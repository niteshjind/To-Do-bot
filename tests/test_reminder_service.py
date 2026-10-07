"""
tests/test_reminder_service.py — Unit and integration tests for reminder_service.py.

Tests cover:
  • format_reminder_message() — message text, local timezone conversion, priority rendering
  • send_task_reminder() — successful dispatch, TelegramError handling, unexpected error, missing user
  • process_due_reminders() — end-to-end delivery cycle, duplicate prevention, partial failure,
    restart recovery, concurrency lock protection, and session management
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session
from telegram.error import TelegramError

from bot.database.models import Task, TaskPriority, TaskStatus, User
from bot.services.reminder_service import (
    _poll_lock,
    format_reminder_message,
    process_due_reminders,
    send_task_reminder,
)
from bot.services.task_service import create_task
from bot.services.user_service import get_or_create_user


@pytest.fixture
def test_user(db_session: Session) -> User:
    """Fixture providing a persisted test user with Asia/Kolkata timezone."""
    user = get_or_create_user(
        db=db_session,
        telegram_user_id=88888,
        username="reminder_tester",
        first_name="ReminderTester",
    )
    user.timezone = "Asia/Kolkata"
    db_session.commit()
    return user


@pytest.fixture
def mock_bot() -> AsyncMock:
    """Fixture providing a mock Telegram Bot with async send_message."""
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock())
    return bot


# ===========================================================================
# Message Formatting Tests
# ===========================================================================

def test_format_reminder_message(test_user: User, db_session: Session) -> None:
    due = datetime(2030, 5, 20, 14, 30, tzinfo=timezone.utc)
    task = create_task(
        db=db_session,
        user=test_user,
        title="Dentist Appointment & Checkup",
        due_at_utc=due,
        priority=TaskPriority.high,
    )
    db_session.commit()

    text = format_reminder_message(task, test_user.timezone)

    assert "Dentist Appointment &amp; Checkup" in text or "Dentist Appointment & Checkup" in text
    assert "High" in text
    assert f"#{task.id}" in text
    # In Asia/Kolkata (UTC+5:30), 14:30 UTC is 20:00 (8:00 PM) local
    assert "20:00" in text


# ===========================================================================
# send_task_reminder Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_send_task_reminder_success(test_user: User, db_session: Session, mock_bot: AsyncMock) -> None:
    due = datetime.now(timezone.utc)
    task = create_task(db=db_session, user=test_user, title="Call Dentist", due_at_utc=due)
    db_session.commit()

    success = await send_task_reminder(mock_bot, task)

    assert success is True
    mock_bot.send_message.assert_awaited_once()
    _, kwargs = mock_bot.send_message.call_args
    assert kwargs["chat_id"] == test_user.telegram_user_id
    assert "Call Dentist" in kwargs["text"]
    assert kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
async def test_send_task_reminder_telegram_error(test_user: User, db_session: Session, mock_bot: AsyncMock) -> None:
    due = datetime.now(timezone.utc)
    task = create_task(db=db_session, user=test_user, title="Failing Task", due_at_utc=due)
    db_session.commit()

    mock_bot.send_message.side_effect = TelegramError("Forbidden: bot was blocked by the user")

    success = await send_task_reminder(mock_bot, task)

    assert success is False
    mock_bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_task_reminder_unexpected_error(test_user: User, db_session: Session, mock_bot: AsyncMock) -> None:
    due = datetime.now(timezone.utc)
    task = create_task(db=db_session, user=test_user, title="Unexpected error", due_at_utc=due)
    db_session.commit()

    mock_bot.send_message.side_effect = RuntimeError("Connection dropped unexpectedly")

    success = await send_task_reminder(mock_bot, task)

    assert success is False


@pytest.mark.asyncio
async def test_send_task_reminder_missing_user(db_session: Session, mock_bot: AsyncMock) -> None:
    task = Task(id=999, title="Orphan", due_at=datetime.now(timezone.utc), user=None)
    success = await send_task_reminder(mock_bot, task)
    assert success is False
    mock_bot.send_message.assert_not_awaited()


# ===========================================================================
# process_due_reminders Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_process_due_reminders_empty(db_session: Session, mock_bot: AsyncMock) -> None:
    delivered = await process_due_reminders(mock_bot, db=db_session)
    assert delivered == 0
    mock_bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_due_reminders_success(test_user: User, db_session: Session, mock_bot: AsyncMock) -> None:
    now = datetime.now(timezone.utc)
    t = create_task(db=db_session, user=test_user, title="Past due item", due_at_utc=now - timedelta(minutes=5))
    db_session.commit()

    delivered = await process_due_reminders(mock_bot, now_utc=now, db=db_session)

    assert delivered == 1
    mock_bot.send_message.assert_awaited_once()

    refreshed = db_session.query(Task).filter_by(id=t.id).one()
    assert refreshed.reminder_sent is True


@pytest.mark.asyncio
async def test_process_due_reminders_delivery_failure_keeps_flag_false(
    test_user: User, db_session: Session, mock_bot: AsyncMock
) -> None:
    now = datetime.now(timezone.utc)
    t = create_task(db=db_session, user=test_user, title="Failed delivery item", due_at_utc=now - timedelta(minutes=5))
    db_session.commit()

    mock_bot.send_message.side_effect = TelegramError("Network timeout")

    delivered = await process_due_reminders(mock_bot, now_utc=now, db=db_session)

    assert delivered == 0
    refreshed = db_session.query(Task).filter_by(id=t.id).one()
    assert refreshed.reminder_sent is False  # Must NOT be marked sent


@pytest.mark.asyncio
async def test_process_due_reminders_partial_delivery(
    test_user: User, db_session: Session, mock_bot: AsyncMock
) -> None:
    now = datetime.now(timezone.utc)
    t1 = create_task(db=db_session, user=test_user, title="First Due", due_at_utc=now - timedelta(minutes=10))
    t2 = create_task(db=db_session, user=test_user, title="Second Due", due_at_utc=now - timedelta(minutes=5))
    db_session.commit()

    # First succeeds, second raises error
    mock_bot.send_message.side_effect = [MagicMock(), TelegramError("Rate limit exceeded")]

    delivered = await process_due_reminders(mock_bot, now_utc=now, db=db_session)

    assert delivered == 1
    assert mock_bot.send_message.await_count == 2

    r1 = db_session.query(Task).filter_by(id=t1.id).one()
    r2 = db_session.query(Task).filter_by(id=t2.id).one()
    assert r1.reminder_sent is True
    assert r2.reminder_sent is False


@pytest.mark.asyncio
async def test_process_due_reminders_duplicate_prevention_repeat_run(
    test_user: User, db_session: Session, mock_bot: AsyncMock
) -> None:
    now = datetime.now(timezone.utc)
    t = create_task(db=db_session, user=test_user, title="One-off Reminder", due_at_utc=now - timedelta(minutes=2))
    db_session.commit()

    # First cycle
    d1 = await process_due_reminders(mock_bot, now_utc=now, db=db_session)
    assert d1 == 1
    assert mock_bot.send_message.await_count == 1

    # Second cycle with same or slightly later time
    d2 = await process_due_reminders(mock_bot, now_utc=now + timedelta(seconds=30), db=db_session)
    assert d2 == 0
    # send_message should NOT have been called again!
    assert mock_bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_process_due_reminders_restart_recovery_behavior(
    test_user: User, db_session: Session, mock_bot: AsyncMock
) -> None:
    """
    Simulate bot being offline during reminder trigger.
    On next cycle (startup sweep), overdue tasks must be picked up and delivered.
    """
    past = datetime.now(timezone.utc) - timedelta(hours=3)
    t_overdue = create_task(db=db_session, user=test_user, title="Overdue while offline", due_at_utc=past)
    db_session.commit()

    now = datetime.now(timezone.utc)
    delivered = await process_due_reminders(mock_bot, now_utc=now, db=db_session)

    assert delivered == 1
    refreshed = db_session.query(Task).filter_by(id=t_overdue.id).one()
    assert refreshed.reminder_sent is True


@pytest.mark.asyncio
async def test_process_due_reminders_with_get_db(
    test_user: User, db_session: Session, mock_bot: AsyncMock
) -> None:
    """Test process_due_reminders when no db session is explicitly passed (uses get_db context manager)."""
    now = datetime.now(timezone.utc)
    t = create_task(db=db_session, user=test_user, title="Test get_db fallback", due_at_utc=now - timedelta(minutes=1))
    db_session.commit()

    with patch("bot.services.reminder_service.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db_session
        mock_get_db.return_value.__exit__.return_value = False

        delivered = await process_due_reminders(mock_bot, now_utc=now)

    assert delivered == 1
    refreshed = db_session.query(Task).filter_by(id=t.id).one()
    assert refreshed.reminder_sent is True


@pytest.mark.asyncio
async def test_process_due_reminders_concurrency_lock_skips_when_locked(
    mock_bot: AsyncMock
) -> None:
    """Verify that if _poll_lock is already acquired, concurrent call returns 0 without executing."""
    async with _poll_lock:
        delivered = await process_due_reminders(mock_bot)
        assert delivered == 0
        mock_bot.send_message.assert_not_awaited()
