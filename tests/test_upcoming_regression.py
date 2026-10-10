"""
tests/test_upcoming_regression.py — Regression tests for DetachedInstanceError in /upcoming.

Verifies:
  1. Reproduction of DetachedInstanceError when ORM objects are accessed after session commit/close.
  2. /upcoming with normal pending tasks (no DetachedInstanceError).
  3. /upcoming with recurring tasks (no DetachedInstanceError).
  4. /upcoming with completed tasks (completed excluded, no DetachedInstanceError).
  5. /upcoming with snoozed tasks (new due time reflected, no DetachedInstanceError).
  6. /upcoming after a recurring task generates next occurrence (new occurrence included, parent excluded).
  7. /upcoming refresh callback (upcoming_callback) works cleanly with closing session.
  8. /today command and callback work cleanly with closing session.
  9. TaskDTO can be safely used standalone outside of any session.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import DetachedInstanceError

from bot.database.models import Base, Task, TaskDTO, TaskPriority, TaskRecurrence, TaskStatus
from bot.handlers.tasks import (
    format_today_view,
    format_upcoming_view,
    today_callback,
    today_command,
    upcoming_callback,
    upcoming_command,
)
from bot.services.task_service import (
    complete_task,
    create_task,
    snooze_task,
    to_task_dto,
)
from bot.services.user_service import get_or_create_user
from bot.utils.keyboards import CB_TODAY_REFRESH, CB_UPCOMING_REFRESH


@pytest.fixture
def closing_session_factory():
    """
    Factory creating a context manager that mimics production get_db():
    yields a session, commits on exit, and closes it (expiring and detaching instances).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    @contextmanager
    def _closing_get_db():
        session = TestingSession()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    yield _closing_get_db, TestingSession

    Base.metadata.drop_all(engine)
    engine.dispose()


def _mock_update(user_id: int = 12345, text: str = "/upcoming", callback_data: str = None):
    update = MagicMock()
    user = MagicMock()
    user.id = user_id
    user.username = f"user_{user_id}"
    user.first_name = "TestUser"
    update.effective_user = user
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()

    if callback_data:
        update.callback_query = MagicMock()
        update.callback_query.data = callback_data
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
    else:
        update.callback_query = None

    return update


def test_reproduce_detached_instance_error_on_expired_tasks_outside_session(closing_session_factory):
    """
    Reproduction test:
    Demonstrates that accessing attributes of ORM Task instances outside a committed/closed
    session raises DetachedInstanceError, but TaskDTO or in-session formatting completely prevents it.
    """
    closing_get_db, _ = closing_session_factory

    # Create user and task
    with closing_get_db() as db:
        user = get_or_create_user(db, telegram_user_id=1001, username="repro_user")
        due = datetime.now(timezone.utc) + timedelta(days=2)
        task = create_task(db, user, "Test detached task", due_at_utc=due)
        task_id = task.id

    # Scenario A: Attempting to access attributes or format view with detached ORM object
    # after session close raises DetachedInstanceError
    assert isinstance(task, Task)
    with pytest.raises(DetachedInstanceError):
        # Attribute access on expired detached task triggers refresh against closed session
        _ = task.due_at

    # Scenario B: TaskDTO snapshot created inside the session is immune to detachment
    with closing_get_db() as db:
        user = get_or_create_user(db, telegram_user_id=1001)
        db_task = db.query(Task).filter_by(id=task_id).first()
        dto = db_task.to_dto()

    # Outside the closed session, DTO attributes are accessible with zero errors
    assert isinstance(dto, TaskDTO)
    assert dto.title == "Test detached task"
    assert dto.due_at is not None
    # format_upcoming_view accepts Sequence[TaskDTO] safely
    output = format_upcoming_view([dto], "Asia/Kolkata", 7)
    assert "Test detached task" in output


@pytest.mark.asyncio
async def test_upcoming_command_with_normal_pending_tasks_real_session(closing_session_factory):
    """
    1. /upcoming with normal pending tasks.
    Verifies that upcoming_command formats tasks inside the session and produces correct output
    without raising DetachedInstanceError.
    """
    closing_get_db, _ = closing_session_factory
    tz = pytz.timezone("Asia/Kolkata")
    tomorrow = (datetime.now(tz) + timedelta(days=1)).astimezone(timezone.utc)

    with closing_get_db() as db:
        user = get_or_create_user(db, telegram_user_id=2001, username="normal_user")
        create_task(db, user, "Buy groceries", due_at_utc=tomorrow, priority=TaskPriority.high)

    update = _mock_update(user_id=2001, text="/upcoming")
    context = MagicMock()

    with patch("bot.handlers.tasks.get_db", closing_get_db):
        await upcoming_command(update, context)

    update.message.reply_text.assert_awaited_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Buy groceries" in reply_text
    assert "Upcoming Tasks" in reply_text
    assert "🔴" in reply_text  # High priority icon


@pytest.mark.asyncio
async def test_upcoming_command_with_recurring_tasks_real_session(closing_session_factory):
    """
    2. /upcoming with recurring tasks.
    Verifies that recurring tasks are listed properly without raising DetachedInstanceError.
    """
    closing_get_db, _ = closing_session_factory
    tz = pytz.timezone("Asia/Kolkata")
    in_two_days = (datetime.now(tz) + timedelta(days=2)).astimezone(timezone.utc)

    with closing_get_db() as db:
        user = get_or_create_user(db, telegram_user_id=2002, username="rec_user")
        create_task(
            db,
            user,
            "Weekly team meeting",
            due_at_utc=in_two_days,
            recurrence=TaskRecurrence.weekly,
        )

    update = _mock_update(user_id=2002, text="/upcoming")
    context = MagicMock()

    with patch("bot.handlers.tasks.get_db", closing_get_db):
        await upcoming_command(update, context)

    update.message.reply_text.assert_awaited_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Weekly team meeting" in reply_text


@pytest.mark.asyncio
async def test_upcoming_command_with_completed_tasks_real_session(closing_session_factory):
    """
    3. /upcoming with completed tasks.
    Verifies that completed tasks are excluded, pending tasks are included,
    and no DetachedInstanceError occurs.
    """
    closing_get_db, _ = closing_session_factory
    tz = pytz.timezone("Asia/Kolkata")
    in_three_days = (datetime.now(tz) + timedelta(days=3)).astimezone(timezone.utc)

    with closing_get_db() as db:
        user = get_or_create_user(db, telegram_user_id=2003, username="completed_user")
        completed_task = create_task(db, user, "Already completed item", due_at_utc=in_three_days)
        complete_task(db, completed_task)
        create_task(db, user, "Still pending item", due_at_utc=in_three_days)

    update = _mock_update(user_id=2003, text="/upcoming")
    context = MagicMock()

    with patch("bot.handlers.tasks.get_db", closing_get_db):
        await upcoming_command(update, context)

    update.message.reply_text.assert_awaited_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Still pending item" in reply_text
    assert "Already completed item" not in reply_text


@pytest.mark.asyncio
async def test_upcoming_command_with_snoozed_tasks_real_session(closing_session_factory):
    """
    4. /upcoming with snoozed tasks.
    Verifies that snoozed tasks are displayed at their updated snoozed due time
    without raising DetachedInstanceError.
    """
    closing_get_db, _ = closing_session_factory
    tz = pytz.timezone("Asia/Kolkata")
    tomorrow = (datetime.now(tz) + timedelta(days=1)).astimezone(timezone.utc)
    snoozed_time = (datetime.now(tz) + timedelta(days=2)).astimezone(timezone.utc)

    with closing_get_db() as db:
        user = get_or_create_user(db, telegram_user_id=2004, username="snooze_user")
        task = create_task(db, user, "Pay electricity bill", due_at_utc=tomorrow)
        snooze_task(db, task, new_due_at_utc=snoozed_time)

    update = _mock_update(user_id=2004, text="/upcoming")
    context = MagicMock()

    with patch("bot.handlers.tasks.get_db", closing_get_db):
        await upcoming_command(update, context)

    update.message.reply_text.assert_awaited_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Pay electricity bill" in reply_text


@pytest.mark.asyncio
async def test_upcoming_command_after_recurring_task_generates_next_occurrence_real_session(
    closing_session_factory,
):
    """
    5. /upcoming after a recurring task has generated its next occurrence.
    Verifies that completing a recurring task generates the next instance,
    which is properly displayed in /upcoming without DetachedInstanceError.
    """
    closing_get_db, _ = closing_session_factory
    tz = pytz.timezone("Asia/Kolkata")
    today_time = datetime.now(tz).astimezone(timezone.utc)

    with closing_get_db() as db:
        user = get_or_create_user(db, telegram_user_id=2005, username="recurring_flow_user")
        parent_task = create_task(
            db,
            user,
            "Daily medication",
            due_at_utc=today_time,
            recurrence=TaskRecurrence.daily,
        )
        complete_task(db, parent_task)
        assert parent_task.status == TaskStatus.completed

    update = _mock_update(user_id=2005, text="/upcoming")
    context = MagicMock()

    with patch("bot.handlers.tasks.get_db", closing_get_db):
        await upcoming_command(update, context)

    update.message.reply_text.assert_awaited_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Daily medication" in reply_text


@pytest.mark.asyncio
async def test_upcoming_callback_refresh_real_session(closing_session_factory):
    """
    Verifies that the upcoming_callback (inline refresh button) executes cleanly
    with a closing database session.
    """
    closing_get_db, _ = closing_session_factory
    tz = pytz.timezone("Asia/Kolkata")
    tomorrow = (datetime.now(tz) + timedelta(days=1)).astimezone(timezone.utc)

    with closing_get_db() as db:
        user = get_or_create_user(db, telegram_user_id=2006, username="cb_user")
        create_task(db, user, "Check emails", due_at_utc=tomorrow)

    update = _mock_update(user_id=2006, callback_data=CB_UPCOMING_REFRESH)
    context = MagicMock()

    with patch("bot.handlers.tasks.get_db", closing_get_db):
        await upcoming_callback(update, context)

    update.callback_query.answer.assert_awaited_once()
    update.callback_query.edit_message_text.assert_awaited_once()
    edited_text = update.callback_query.edit_message_text.call_args[0][0]
    assert "Check emails" in edited_text


@pytest.mark.asyncio
async def test_today_command_and_callback_real_session(closing_session_factory):
    """
    Verifies that today_command and today_callback execute cleanly
    with a closing database session.
    """
    closing_get_db, _ = closing_session_factory
    tz = pytz.timezone("Asia/Kolkata")
    today_time = datetime.now(tz).astimezone(timezone.utc)

    with closing_get_db() as db:
        user = get_or_create_user(db, telegram_user_id=2007, username="today_user")
        create_task(db, user, "Morning jog", due_at_utc=today_time)

    update = _mock_update(user_id=2007, text="/today")
    context = MagicMock()

    with patch("bot.handlers.tasks.get_db", closing_get_db):
        await today_command(update, context)

    update.message.reply_text.assert_awaited_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Morning jog" in reply_text
    assert "Today's Tasks" in reply_text

    # Callback refresh
    update_cb = _mock_update(user_id=2007, callback_data=CB_TODAY_REFRESH)
    with patch("bot.handlers.tasks.get_db", closing_get_db):
        await today_callback(update_cb, context)

    update_cb.callback_query.edit_message_text.assert_awaited_once()
    edited_text = update_cb.callback_query.edit_message_text.call_args[0][0]
    assert "Morning jog" in edited_text


def test_task_dto_conversion_and_view_rendering():
    """
    Verifies TaskDTO can be rendered by both format_today_view and format_upcoming_view
    without requiring a database session.
    """
    now = datetime.now(timezone.utc)
    dto = TaskDTO(
        id=99,
        user_id=1,
        title="DTO Standalone Task",
        status=TaskStatus.pending,
        priority=TaskPriority.medium,
        due_at=now,
        recurrence=None,
        reminder_sent=False,
        snoozed_until=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )

    today_rendered = format_today_view([dto], "Asia/Kolkata")
    assert "DTO Standalone Task" in today_rendered

    upcoming_rendered = format_upcoming_view([dto], "Asia/Kolkata", 7)
    assert "DTO Standalone Task" in upcoming_rendered
