"""
tests/test_settings_handlers.py — Unit tests for Phase 7 Step 4 Telegram settings and summary handlers.

Tests cover:
  • /settings initial dashboard rendering and auto user registration
  • Toggle callbacks for task reminders and daily summary (persistence & UI updates)
  • Menu navigation callbacks (timezone menu, summary time menu, refresh, back)
  • Quick-pick timezone and summary-time callbacks
  • Custom timezone conversation flow (start, valid, invalid retry, cancel)
  • Custom summary time conversation flow (start, valid, invalid retry, cancel)
  • /summary command for empty day and day with tasks
  • Summary callbacks (refresh, view today)
  • Callback query acknowledgements and stale callback handling
  • Two-user isolation for settings and summary data
"""

from datetime import date, datetime, time as time_cls, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from telegram.ext import ConversationHandler

from bot.database.models import Task, TaskPriority, TaskStatus, User
from bot.handlers.settings import (
    STATE_CUSTOM_TIME,
    STATE_CUSTOM_TIMEZONE,
    cancel_custom_time,
    cancel_custom_timezone,
    receive_custom_time,
    receive_custom_timezone,
    settings_command,
    settings_menu_callback,
    settings_toggle_reminders_callback,
    settings_toggle_summary_callback,
    start_custom_time,
    start_custom_timezone,
    summary_callback,
    summary_command,
    summary_time_quick_pick_callback,
    timezone_quick_pick_callback,
)
from bot.services.task_service import complete_task, create_task
from bot.services.user_service import get_or_create_user
from bot.utils.datetime_utils import combine_to_utc
from bot.utils.keyboards import (
    CB_SETTINGS_BACK,
    CB_SETTINGS_CHANGE_TIME,
    CB_SETTINGS_CHANGE_TZ,
    CB_SETTINGS_REFRESH,
    CB_SETTINGS_TOGGLE_REMINDERS,
    CB_SETTINGS_TOGGLE_SUMMARY,
    CB_SUMMARY_REFRESH,
    CB_TIME_CUSTOM,
    CB_TIME_SET_PREFIX,
    CB_TZ_CUSTOM,
    CB_TZ_SET_PREFIX,
    CB_VIEW_TODAY,
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


# ===========================================================================
# 1. /settings Command Tests
# ===========================================================================

@pytest.mark.asyncio
class TestSettingsCommand:
    async def test_settings_command_initial_dashboard(self, db_session, mock_context):
        """Send /settings -> displays dashboard with default settings and buttons."""
        update = _create_mock_update(user_id=12345, text="/settings")

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await settings_command(update, mock_context)

        update.message.reply_text.assert_awaited_once()
        args, kwargs = update.message.reply_text.await_args
        msg = args[0]
        assert "Settings & Preferences" in msg
        assert "Asia/Kolkata" in msg
        assert "🔔 <b>Task Reminders:</b> 🔔 Enabled" in msg
        assert "📊 <b>Daily Summary:</b> 📊 Enabled" in msg
        assert "09:00" in msg
        assert kwargs.get("reply_markup") is not None

    async def test_settings_command_creates_user_if_missing(self, db_session, mock_context):
        """Unknown telegram_user_id running /settings gets automatically registered."""
        update = _create_mock_update(user_id=987654, username="newbie", text="/settings")

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await settings_command(update, mock_context)

        user = db_session.query(User).filter_by(telegram_user_id=987654).first()
        assert user is not None
        assert user.username == "newbie"


# ===========================================================================
# 2. Settings Toggle Callbacks Tests
# ===========================================================================

@pytest.mark.asyncio
class TestSettingsToggles:
    async def test_toggle_reminders_callback(self, db_session, mock_context):
        """Clicking toggle reminders flips state and edits message."""
        update = _create_mock_update(user_id=12345, callback_data=CB_SETTINGS_TOGGLE_REMINDERS)

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            # First toggle -> False
            await settings_toggle_reminders_callback(update, mock_context)

        user = db_session.query(User).filter_by(telegram_user_id=12345).first()
        assert user.reminders_enabled is False
        update.callback_query.answer.assert_awaited_with("Reminders disabled.")
        update.callback_query.edit_message_text.assert_awaited_once()
        assert "🔕 Disabled" in update.callback_query.edit_message_text.await_args[0][0]

        # Second toggle -> True
        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await settings_toggle_reminders_callback(update, mock_context)

        assert user.reminders_enabled is True
        update.callback_query.answer.assert_awaited_with("Reminders enabled.")

    async def test_toggle_summary_callback(self, db_session, mock_context):
        """Clicking toggle daily summary flips state and edits message."""
        update = _create_mock_update(user_id=12345, callback_data=CB_SETTINGS_TOGGLE_SUMMARY)

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            # First toggle -> False
            await settings_toggle_summary_callback(update, mock_context)

        user = db_session.query(User).filter_by(telegram_user_id=12345).first()
        assert user.daily_summary_enabled is False
        update.callback_query.answer.assert_awaited_with("Daily summary disabled.")
        assert "⏹️ Disabled" in update.callback_query.edit_message_text.await_args[0][0]

        # Second toggle -> True
        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await settings_toggle_summary_callback(update, mock_context)

        assert user.daily_summary_enabled is True
        update.callback_query.answer.assert_awaited_with("Daily summary enabled.")


# ===========================================================================
# 3. Settings Menu Navigation Callbacks Tests
# ===========================================================================

@pytest.mark.asyncio
class TestSettingsMenuNavigation:
    async def test_menu_change_timezone(self, db_session, mock_context):
        """Clicking Change Timezone opens timezone selection keyboard."""
        update = _create_mock_update(user_id=12345, callback_data=CB_SETTINGS_CHANGE_TZ)

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await settings_menu_callback(update, mock_context)

        update.callback_query.answer.assert_awaited_once()
        update.callback_query.edit_message_text.assert_awaited_once()
        text = update.callback_query.edit_message_text.await_args[0][0]
        assert "Select Your Timezone" in text

    async def test_menu_change_summary_time(self, db_session, mock_context):
        """Clicking Change Summary Time opens summary time selection keyboard."""
        update = _create_mock_update(user_id=12345, callback_data=CB_SETTINGS_CHANGE_TIME)

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await settings_menu_callback(update, mock_context)

        update.callback_query.answer.assert_awaited_once()
        text = update.callback_query.edit_message_text.await_args[0][0]
        assert "Select Daily Summary Time" in text

    async def test_menu_refresh_and_back(self, db_session, mock_context):
        """Clicking Refresh or Back returns to the settings dashboard."""
        # 1. Refresh
        update_refresh = _create_mock_update(user_id=12345, callback_data=CB_SETTINGS_REFRESH)
        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await settings_menu_callback(update_refresh, mock_context)

        update_refresh.callback_query.answer.assert_awaited_with("Settings refreshed.")
        assert "Settings & Preferences" in update_refresh.callback_query.edit_message_text.await_args[0][0]

        # 2. Back
        update_back = _create_mock_update(user_id=12345, callback_data=CB_SETTINGS_BACK)
        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await settings_menu_callback(update_back, mock_context)

        update_back.callback_query.answer.assert_awaited_once()
        assert "Settings & Preferences" in update_back.callback_query.edit_message_text.await_args[0][0]


# ===========================================================================
# 4. Quick-Pick Callbacks Tests
# ===========================================================================

@pytest.mark.asyncio
class TestQuickPickCallbacks:
    async def test_timezone_quick_pick_valid(self, db_session, mock_context):
        """Clicking tz:set:Europe/London updates user's timezone to Europe/London."""
        update = _create_mock_update(user_id=12345, callback_data=f"{CB_TZ_SET_PREFIX}Europe/London")

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await timezone_quick_pick_callback(update, mock_context)

        user = db_session.query(User).filter_by(telegram_user_id=12345).first()
        assert user.timezone == "Europe/London"
        update.callback_query.answer.assert_awaited_with("Timezone updated to Europe/London.")

    async def test_timezone_quick_pick_invalid(self, db_session, mock_context):
        """Selecting an invalid timezone callback alerts user without saving."""
        update = _create_mock_update(user_id=12345, callback_data=f"{CB_TZ_SET_PREFIX}Moon/Crater")

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await timezone_quick_pick_callback(update, mock_context)

        update.callback_query.answer.assert_awaited_once()
        assert update.callback_query.answer.await_args[1].get("show_alert") is True

    async def test_summary_time_quick_pick_valid(self, db_session, mock_context):
        """Clicking time:set:20:00 updates summary time to 20:00."""
        update = _create_mock_update(user_id=12345, callback_data=f"{CB_TIME_SET_PREFIX}20:00")

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await summary_time_quick_pick_callback(update, mock_context)

        user = db_session.query(User).filter_by(telegram_user_id=12345).first()
        assert user.daily_summary_time == "20:00"
        update.callback_query.answer.assert_awaited_with("Summary time set to 20:00.")


# ===========================================================================
# 5. Custom Timezone Conversation Tests
# ===========================================================================

@pytest.mark.asyncio
class TestCustomTimezoneConversation:
    async def test_start_custom_timezone(self, mock_context):
        """Tapping custom timezone enters conversation state."""
        update = _create_mock_update(user_id=12345, callback_data=CB_TZ_CUSTOM)
        state = await start_custom_timezone(update, mock_context)

        assert state == STATE_CUSTOM_TIMEZONE
        update.callback_query.edit_message_text.assert_awaited_once()
        assert "Enter Custom Timezone" in update.callback_query.edit_message_text.await_args[0][0]

    async def test_receive_custom_timezone_valid(self, db_session, mock_context):
        """Sending a valid IANA timezone updates DB and ends conversation."""
        update = _create_mock_update(user_id=12345, text="America/Chicago")

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            state = await receive_custom_timezone(update, mock_context)

        assert state == ConversationHandler.END
        user = db_session.query(User).filter_by(telegram_user_id=12345).first()
        assert user.timezone == "America/Chicago"
        update.message.reply_text.assert_awaited_once()
        assert "Timezone updated to:" in update.message.reply_text.await_args[0][0]

    async def test_receive_custom_timezone_invalid_retries(self, db_session, mock_context):
        """Sending an invalid timezone displays error and keeps user in conversation."""
        update = _create_mock_update(user_id=12345, text="Atlantis/Deep")

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            state = await receive_custom_timezone(update, mock_context)

        assert state == STATE_CUSTOM_TIMEZONE
        user = db_session.query(User).filter_by(telegram_user_id=12345).first()
        assert user.timezone == "Asia/Kolkata"  # unchanged
        assert "Invalid timezone:" in update.message.reply_text.await_args[0][0]

    async def test_cancel_custom_timezone(self, db_session, mock_context):
        """Sending /cancel exits custom timezone entry."""
        update = _create_mock_update(user_id=12345, text="/cancel")

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            state = await cancel_custom_timezone(update, mock_context)

        assert state == ConversationHandler.END
        assert "Timezone change cancelled." in update.message.reply_text.await_args[0][0]


# ===========================================================================
# 6. Custom Summary Time Conversation Tests
# ===========================================================================

@pytest.mark.asyncio
class TestCustomSummaryTimeConversation:
    async def test_start_custom_time(self, mock_context):
        """Tapping custom time enters conversation state."""
        update = _create_mock_update(user_id=12345, callback_data=CB_TIME_CUSTOM)
        state = await start_custom_time(update, mock_context)

        assert state == STATE_CUSTOM_TIME
        update.callback_query.edit_message_text.assert_awaited_once()
        assert "Enter Custom Summary Time" in update.callback_query.edit_message_text.await_args[0][0]

    async def test_receive_custom_time_valid(self, db_session, mock_context):
        """Sending a valid 24-hour HH:MM time updates DB and ends conversation."""
        update = _create_mock_update(user_id=12345, text="18:45")

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            state = await receive_custom_time(update, mock_context)

        assert state == ConversationHandler.END
        user = db_session.query(User).filter_by(telegram_user_id=12345).first()
        assert user.daily_summary_time == "18:45"
        assert "Daily summary time updated to:" in update.message.reply_text.await_args[0][0]

    async def test_receive_custom_time_invalid_retries(self, db_session, mock_context):
        """Sending an invalid time displays error and stays in state."""
        update = _create_mock_update(user_id=12345, text="25:99")

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            state = await receive_custom_time(update, mock_context)

        assert state == STATE_CUSTOM_TIME
        user = db_session.query(User).filter_by(telegram_user_id=12345).first()
        assert user.daily_summary_time == "09:00"  # default unchanged
        assert "Invalid time format" in update.message.reply_text.await_args[0][0]

    async def test_cancel_custom_time(self, db_session, mock_context):
        """Sending /cancel exits custom summary time entry."""
        update = _create_mock_update(user_id=12345, text="/cancel")

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            state = await cancel_custom_time(update, mock_context)

        assert state == ConversationHandler.END
        assert "Summary time change cancelled." in update.message.reply_text.await_args[0][0]


# ===========================================================================
# 7. /summary Command & Callback Tests
# ===========================================================================

@pytest.mark.asyncio
class TestSummaryCommandAndCallbacks:
    async def test_summary_command_empty(self, db_session, mock_context):
        """User with no tasks sees clean empty summary message."""
        update = _create_mock_update(user_id=12345, text="/summary")

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await summary_command(update, mock_context)

        update.message.reply_text.assert_awaited_once()
        msg = update.message.reply_text.await_args[0][0]
        assert "Daily Task Summary" in msg
        assert "No tasks scheduled for today and no overdue items!" in msg

    async def test_summary_command_with_tasks(self, db_session, mock_context):
        """User with tasks sees today's agenda and overdue items."""
        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            user = get_or_create_user(db=db_session, telegram_user_id=12345)

            # Create an overdue task
            past_due = datetime.now(timezone.utc) - timedelta(days=2)
            create_task(db=db_session, user=user, title="Overdue Task", due_at_utc=past_due)

            # Create a task due today
            now_utc = datetime.now(timezone.utc)
            create_task(db=db_session, user=user, title="Today Task", due_at_utc=now_utc)
            db_session.commit()

        update = _create_mock_update(user_id=12345, text="/summary")
        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await summary_command(update, mock_context)

        msg = update.message.reply_text.await_args[0][0]
        assert "Today Task" in msg
        assert "Overdue Task" in msg
        assert "Overdue Tasks:</b> 1" in msg

    async def test_summary_refresh_callback(self, db_session, mock_context):
        """Clicking summary:refresh edits the message with fresh data."""
        update = _create_mock_update(user_id=12345, callback_data=CB_SUMMARY_REFRESH)

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await summary_callback(update, mock_context)

        update.callback_query.answer.assert_awaited_with("Summary refreshed.")
        update.callback_query.edit_message_text.assert_awaited_once()

    async def test_summary_view_today_callback(self, db_session, mock_context):
        """Clicking view:today edits the message to the /today view."""
        update = _create_mock_update(user_id=12345, callback_data=CB_VIEW_TODAY)

        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await summary_callback(update, mock_context)

        update.callback_query.answer.assert_awaited_once()
        update.callback_query.edit_message_text.assert_awaited_once()


# ===========================================================================
# 8. Two-User Isolation Tests
# ===========================================================================

@pytest.mark.asyncio
class TestTwoUserIsolation:
    async def test_two_user_settings_isolation(self, db_session, mock_context):
        """User A updating settings never touches User B's settings."""
        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            user_a = get_or_create_user(db=db_session, telegram_user_id=111)
            user_b = get_or_create_user(db=db_session, telegram_user_id=222)
            db_session.commit()

        # User A toggles reminders off
        update_a = _create_mock_update(user_id=111, callback_data=CB_SETTINGS_TOGGLE_REMINDERS)
        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await settings_toggle_reminders_callback(update_a, mock_context)

        # Verify User A has reminders False, User B still True
        assert user_a.reminders_enabled is False
        assert user_b.reminders_enabled is True

    async def test_two_user_summary_isolation(self, db_session, mock_context):
        """User A's summary never leaks tasks belonging to User B."""
        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            user_a = get_or_create_user(db=db_session, telegram_user_id=111)
            user_b = get_or_create_user(db=db_session, telegram_user_id=222)

            now_utc = datetime.now(timezone.utc)
            create_task(db=db_session, user=user_b, title="Secret Task of B", due_at_utc=now_utc)
            db_session.commit()

        # User A calls /summary
        update_a = _create_mock_update(user_id=111, text="/summary")
        with patch("bot.handlers.settings.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            await summary_command(update_a, mock_context)

        msg_a = update_a.message.reply_text.await_args[0][0]
        assert "Secret Task of B" not in msg_a
        assert "No tasks scheduled for today" in msg_a
