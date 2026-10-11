"""
tests/test_ui.py — Tests for Phase 7 Step 3 UI components, inline keyboards, and message formatters.

Tests cover:
  • Settings dashboard message reflects enabled/disabled states and last summary date
  • Settings inline keyboard labels toggle according to state
  • Timezone selection keyboard contains all required options and active checkmark
  • Summary time keyboard contains all required quick-pick options and active checkmark
  • Callback data values are strictly unique and <= 64 bytes (Telegram limit)
  • Task titles containing HTML-sensitive characters (<, >, &, ", ') are safely escaped
  • Empty summary formatting renders helpful empty state
  • Full summary formatting renders overdue backlog, today agenda, counts, and icons
  • Unbounded length protection: large task lists / long titles never exceed Telegram limits
"""

from datetime import date, datetime, timezone
import pytest

from bot.database.models import TaskPriority, TaskStatus
from bot.services.task_service import DailySummaryDTO, TaskDTO
from bot.services.user_service import UserSettingsDTO
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
    settings_keyboard,
    summary_keyboard,
    summary_time_keyboard,
    timezone_keyboard,
)
from bot.utils.messages import (
    SUMMARY_TIME_SELECTION_PROMPT,
    TIMEZONE_SELECTION_PROMPT,
    format_daily_summary_message,
    format_settings_message,
)


# ===========================================================================
# Settings Dashboard UI Tests
# ===========================================================================

class TestSettingsDashboardUI:
    def test_settings_message_reflects_enabled_states(self) -> None:
        """Settings dashboard displays enabled icons and values."""
        dto = UserSettingsDTO(
            user_id=1,
            telegram_user_id=123456,
            timezone="Asia/Kolkata",
            reminders_enabled=True,
            daily_summary_enabled=True,
            daily_summary_time="09:00",
            last_summary_date=None,
        )
        msg = format_settings_message(dto)

        assert "Settings & Preferences" in msg
        assert "<code>Asia/Kolkata</code>" in msg
        assert "🔔 <b>Task Reminders:</b> 🔔 Enabled" in msg
        assert "📊 <b>Daily Summary:</b> 📊 Enabled" in msg
        assert "<code>09:00</code> (local)" in msg
        assert "Last Summary Sent" not in msg

    def test_settings_message_reflects_disabled_states(self) -> None:
        """Settings dashboard displays disabled icons and values."""
        dto = UserSettingsDTO(
            user_id=2,
            telegram_user_id=654321,
            timezone="America/New_York",
            reminders_enabled=False,
            daily_summary_enabled=False,
            daily_summary_time="20:00",
            last_summary_date="2026-10-10",
        )
        msg = format_settings_message(dto)

        assert "<code>America/New_York</code>" in msg
        assert "🔔 <b>Task Reminders:</b> 🔕 Disabled" in msg
        assert "📊 <b>Daily Summary:</b> ⏹️ Disabled" in msg
        assert "<code>20:00</code> (local)" in msg
        assert "🗓️ <b>Last Summary Sent:</b> <code>2026-10-10</code>" in msg

    def test_settings_keyboard_labels_and_callbacks(self) -> None:
        """Buttons toggle labels based on enabled flags, and callbacks are within limits."""
        # 1. Enabled keyboard
        kb_on = settings_keyboard(reminders_enabled=True, daily_summary_enabled=True)
        buttons_on = [btn for row in kb_on.inline_keyboard for btn in row]
        texts_on = [btn.text for btn in buttons_on]
        cbs_on = [btn.callback_data for btn in buttons_on]

        assert "🔔 Reminders: ON" in texts_on
        assert "📊 Daily Summary: ON" in texts_on
        assert "🌐 Timezone" in texts_on
        assert "⏰ Summary Time" in texts_on
        assert "🔄 Refresh Settings" in texts_on

        # Check callback data lengths and uniqueness
        assert len(cbs_on) == len(set(cbs_on))
        for cb in cbs_on:
            assert len(cb.encode("utf-8")) <= 64

        # 2. Disabled keyboard
        kb_off = settings_keyboard(reminders_enabled=False, daily_summary_enabled=False)
        buttons_off = [btn for row in kb_off.inline_keyboard for btn in row]
        texts_off = [btn.text for btn in buttons_off]

        assert "🔕 Reminders: OFF" in texts_off
        assert "⏹️ Daily Summary: OFF" in texts_off


# ===========================================================================
# Timezone Selection UI Tests
# ===========================================================================

class TestTimezoneSelectionUI:
    def test_timezone_keyboard_contains_expected_options(self) -> None:
        """Timezone keyboard contains all standard quick-picks, custom, and back buttons."""
        kb = timezone_keyboard(current_timezone="UTC")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        texts = [btn.text for btn in buttons]
        cbs = [btn.callback_data for btn in buttons]

        # Verify common timezones exist
        assert any("Asia/Kolkata" in t for t in texts)
        assert any("UTC" in t for t in texts)
        assert any("Asia/Dubai" in t for t in texts)
        assert any("Europe/London" in t for t in texts)
        assert any("America/New_York" in t for t in texts)

        # Active checkmark on UTC
        utc_button = next(btn for btn in buttons if "UTC" in btn.text)
        assert utc_button.text.startswith("✅")

        # Custom & Back buttons
        assert any("Custom Timezone" in t for t in texts)
        assert any("Back to Settings" in t for t in texts)

        # Unique & within 64 bytes
        assert len(cbs) == len(set(cbs))
        for cb in cbs:
            assert len(cb.encode("utf-8")) <= 64

    def test_timezone_prompt_formatting(self) -> None:
        """Prompt message safely formats with user's current timezone."""
        formatted = TIMEZONE_SELECTION_PROMPT.format(current_timezone="Asia/Kolkata")
        assert "Current timezone: <b>Asia/Kolkata</b>" in formatted


# ===========================================================================
# Summary Time Selection UI Tests
# ===========================================================================

class TestSummaryTimeSelectionUI:
    def test_summary_time_keyboard_contains_expected_options(self) -> None:
        """Summary time keyboard contains 07:00, 08:00, 09:00, 20:00, custom, and back."""
        kb = summary_time_keyboard(current_time="09:00")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        texts = [btn.text for btn in buttons]
        cbs = [btn.callback_data for btn in buttons]

        assert any("07:00" in t for t in texts)
        assert any("08:00" in t for t in texts)
        assert any("09:00" in t for t in texts)
        assert any("20:00" in t for t in texts)

        # Active checkmark on 09:00
        btn_09 = next(btn for btn in buttons if "09:00" in btn.text)
        assert btn_09.text.startswith("✅")

        # Custom & Back
        assert any("Custom Time" in t for t in texts)
        assert any("Back to Settings" in t for t in texts)

        # Unique & within 64 bytes
        assert len(cbs) == len(set(cbs))
        for cb in cbs:
            assert len(cb.encode("utf-8")) <= 64

    def test_summary_time_prompt_formatting(self) -> None:
        """Prompt message safely formats with user's current summary time."""
        formatted = SUMMARY_TIME_SELECTION_PROMPT.format(current_time="09:00")
        assert "Current delivery time: <b>09:00</b>" in formatted


# ===========================================================================
# Daily Summary Message Formatter Tests
# ===========================================================================

class TestDailySummaryFormatter:
    def test_empty_summary_message(self) -> None:
        """Empty summary renders friendly empty state without crashing."""
        summary = DailySummaryDTO(
            user_id=1,
            telegram_user_id=111,
            date=date(2026, 10, 11),
            timezone="Asia/Kolkata",
            today_tasks=[],
            today_pending_count=0,
            today_completed_count=0,
            today_total_count=0,
            overdue_tasks=[],
            overdue_count=0,
        )
        msg = format_daily_summary_message(summary)

        assert "Daily Task Summary (11 Oct 2026)" in msg
        assert "No tasks scheduled for today and no overdue items!" in msg
        assert "Overdue Backlog" not in msg

    def test_summary_with_pending_and_completed_tasks(self) -> None:
        """Summary renders completed tasks with strikethrough and pending normally."""
        now_utc = datetime(2026, 10, 11, 4, 30, tzinfo=timezone.utc)  # 10:00 IST
        t1 = TaskDTO(
            id=10,
            user_id=1,
            title="Morning Meeting",
            status=TaskStatus.pending,
            priority=TaskPriority.high,
            due_at=now_utc,
            recurrence=None,
            reminder_sent=False,
            snoozed_until=None,
            completed_at=None,
            created_at=now_utc,
            updated_at=now_utc,
        )
        t2 = TaskDTO(
            id=11,
            user_id=1,
            title="Read Emails",
            status=TaskStatus.completed,
            priority=TaskPriority.low,
            due_at=now_utc,
            recurrence=None,
            reminder_sent=True,
            snoozed_until=None,
            completed_at=now_utc,
            created_at=now_utc,
            updated_at=now_utc,
        )

        summary = DailySummaryDTO(
            user_id=1,
            telegram_user_id=111,
            date=date(2026, 10, 11),
            timezone="Asia/Kolkata",
            today_tasks=[t1, t2],
            today_pending_count=1,
            today_completed_count=1,
            today_total_count=2,
            overdue_tasks=[],
            overdue_count=0,
        )
        msg = format_daily_summary_message(summary)

        assert "Today's Tasks:</b> 2 (1 completed, 1 pending)" in msg
        assert "Morning Meeting" in msg
        assert "<s>Read Emails</s>" in msg
        assert "🔴" in msg  # High priority
        assert "🟢" in msg  # Low priority

    def test_summary_with_overdue_tasks(self) -> None:
        """Summary renders overdue backlog section with overdue warning."""
        past_utc = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
        t_overdue = TaskDTO(
            id=5,
            user_id=1,
            title="Overdue Tax Filing",
            status=TaskStatus.pending,
            priority=TaskPriority.high,
            due_at=past_utc,
            recurrence=None,
            reminder_sent=True,
            snoozed_until=None,
            completed_at=None,
            created_at=past_utc,
            updated_at=past_utc,
        )

        summary = DailySummaryDTO(
            user_id=1,
            telegram_user_id=111,
            date=date(2026, 10, 11),
            timezone="Asia/Kolkata",
            today_tasks=[],
            today_pending_count=0,
            today_completed_count=0,
            today_total_count=0,
            overdue_tasks=[t_overdue],
            overdue_count=1,
        )
        msg = format_daily_summary_message(summary)

        assert "Overdue Tasks:</b> 1" in msg
        assert "⚠️ Overdue Backlog:" in msg
        assert "Overdue Tax Filing" in msg
        assert "due 09 Oct 2026" in msg

    def test_html_escaping_in_task_titles(self) -> None:
        """HTML special characters (<, >, &, \", ') in task titles are safely escaped."""
        now_utc = datetime(2026, 10, 11, 4, 30, tzinfo=timezone.utc)
        dangerous_title = "<b>Bold</b> & <script>alert('xss')</script> \"quoted\""
        task = TaskDTO(
            id=99,
            user_id=1,
            title=dangerous_title,
            status=TaskStatus.pending,
            priority=TaskPriority.medium,
            due_at=now_utc,
            recurrence=None,
            reminder_sent=False,
            snoozed_until=None,
            completed_at=None,
            created_at=now_utc,
            updated_at=now_utc,
        )

        summary = DailySummaryDTO(
            user_id=1,
            telegram_user_id=111,
            date=date(2026, 10, 11),
            timezone="Asia/Kolkata",
            today_tasks=[task],
            today_pending_count=1,
            today_completed_count=0,
            today_total_count=1,
            overdue_tasks=[],
            overdue_count=0,
        )
        msg = format_daily_summary_message(summary)

        # Check raw tags do not appear
        assert "<script>" not in msg
        assert "</script>" not in msg
        # Escaped versions are present
        assert "&lt;b&gt;Bold&lt;/b&gt;" in msg
        assert "&amp;" in msg
        assert "&lt;script&gt;" in msg

    def test_unbounded_message_truncation(self) -> None:
        """Large number of tasks does not exceed max_length (4000 characters)."""
        now_utc = datetime(2026, 10, 11, 5, 0, tzinfo=timezone.utc)
        # Create 100 tasks with lengthy titles
        tasks = [
            TaskDTO(
                id=i,
                user_id=1,
                title=f"Very Important Enterprise Objective Number {i} with extensive extra details",
                status=TaskStatus.pending,
                priority=TaskPriority.medium,
                due_at=now_utc,
                recurrence=None,
                reminder_sent=False,
                snoozed_until=None,
                completed_at=None,
                created_at=now_utc,
                updated_at=now_utc,
            )
            for i in range(1, 101)
        ]

        summary = DailySummaryDTO(
            user_id=1,
            telegram_user_id=111,
            date=date(2026, 10, 11),
            timezone="Asia/Kolkata",
            today_tasks=tasks,
            today_pending_count=100,
            today_completed_count=0,
            today_total_count=100,
            overdue_tasks=[],
            overdue_count=0,
        )

        msg = format_daily_summary_message(summary, max_length=4000)

        # Must be strictly under Telegram budget
        assert len(msg) <= 4000
        # Footnote must be present indicating omitted tasks
        assert "more tasks (use /today or /upcoming to view all)" in msg

    def test_summary_keyboard(self) -> None:
        """Summary keyboard buttons have valid and short callback data."""
        kb = summary_keyboard()
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        cbs = [btn.callback_data for btn in buttons]

        assert len(cbs) == len(set(cbs))
        for cb in cbs:
            assert len(cb.encode("utf-8")) <= 64
        assert CB_SUMMARY_REFRESH in cbs
