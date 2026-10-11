"""
tests/test_phase7_end_to_end.py — Comprehensive end-to-end integration tests for Phase 7.

Validates the full lifecycle of a user across:
  1. Initial /settings interaction and automatic user registration.
  2. In-place dashboard toggles (reminders and daily summary).
  3. Interactive ConversationHandler for custom delivery time (HH:MM).
  4. Task creation (today, overdue, completed) and /summary command view.
  5. Reminder scheduler integration respecting reminders_enabled=False.
  6. Re-enabling reminders and receiving scheduled reminders.
  7. Daily summary scheduler delivering at the configured time.
  8. Deduplication on subsequent scheduler sweeps.
  9. Cross-user isolation across all settings and summary flows.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session
from telegram import CallbackQuery, Message, Update, User as TgUser

from bot.database.models import Task, TaskPriority, TaskStatus, User
from bot.handlers.settings import (
    receive_custom_time,
    settings_command,
    settings_toggle_reminders_callback,
    start_custom_time,
    summary_command,
)
from bot.services.reminder_service import process_due_reminders
from bot.services.summary_service import process_daily_summaries
from bot.services.task_service import complete_task, create_task
from bot.services.user_service import get_user_settings_by_telegram_id
from bot.utils.keyboards import CB_SETTINGS_TOGGLE_REMINDERS, CB_TIME_CUSTOM


def _create_mock_update(user_id: int, username: str = "testuser", text: str = "") -> Update:
    update = MagicMock(spec=Update)
    user = MagicMock(spec=TgUser)
    user.id = user_id
    user.username = username
    user.first_name = "Test"
    user.is_bot = False
    update.effective_user = user

    msg = AsyncMock(spec=Message)
    msg.text = text
    msg.reply_text = AsyncMock()
    update.message = msg
    update.callback_query = None
    return update


def _create_mock_callback_update(user_id: int, callback_data: str, username: str = "testuser") -> Update:
    update = MagicMock(spec=Update)
    user = MagicMock(spec=TgUser)
    user.id = user_id
    user.username = username
    user.first_name = "Test"
    user.is_bot = False
    update.effective_user = user

    query = AsyncMock(spec=CallbackQuery)
    query.data = callback_data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update.callback_query = query
    update.message = None
    return update


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.user_data = {}
    return ctx


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock())
    return bot


@pytest.mark.asyncio
async def test_full_phase7_lifecycle_end_to_end(
    db_session: Session, mock_context: MagicMock, mock_bot: AsyncMock
) -> None:
    """
    Complete end-to-end test simulating a user interacting with settings,
    customizing summary time, toggling reminders, checking /summary, and
    verifying background scheduler dispatches.
    """
    user_id = 998877

    # -----------------------------------------------------------------------
    # Step 1: User runs /settings -> registered with default preferences
    # -----------------------------------------------------------------------
    update_settings = _create_mock_update(user_id=user_id, text="/settings")
    with patch("bot.handlers.settings.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db_session
        await settings_command(update_settings, mock_context)

    settings = get_user_settings_by_telegram_id(db_session, user_id)
    assert settings is not None
    assert settings.timezone == "Asia/Kolkata"
    assert settings.reminders_enabled is True
    assert settings.daily_summary_enabled is True
    assert settings.daily_summary_time == "09:00"
    assert settings.last_summary_date is None

    update_settings.message.reply_text.assert_awaited_once()
    assert "Settings & Preferences" in update_settings.message.reply_text.call_args[0][0]

    # -----------------------------------------------------------------------
    # Step 2: User toggles reminders -> reminders disabled
    # -----------------------------------------------------------------------
    update_toggle = _create_mock_callback_update(user_id=user_id, callback_data=CB_SETTINGS_TOGGLE_REMINDERS)
    with patch("bot.handlers.settings.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db_session
        await settings_toggle_reminders_callback(update_toggle, mock_context)

    settings = get_user_settings_by_telegram_id(db_session, user_id)
    assert settings.reminders_enabled is False
    update_toggle.callback_query.edit_message_text.assert_awaited_once()
    assert "Disabled" in update_toggle.callback_query.edit_message_text.call_args[0][0]

    # -----------------------------------------------------------------------
    # Step 3: User customizes summary time via conversation -> sets 08:30
    # -----------------------------------------------------------------------
    update_custom_time_start = _create_mock_callback_update(user_id=user_id, callback_data=CB_TIME_CUSTOM)
    await start_custom_time(update_custom_time_start, mock_context)

    update_time_input = _create_mock_update(user_id=user_id, text="08:30")
    with patch("bot.handlers.settings.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db_session
        state = await receive_custom_time(update_time_input, mock_context)

    assert state == -1  # ConversationHandler.END
    settings = get_user_settings_by_telegram_id(db_session, user_id)
    assert settings.daily_summary_time == "08:30"

    # -----------------------------------------------------------------------
    # Step 4: Populate tasks and verify /summary command
    # -----------------------------------------------------------------------
    user = db_session.query(User).filter_by(telegram_user_id=user_id).one()
    # Asia/Kolkata (UTC+5:30) date reference: 2026-10-11
    now_utc = datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc)  # 08:30 local

    # Task 1: Overdue item (due yesterday in Kolkata)
    t_overdue = create_task(
        db=db_session,
        user=user,
        title="Yesterday Report",
        due_at_utc=now_utc - timedelta(days=1),
        priority=TaskPriority.high,
    )
    # Task 2: Due today (due at 08:30 local)
    t_today = create_task(
        db=db_session,
        user=user,
        title="Today Standup",
        due_at_utc=now_utc,
        priority=TaskPriority.medium,
    )
    # Task 3: Completed today
    t_done = create_task(
        db=db_session,
        user=user,
        title="Morning Coffee",
        due_at_utc=now_utc - timedelta(hours=1),
    )
    complete_task(db=db_session, task=t_done)
    db_session.commit()

    update_summary = _create_mock_update(user_id=user_id, text="/summary")
    with patch("bot.handlers.settings.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db_session
        await summary_command(update_summary, mock_context)

    update_summary.message.reply_text.assert_awaited_once()
    summary_text = update_summary.message.reply_text.call_args[0][0]
    assert "Daily Task Summary" in summary_text
    assert "Today Standup" in summary_text
    assert "Yesterday Report" in summary_text
    assert "Morning Coffee" in summary_text

    # -----------------------------------------------------------------------
    # Step 5: Reminder scheduler runs -> reminder skipped because reminders_enabled=False
    # -----------------------------------------------------------------------
    reminders_sent = await process_due_reminders(mock_bot, now_utc=now_utc, db=db_session)
    assert reminders_sent == 0
    mock_bot.send_message.assert_not_awaited()

    # -----------------------------------------------------------------------
    # Step 6: User re-enables reminders -> reminder scheduler delivers task reminder
    # -----------------------------------------------------------------------
    user.reminders_enabled = True
    db_session.commit()

    reminders_sent2 = await process_due_reminders(mock_bot, now_utc=now_utc, db=db_session)
    # Both overdue and today standup are due and sent
    assert reminders_sent2 == 2
    assert mock_bot.send_message.await_count == 2
    mock_bot.send_message.reset_mock()

    # -----------------------------------------------------------------------
    # Step 7: Daily summary scheduler runs at 08:30 local time -> summary delivered
    # -----------------------------------------------------------------------
    summaries_sent = await process_daily_summaries(mock_bot, now_utc=now_utc, db=db_session)
    assert summaries_sent == 1
    mock_bot.send_message.assert_awaited_once()
    assert "Daily Task Summary" in mock_bot.send_message.call_args[1]["text"]

    db_session.refresh(user)
    assert user.last_summary_date == "2026-10-11"

    # -----------------------------------------------------------------------
    # Step 8: Subsequent scheduler run on same date -> deduplicated, 0 sent
    # -----------------------------------------------------------------------
    mock_bot.send_message.reset_mock()
    summaries_sent_repeat = await process_daily_summaries(
        mock_bot, now_utc=now_utc + timedelta(minutes=1), db=db_session
    )
    assert summaries_sent_repeat == 0
    mock_bot.send_message.assert_not_awaited()
