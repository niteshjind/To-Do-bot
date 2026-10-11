"""
services/summary_service.py — Daily summary notification logic and dispatch.

Responsibilities:
  1. Determine users eligible for daily task summary delivery based on:
     • daily_summary_enabled == True
     • Valid Telegram chat ID (telegram_user_id is not None)
     • User's local time >= daily_summary_time
     • last_summary_date != local calendar date (YYYY-MM-DD)
  2. Deliver daily summary messages via the Telegram Bot API.
  3. Ensure at-most-once delivery per local calendar day by recording
     last_summary_date ONLY after successful Telegram delivery.
  4. Guard concurrent sweeps via an asyncio.Lock (_summary_poll_lock).
  5. Handle Telegram API errors, timezone discrepancies, and invalid configuration
     gracefully without affecting other users or failing other background jobs.

Concurrency & Delivery Guarantees:
  • Single-process deployment: The in-process asyncio.Lock prevents overlapping
    polling sweeps within this bot process.
  • APScheduler safeguards: Polling job is configured with max_instances=1 and coalesce=True.
  • Multi-process limitation: SQLite operates in single-writer mode and does not support
    distributed row-level locks (e.g. SELECT FOR UPDATE). If scaled horizontally across multiple
    processes, a central distributed lock (Redis) or transactional claim token in the database
    would be required. For the current single-process architecture, in-process mutex plus
    immediate commit upon delivery provides robust deduplication.
  • Network ambiguity: As with any distributed notification system, exactly-once delivery
    cannot be guaranteed if a network timeout occurs after Telegram accepts the message
    but before the HTTP response reaches the bot. In such cases, last_summary_date remains
    uncommitted, potentially resulting in a retry on a subsequent poll.
"""

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Optional, Union

import pytz
from sqlalchemy.orm import Session
from telegram.error import TelegramError

from bot.config import settings
from bot.database.database import get_db
from bot.database.models import User
from bot.services.task_service import DailySummaryDTO, get_daily_summary
from bot.services.user_service import SUMMARY_TIME_REGEX, update_last_summary_date
from bot.utils.keyboards import summary_keyboard
from bot.utils.messages import format_daily_summary_message

logger = logging.getLogger(__name__)

# Mutex to ensure only one instance of process_daily_summaries executes concurrently.
_summary_poll_lock = asyncio.Lock()


async def send_daily_summary(
    bot,
    target: Union[User, int],
    summary: DailySummaryDTO,
) -> bool:
    """
    Format and deliver a daily task summary notification to a user via Telegram.

    Args:
        bot:     Telegram Bot instance (provides send_message).
        target:  Either a User ORM instance or an integer Telegram chat/user ID.
        summary: DailySummaryDTO containing the day's task snapshot.

    Returns:
        True if the message was delivered and accepted by Telegram.
        False if sending failed (network error, user blocked bot, invalid chat ID, etc.).
    """
    if isinstance(target, User):
        chat_id = target.telegram_user_id
    else:
        chat_id = target

    if not chat_id:
        logger.error("Cannot deliver daily summary: missing or empty chat ID.")
        return False

    message_text = format_daily_summary_message(summary)
    reply_markup = summary_keyboard()

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        logger.info(
            "Delivered daily summary to chat_id=%d for local date=%s.",
            chat_id,
            summary.date.isoformat(),
        )
        return True
    except TelegramError as tg_err:
        logger.error(
            "Telegram API error delivering daily summary to chat_id=%d: %s",
            chat_id,
            tg_err,
        )
        return False
    except Exception as exc:
        logger.error(
            "Unexpected error delivering daily summary to chat_id=%d: %s",
            chat_id,
            exc,
            exc_info=True,
        )
        return False


async def _process_summaries_in_session(
    bot,
    db: Session,
    now_utc: Optional[datetime] = None,
) -> int:
    """
    Internal worker: query eligible users, evaluate local schedule, deliver summaries,
    and update last_summary_date for successful sends.

    Args:
        bot:     Telegram Bot instance.
        db:      Active SQLAlchemy database session.
        now_utc: Reference UTC datetime for schedule evaluation.

    Returns:
        Number of successfully delivered daily summaries.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        raise ValueError("now_utc must be a timezone-aware datetime.")

    # Fetch users who have daily summary enabled and a valid Telegram user ID
    users = (
        db.query(User)
        .filter(
            User.daily_summary_enabled.is_(True),
            User.telegram_user_id.isnot(None),
        )
        .all()
    )

    if not users:
        return 0

    delivered_count = 0
    for user in users:
        try:
            # 1. Validate timezone
            tz_str = user.timezone or settings.TIMEZONE
            try:
                local_tz = pytz.timezone(tz_str)
            except Exception:
                logger.warning(
                    "User id=%s has invalid timezone '%s'; skipping daily summary.",
                    user.id,
                    tz_str,
                )
                continue

            # 2. Validate daily_summary_time format
            time_str = user.daily_summary_time or "09:00"
            if not isinstance(time_str, str) or not SUMMARY_TIME_REGEX.match(time_str):
                logger.warning(
                    "User id=%s has invalid daily_summary_time '%s'; skipping daily summary.",
                    user.id,
                    time_str,
                )
                continue

            try:
                target_hour, target_minute = map(int, time_str.split(":"))
            except Exception:
                logger.warning(
                    "Failed to parse daily_summary_time '%s' for user id=%s; skipping.",
                    time_str,
                    user.id,
                )
                continue

            # 3. Calculate user's current local date and time
            now_local = now_utc.astimezone(local_tz)
            today_date = now_local.date()
            today_str = today_date.isoformat()

            # 4. Check if already delivered for today's local date
            if user.last_summary_date == today_str:
                continue

            # 5. Check if scheduled local time has arrived
            if (now_local.hour, now_local.minute) < (target_hour, target_minute):
                continue

            # 6. Build detached summary snapshot before async call
            summary_dto = get_daily_summary(db=db, user=user, target_date=today_date)
            chat_id = user.telegram_user_id

            # 7. Deliver to Telegram
            delivered = await send_daily_summary(bot, chat_id, summary_dto)
            if delivered:
                # Update last_summary_date ONLY after successful Telegram acceptance
                update_last_summary_date(db, user, today_str)
                db.commit()
                delivered_count += 1
            else:
                logger.warning(
                    "Daily summary delivery failed for user id=%s (chat_id=%d); leaving last_summary_date unchanged for retry.",
                    user.id,
                    chat_id,
                )
        except Exception as exc:
            logger.error(
                "Error processing daily summary for user id=%s: %s",
                getattr(user, "id", "unknown"),
                exc,
                exc_info=True,
            )
            db.rollback()

    return delivered_count


async def process_daily_summaries(
    bot,
    now_utc: Optional[datetime] = None,
    db: Optional[Session] = None,
) -> int:
    """
    Main daily summary polling entry point.

    Iterates over eligible users, checks their local schedule, delivers
    the summary if due, and records last_summary_date.
    Guarded by an asyncio.Lock to avoid concurrent duplicate runs.

    Args:
        bot:     Telegram Bot instance.
        now_utc: Optional reference UTC datetime for testing.
        db:      Optional existing database session (primarily for unit tests).
                 If omitted, a session is obtained from `get_db()`.

    Returns:
        Number of successfully delivered daily summaries.
    """
    if _summary_poll_lock.locked():
        logger.debug("process_daily_summaries is already running; skipping concurrent trigger.")
        return 0

    async with _summary_poll_lock:
        if db is not None:
            return await _process_summaries_in_session(bot, db, now_utc)
        else:
            with get_db() as session:
                return await _process_summaries_in_session(bot, session, now_utc)
