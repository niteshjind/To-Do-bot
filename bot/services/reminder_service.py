"""
services/reminder_service.py — Reminder notification logic and dispatch.

Responsibilities:
  1. Format reminder notification messages with local timezone and priority info.
  2. Deliver reminder messages to users via the Telegram Bot API.
  3. Ensure duplicate prevention by marking `reminder_sent = True` ONLY after
     successful delivery.
  4. Coordinate periodic reminder polling (`process_due_reminders`), guarded by
     an asyncio.Lock to prevent overlapping sweeps.
  5. Handle Telegram API errors, transient network faults, or blocked bots gracefully.
"""

import asyncio
import html
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from telegram.error import TelegramError

from bot.config import settings
from bot.database.database import get_db
from bot.database.models import Task
from bot.services.task_service import get_due_tasks, mark_reminder_sent
from bot.utils.datetime_utils import format_dt_local
from bot.utils.keyboards import PRIORITY_ICONS, reminder_keyboard
from bot.utils.messages import REMINDER_NOTIFICATION

logger = logging.getLogger(__name__)

# Mutex to ensure only one instance of process_due_reminders executes at any given time.
_poll_lock = asyncio.Lock()


def format_reminder_message(task: Task, tz_string: str) -> str:
    """
    Build the formatted HTML message for a task reminder notification.

    Args:
        task: The Task model instance.
        tz_string: IANA timezone name (e.g. "Asia/Kolkata").

    Returns:
        Formatted HTML string ready for Telegram delivery.
    """
    due_str = format_dt_local(task.due_at, tz_string) if task.due_at else "Not set"
    p_icon = PRIORITY_ICONS.get(task.priority.value, "⚪")
    p_label = task.priority.value.capitalize()

    return REMINDER_NOTIFICATION.format(
        task_id=task.id,
        title=html.escape(task.title),
        due_display=due_str,
        priority_icon=p_icon,
        priority_label=p_label,
    )


async def send_task_reminder(bot, task: Task) -> bool:
    """
    Format and send a reminder notification to the task owner via Telegram.

    Args:
        bot: Telegram Bot instance (provides send_message).
        task: Task model instance (must have user relationship populated).

    Returns:
        True if the message was delivered successfully.
        False if sending failed (network error, user blocked bot, invalid chat ID, etc.).
    """
    user = task.user
    if user is None or not user.telegram_user_id:
        logger.error("Cannot deliver reminder for task #%d: missing user or telegram_user_id.", task.id)
        return False

    chat_id = user.telegram_user_id
    tz_string = user.timezone or settings.TIMEZONE
    message_text = format_reminder_message(task, tz_string)
    reply_markup = reminder_keyboard(task.id)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        logger.info(
            "Delivered reminder for task #%d to user telegram_id=%d.",
            task.id,
            chat_id,
        )
        return True
    except TelegramError as tg_err:
        logger.error(
            "Telegram API error delivering reminder for task #%d to chat_id=%d: %s",
            task.id,
            chat_id,
            tg_err,
        )
        return False
    except Exception as exc:
        logger.error(
            "Unexpected error delivering reminder for task #%d to chat_id=%d: %s",
            task.id,
            chat_id,
            exc,
            exc_info=True,
        )
        return False


async def _process_reminders_in_session(
    bot,
    db: Session,
    now_utc: Optional[datetime] = None,
) -> int:
    """
    Internal worker: fetch due tasks, deliver messages, and commit reminder_sent.
    """
    due_tasks = get_due_tasks(db, now_utc)
    if not due_tasks:
        return 0

    delivered_count = 0
    for task in due_tasks:
        try:
            delivered = await send_task_reminder(bot, task)
            if delivered:
                # Mark reminder_sent ONLY after successful Telegram delivery
                mark_reminder_sent(db, task)
                db.commit()
                delivered_count += 1
            else:
                logger.warning(
                    "Reminder delivery for task #%d failed; leaving reminder_sent=False for retry.",
                    task.id,
                )
        except Exception as exc:
            logger.error(
                "Error processing reminder for task #%d: %s",
                task.id,
                exc,
                exc_info=True,
            )
            db.rollback()

    return delivered_count


async def process_due_reminders(
    bot,
    now_utc: Optional[datetime] = None,
    db: Optional[Session] = None,
) -> int:
    """
    Main reminder processing entry point.

    Fetches all due pending tasks, delivers notifications, and marks them sent.
    Guarded by an asyncio.Lock to avoid concurrent duplicate runs.

    Args:
        bot: Telegram Bot instance.
        now_utc: Optional reference UTC datetime for testing.
        db: Optional existing database session (primarily for unit tests).
            If omitted, a session is obtained from `get_db()`.

    Returns:
        Number of successfully delivered reminders.
    """
    if _poll_lock.locked():
        logger.debug("process_due_reminders is already running; skipping concurrent trigger.")
        return 0

    async with _poll_lock:
        if db is not None:
            return await _process_reminders_in_session(bot, db, now_utc)
        else:
            with get_db() as session:
                return await _process_reminders_in_session(bot, session, now_utc)
