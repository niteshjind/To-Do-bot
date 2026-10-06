"""
tests/test_handlers.py — Unit tests for Telegram handlers in Phase 2.

Tests cover:
  • add_start(): initializes state, asks for title, returns ASK_TITLE
  • receive_title(): validates title (empty, too long, valid), returns ASK_DATE
  • receive_date(): validates date format, returns ASK_TIME
  • receive_time(): validates time format and past-time checks, returns ASK_PRIORITY
  • receive_priority(): updates priority, displays confirm summary, returns CONFIRM
  • receive_confirmation(): handles save (DB write + success) and cancel (abort)
  • cancel_add(): cancels flow from any step
  • button guards: handles user typing text when keyboard input expected
"""

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.ext import ConversationHandler

from bot.database.models import Task, TaskPriority, TaskStatus
from bot.handlers.tasks import (
    ASK_DATE,
    ASK_PRIORITY,
    ASK_TIME,
    ASK_TITLE,
    CONFIRM,
    UD_DATE,
    UD_PRIORITY,
    UD_TIME,
    UD_TIMEZONE,
    UD_TITLE,
    add_start,
    cancel_add,
    confirm_text_guard,
    priority_text_guard,
    receive_confirmation,
    receive_date,
    receive_priority,
    receive_time,
    receive_title,
    today_callback,
    today_command,
    upcoming_callback,
    upcoming_command,
)
from bot.utils.keyboards import (
    CB_CONFIRM_CANCEL,
    CB_CONFIRM_SAVE,
    CB_PRIORITY_HIGH,
    CB_PRIORITY_LOW,
    CB_TODAY_REFRESH,
    CB_UPCOMING_REFRESH,
    CB_VIEW_TODAY,
    CB_VIEW_UPCOMING,
)


@pytest.fixture
def mock_context():
    context = MagicMock()
    context.user_data = {}
    return context


def _create_mock_update(user_id=12345, username="testuser", text="", callback_data=None):
    update = MagicMock()
    user = MagicMock()
    user.id = user_id
    user.username = username
    user.first_name = "Test"
    update.effective_user = user

    message = MagicMock()
    message.text = text
    message.reply_text = AsyncMock()
    update.message = message
    update.effective_message = message

    if callback_data:
        cb = MagicMock()
        cb.data = callback_data
        cb.answer = AsyncMock()
        cb.edit_message_text = AsyncMock()
        cb.message = message
        update.callback_query = cb
    else:
        update.callback_query = None

    return update


@pytest.mark.asyncio
async def test_add_start(db_session, mock_context):
    update = _create_mock_update(user_id=12345, text="/add")

    with patch("bot.handlers.tasks.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db_session
        state = await add_start(update, mock_context)

    assert state == ASK_TITLE
    assert mock_context.user_data[UD_TIMEZONE] == "Asia/Kolkata"
    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_receive_title_valid(mock_context):
    mock_context.user_data[UD_TIMEZONE] = "Asia/Kolkata"
    update = _create_mock_update(text="Submit report")

    state = await receive_title(update, mock_context)

    assert state == ASK_DATE
    assert mock_context.user_data[UD_TITLE] == "Submit report"
    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_receive_title_empty(mock_context):
    mock_context.user_data[UD_TIMEZONE] = "Asia/Kolkata"
    update = _create_mock_update(text="   ")

    state = await receive_title(update, mock_context)

    assert state == ASK_TITLE
    assert UD_TITLE not in mock_context.user_data
    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_receive_title_too_long(mock_context):
    mock_context.user_data[UD_TIMEZONE] = "Asia/Kolkata"
    update = _create_mock_update(text="A" * 501)

    state = await receive_title(update, mock_context)

    assert state == ASK_TITLE
    assert UD_TITLE not in mock_context.user_data


@pytest.mark.asyncio
async def test_receive_date_valid(mock_context):
    mock_context.user_data[UD_TIMEZONE] = "Asia/Kolkata"
    update = _create_mock_update(text="15/10/2026")

    state = await receive_date(update, mock_context)

    assert state == ASK_TIME
    assert mock_context.user_data[UD_DATE] == date(2026, 10, 15)
    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_receive_date_invalid(mock_context):
    mock_context.user_data[UD_TIMEZONE] = "Asia/Kolkata"
    update = _create_mock_update(text="2026-10-15")

    state = await receive_date(update, mock_context)

    assert state == ASK_DATE
    assert UD_DATE not in mock_context.user_data


@pytest.mark.asyncio
async def test_receive_time_valid(mock_context):
    mock_context.user_data[UD_TIMEZONE] = "Asia/Kolkata"
    # Set date in far future so time validation passes
    mock_context.user_data[UD_DATE] = date(2030, 1, 1)
    update = _create_mock_update(text="14:30")

    state = await receive_time(update, mock_context)

    assert state == ASK_PRIORITY
    assert mock_context.user_data[UD_TIME] == time(14, 30)
    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_receive_time_invalid_format(mock_context):
    mock_context.user_data[UD_TIMEZONE] = "Asia/Kolkata"
    mock_context.user_data[UD_DATE] = date(2030, 1, 1)
    update = _create_mock_update(text="2:30pm")

    state = await receive_time(update, mock_context)

    assert state == ASK_TIME
    assert UD_TIME not in mock_context.user_data


@pytest.mark.asyncio
async def test_receive_time_in_past(mock_context):
    mock_context.user_data[UD_TIMEZONE] = "Asia/Kolkata"
    mock_context.user_data[UD_DATE] = date(2000, 1, 1)
    update = _create_mock_update(text="10:00")

    state = await receive_time(update, mock_context)

    assert state == ASK_TIME
    assert UD_TIME not in mock_context.user_data


@pytest.mark.asyncio
async def test_receive_priority(mock_context):
    mock_context.user_data[UD_TIMEZONE] = "Asia/Kolkata"
    mock_context.user_data[UD_TITLE] = "Finish assignment"
    mock_context.user_data[UD_DATE] = date(2030, 1, 1)
    mock_context.user_data[UD_TIME] = time(10, 0)
    update = _create_mock_update(callback_data=CB_PRIORITY_HIGH)

    state = await receive_priority(update, mock_context)

    assert state == CONFIRM
    assert mock_context.user_data[UD_PRIORITY] == TaskPriority.high
    update.callback_query.answer.assert_awaited_once()
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_receive_confirmation_save(db_session, mock_context):
    mock_context.user_data[UD_TIMEZONE] = "Asia/Kolkata"
    mock_context.user_data[UD_TITLE] = "Test Task Save"
    mock_context.user_data[UD_DATE] = date(2030, 5, 20)
    mock_context.user_data[UD_TIME] = time(11, 0)
    mock_context.user_data[UD_PRIORITY] = TaskPriority.low

    update = _create_mock_update(user_id=8888, callback_data=CB_CONFIRM_SAVE)

    with patch("bot.handlers.tasks.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db_session
        state = await receive_confirmation(update, mock_context)

    assert state == ConversationHandler.END
    # User data must be cleared after save
    assert UD_TITLE not in mock_context.user_data
    update.callback_query.edit_message_text.assert_awaited_once()

    # Verify task in DB
    task = db_session.query(Task).filter_by(title="Test Task Save").first()
    assert task is not None
    assert task.priority == TaskPriority.low
    assert task.status == TaskStatus.pending


@pytest.mark.asyncio
async def test_receive_confirmation_cancel(db_session, mock_context):
    mock_context.user_data[UD_TIMEZONE] = "Asia/Kolkata"
    mock_context.user_data[UD_TITLE] = "Task to Cancel"
    mock_context.user_data[UD_DATE] = date(2030, 5, 20)
    mock_context.user_data[UD_TIME] = time(11, 0)
    mock_context.user_data[UD_PRIORITY] = TaskPriority.medium

    update = _create_mock_update(user_id=8888, callback_data=CB_CONFIRM_CANCEL)

    state = await receive_confirmation(update, mock_context)

    assert state == ConversationHandler.END
    assert UD_TITLE not in mock_context.user_data
    update.callback_query.edit_message_text.assert_awaited_once()

    # Verify no task in DB
    task = db_session.query(Task).filter_by(title="Task to Cancel").first()
    assert task is None


@pytest.mark.asyncio
async def test_cancel_add(mock_context):
    mock_context.user_data[UD_TITLE] = "Incomplete task"
    update = _create_mock_update(text="/cancel")

    state = await cancel_add(update, mock_context)

    assert state == ConversationHandler.END
    assert UD_TITLE not in mock_context.user_data
    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_button_guards(mock_context):
    update = _create_mock_update(text="some text instead of button")

    priority_state = await priority_text_guard(update, mock_context)
    assert priority_state == ASK_PRIORITY

    confirm_state = await confirm_text_guard(update, mock_context)
    assert confirm_state == CONFIRM


# ===========================================================================
# Phase 3: /today and /upcoming handler tests
# ===========================================================================

@pytest.mark.asyncio
async def test_today_command_empty(db_session, mock_context):
    update = _create_mock_update(user_id=7777, text="/today")

    with patch("bot.handlers.tasks.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db_session
        await today_command(update, mock_context)

    update.message.reply_text.assert_awaited_once()
    args, kwargs = update.message.reply_text.call_args
    assert "No tasks scheduled for today" in args[0]
    assert kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
async def test_today_command_with_tasks(db_session, mock_context):
    from bot.services.task_service import create_task
    from bot.services.user_service import get_or_create_user
    import pytz

    user = get_or_create_user(db_session, telegram_user_id=7778, username="today_user")
    tz = pytz.timezone(user.timezone)
    now_local = datetime.now(tz)
    now_utc = now_local.astimezone(timezone.utc)

    create_task(db_session, user=user, title="Dentist appointment", due_at_utc=now_utc)
    db_session.commit()

    update = _create_mock_update(user_id=7778, text="/today")

    with patch("bot.handlers.tasks.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db_session
        await today_command(update, mock_context)

    update.message.reply_text.assert_awaited_once()
    args, kwargs = update.message.reply_text.call_args
    assert "Dentist appointment" in args[0]
    assert "Today's Tasks" in args[0]


@pytest.mark.asyncio
async def test_upcoming_command_empty(db_session, mock_context):
    update = _create_mock_update(user_id=8881, text="/upcoming")

    with patch("bot.handlers.tasks.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db_session
        await upcoming_command(update, mock_context)

    update.message.reply_text.assert_awaited_once()
    args, kwargs = update.message.reply_text.call_args
    assert "No pending tasks scheduled" in args[0]


@pytest.mark.asyncio
async def test_upcoming_command_with_tasks(db_session, mock_context):
    from bot.services.task_service import create_task
    from bot.services.user_service import get_or_create_user
    import pytz

    user = get_or_create_user(db_session, telegram_user_id=8882, username="upcoming_user")
    tz = pytz.timezone(user.timezone)
    tomorrow_utc = (datetime.now(tz) + timedelta(days=1)).astimezone(timezone.utc)

    create_task(db_session, user=user, title="Submit assignment", due_at_utc=tomorrow_utc)
    db_session.commit()

    update = _create_mock_update(user_id=8882, text="/upcoming")

    with patch("bot.handlers.tasks.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db_session
        await upcoming_command(update, mock_context)

    update.message.reply_text.assert_awaited_once()
    args, kwargs = update.message.reply_text.call_args
    assert "Submit assignment" in args[0]
    assert "Upcoming Tasks" in args[0]


@pytest.mark.asyncio
async def test_today_callback_refresh(db_session, mock_context):
    update = _create_mock_update(user_id=9991, callback_data=CB_TODAY_REFRESH)

    with patch("bot.handlers.tasks.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db_session
        await today_callback(update, mock_context)

    update.callback_query.answer.assert_awaited_once()
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_upcoming_callback_refresh(db_session, mock_context):
    update = _create_mock_update(user_id=9992, callback_data=CB_UPCOMING_REFRESH)

    with patch("bot.handlers.tasks.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = db_session
        await upcoming_callback(update, mock_context)

    update.callback_query.answer.assert_awaited_once()
    update.callback_query.edit_message_text.assert_awaited_once()
