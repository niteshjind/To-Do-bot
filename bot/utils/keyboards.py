"""
utils/keyboards.py — InlineKeyboardMarkup factory functions.

All callback_data strings are defined as module-level constants so that
handlers can match them with equality checks rather than hard-coded strings.

Naming convention for callback_data:
  "<feature>:<action_or_value>"
  Examples: "priority:low", "confirm:save", "confirm:cancel"
"""

from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ---------------------------------------------------------------------------
# Callback data constants — import these in handlers for matching
# ---------------------------------------------------------------------------

# /add flow — priority selection
CB_PRIORITY_LOW = "priority:low"
CB_PRIORITY_MEDIUM = "priority:medium"
CB_PRIORITY_HIGH = "priority:high"

# /add flow — confirmation
CB_CONFIRM_SAVE = "confirm:save"
CB_CONFIRM_CANCEL = "confirm:cancel"

# Task list navigation & refresh callbacks
CB_TODAY_REFRESH = "view:today_refresh"
CB_UPCOMING_REFRESH = "view:upcoming_refresh"
CB_VIEW_TODAY = "view:today"
CB_VIEW_UPCOMING = "view:upcoming"

# Phase 4: Task actions callbacks (/done, /edit, /delete)
CB_DONE_CANCEL = "done:cancel"
CB_DELETE_CANCEL = "delete:cancel"
CB_EDIT_CANCEL = "edit:cancel"
CB_EDIT_SAVE = "edit:save"
CB_EDIT_FIELD_TITLE = "edit:field:title"
CB_EDIT_FIELD_DATE = "edit:field:date"
CB_EDIT_FIELD_TIME = "edit:field:time"
CB_EDIT_FIELD_PRIORITY = "edit:field:priority"
CB_EDIT_FIELD_RECURRENCE = "edit:field:recurrence"

# Phase 6: Recurrence selection callbacks
CB_REC_NONE = "rec:none"
CB_REC_DAILY = "rec:daily"
CB_REC_WEEKLY = "rec:weekly"
CB_REC_MONTHLY = "rec:monthly"

# Phase 6: Snooze options
CB_SNOOZE_10M = "10m"
CB_SNOOZE_30M = "30m"
CB_SNOOZE_1H = "1h"
CB_SNOOZE_TOMORROW = "tomorrow"

# Phase 7: Settings & Summary callbacks
CB_SETTINGS_TOGGLE_REMINDERS = "settings:toggle_reminders"
CB_SETTINGS_TOGGLE_SUMMARY = "settings:toggle_summary"
CB_SETTINGS_CHANGE_TZ = "settings:change_tz"
CB_SETTINGS_CHANGE_TIME = "settings:change_time"
CB_SETTINGS_REFRESH = "settings:refresh"
CB_SETTINGS_BACK = "settings:back"
CB_TZ_SET_PREFIX = "tz:set:"
CB_TZ_CUSTOM = "tz:custom"
CB_TIME_SET_PREFIX = "time:set:"
CB_TIME_CUSTOM = "time:custom"
CB_SUMMARY_REFRESH = "summary:refresh"

# Phase 7: Predefined quick-pick options
COMMON_TIMEZONES = [
    ("🇮🇳 Asia/Kolkata", "Asia/Kolkata"),
    ("🌐 UTC", "UTC"),
    ("🇦🇪 Asia/Dubai", "Asia/Dubai"),
    ("🇬🇧 Europe/London", "Europe/London"),
    ("🇺🇸 America/New_York", "America/New_York"),
]

COMMON_SUMMARY_TIMES = [
    ("🌅 07:00", "07:00"),
    ("☕ 08:00", "08:00"),
    ("☀️ 09:00", "09:00"),
    ("🌙 20:00", "20:00"),
]


# Priority display helpers
PRIORITY_ICONS = {
    "low": "🟢",
    "medium": "🟡",
    "high": "🔴",
}

# Status display helpers
STATUS_ICONS = {
    "pending": "⏳",
    "completed": "✅",
    "cancelled": "❌",
}


# ---------------------------------------------------------------------------
# Keyboard builders
# ---------------------------------------------------------------------------

def priority_keyboard() -> InlineKeyboardMarkup:
    """
    Inline keyboard for task priority selection.

    Layout: [🟢 Low] [🟡 Medium] [🔴 High]  (single row)
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🟢 Low", callback_data=CB_PRIORITY_LOW),
                InlineKeyboardButton("🟡 Medium", callback_data=CB_PRIORITY_MEDIUM),
                InlineKeyboardButton("🔴 High", callback_data=CB_PRIORITY_HIGH),
            ]
        ]
    )


def confirm_task_keyboard() -> InlineKeyboardMarkup:
    """
    Inline keyboard for task save confirmation.

    Layout:
      [✅ Save Task]
      [❌ Cancel]
    (two rows — prevents accidental Cancel tap)
    """
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Save Task", callback_data=CB_CONFIRM_SAVE)],
            [InlineKeyboardButton("❌ Cancel", callback_data=CB_CONFIRM_CANCEL)],
        ]
    )


def today_keyboard() -> InlineKeyboardMarkup:
    """
    Inline keyboard for /today list view.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Refresh", callback_data=CB_TODAY_REFRESH),
                InlineKeyboardButton("📆 View Upcoming", callback_data=CB_VIEW_UPCOMING),
            ]
        ]
    )


def upcoming_keyboard() -> InlineKeyboardMarkup:
    """
    Inline keyboard for /upcoming list view.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Refresh", callback_data=CB_UPCOMING_REFRESH),
                InlineKeyboardButton("📅 View Today", callback_data=CB_VIEW_TODAY),
            ]
        ]
    )


# ---------------------------------------------------------------------------
# Phase 4: Task Action Keyboard Builders
# ---------------------------------------------------------------------------

def task_selection_keyboard(
    tasks,
    callback_prefix: str,
    cancel_callback: str,
    tz_string: str,
) -> InlineKeyboardMarkup:
    """
    Build an inline keyboard listing tasks for user selection.
    Each row has one task button: [#{id} {title[:20]} ({time})].
    Bottom row has [❌ Cancel].
    """
    from bot.utils.datetime_utils import format_time_only

    buttons = []
    for t in tasks:
        p_icon = PRIORITY_ICONS.get(t.priority.value, "⚪")
        time_str = format_time_only(t.due_at, tz_string) if t.due_at else ""
        short_title = t.title[:22] + "…" if len(t.title) > 22 else t.title
        label = f"#{t.id} {p_icon} {short_title}"
        if time_str:
            label += f" ({time_str})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"{callback_prefix}:{t.id}")])

    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=cancel_callback)])
    return InlineKeyboardMarkup(buttons)


def confirm_delete_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """
    Inline keyboard for confirming task deletion.
    """
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗑️ Yes, Delete", callback_data=f"delete:confirm:{task_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data=CB_DELETE_CANCEL)],
        ]
    )


def edit_fields_keyboard() -> InlineKeyboardMarkup:
    """
    Inline keyboard for selecting which field of a task to edit.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📝 Title", callback_data=CB_EDIT_FIELD_TITLE),
                InlineKeyboardButton("🏷️ Priority", callback_data=CB_EDIT_FIELD_PRIORITY),
            ],
            [
                InlineKeyboardButton("📅 Date", callback_data=CB_EDIT_FIELD_DATE),
                InlineKeyboardButton("⏰ Time", callback_data=CB_EDIT_FIELD_TIME),
            ],
            [
                InlineKeyboardButton("🔁 Recurrence", callback_data=CB_EDIT_FIELD_RECURRENCE),
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data=CB_EDIT_CANCEL),
            ],
        ]
    )


def recurrence_keyboard() -> InlineKeyboardMarkup:
    """
    Inline keyboard for choosing task recurrence frequency.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ No Recurrence", callback_data=CB_REC_NONE),
            ],
            [
                InlineKeyboardButton("🔁 Daily", callback_data=CB_REC_DAILY),
                InlineKeyboardButton("🔁 Weekly", callback_data=CB_REC_WEEKLY),
            ],
            [
                InlineKeyboardButton("🔁 Monthly", callback_data=CB_REC_MONTHLY),
            ],
        ]
    )


def confirm_edit_keyboard() -> InlineKeyboardMarkup:
    """
    Inline keyboard for confirming task edits.
    """
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Save Changes", callback_data=CB_EDIT_SAVE)],
            [InlineKeyboardButton("❌ Cancel", callback_data=CB_EDIT_CANCEL)],
        ]
    )


def action_nav_keyboard() -> InlineKeyboardMarkup:
    """
    Navigation buttons shown after an action succeeds.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📅 Today", callback_data=CB_VIEW_TODAY),
                InlineKeyboardButton("📆 Upcoming", callback_data=CB_VIEW_UPCOMING),
            ]
        ]
    )


def reminder_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """
    Inline keyboard attached to an automated reminder notification.
    Provides quick completion and snooze options.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Mark Done", callback_data=f"done:select:{task_id}"),
            ],
            [
                InlineKeyboardButton("😴 10 min", callback_data=f"snooze:{task_id}:{CB_SNOOZE_10M}"),
                InlineKeyboardButton("😴 30 min", callback_data=f"snooze:{task_id}:{CB_SNOOZE_30M}"),
            ],
            [
                InlineKeyboardButton("😴 1 hour", callback_data=f"snooze:{task_id}:{CB_SNOOZE_1H}"),
                InlineKeyboardButton("📅 Tomorrow", callback_data=f"snooze:{task_id}:{CB_SNOOZE_TOMORROW}"),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Phase 7: Settings & Daily Summary Keyboards
# ---------------------------------------------------------------------------

def settings_keyboard(
    reminders_enabled: bool,
    daily_summary_enabled: bool,
) -> InlineKeyboardMarkup:
    """
    Inline keyboard for the /settings dashboard.

    Layout:
      [🔔 Reminders: ON / 🔕 Reminders: OFF]
      [📊 Daily Summary: ON / ⏹️ Daily Summary: OFF]
      [🌐 Timezone] [⏰ Summary Time]
      [🔄 Refresh Settings]
    """
    rem_text = "🔔 Reminders: ON" if reminders_enabled else "🔕 Reminders: OFF"
    sum_text = "📊 Daily Summary: ON" if daily_summary_enabled else "⏹️ Daily Summary: OFF"

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(rem_text, callback_data=CB_SETTINGS_TOGGLE_REMINDERS)],
            [InlineKeyboardButton(sum_text, callback_data=CB_SETTINGS_TOGGLE_SUMMARY)],
            [
                InlineKeyboardButton("🌐 Timezone", callback_data=CB_SETTINGS_CHANGE_TZ),
                InlineKeyboardButton("⏰ Summary Time", callback_data=CB_SETTINGS_CHANGE_TIME),
            ],
            [InlineKeyboardButton("🔄 Refresh Settings", callback_data=CB_SETTINGS_REFRESH)],
        ]
    )


def timezone_keyboard(current_timezone: Optional[str] = None) -> InlineKeyboardMarkup:
    """
    Inline keyboard for selecting a timezone from common quick-picks or custom input.
    Marks the currently active timezone with a checkmark.
    """
    buttons = []
    for label, tz in COMMON_TIMEZONES:
        btn_label = f"✅ {label}" if current_timezone == tz else label
        buttons.append([InlineKeyboardButton(btn_label, callback_data=f"{CB_TZ_SET_PREFIX}{tz}")])

    buttons.append([InlineKeyboardButton("✏️ Custom Timezone", callback_data=CB_TZ_CUSTOM)])
    buttons.append([InlineKeyboardButton("🔙 Back to Settings", callback_data=CB_SETTINGS_BACK)])
    return InlineKeyboardMarkup(buttons)


def summary_time_keyboard(current_time: Optional[str] = None) -> InlineKeyboardMarkup:
    """
    Inline keyboard for selecting daily summary delivery time.
    Marks the currently active time with a checkmark.
    """
    row1 = []
    row2 = []
    for idx, (label, t_val) in enumerate(COMMON_SUMMARY_TIMES):
        btn_label = f"✅ {label}" if current_time == t_val else label
        btn = InlineKeyboardButton(btn_label, callback_data=f"{CB_TIME_SET_PREFIX}{t_val}")
        if idx < 2:
            row1.append(btn)
        else:
            row2.append(btn)

    buttons = [
        row1,
        row2,
        [InlineKeyboardButton("✏️ Custom Time", callback_data=CB_TIME_CUSTOM)],
        [InlineKeyboardButton("🔙 Back to Settings", callback_data=CB_SETTINGS_BACK)],
    ]
    return InlineKeyboardMarkup(buttons)


def summary_keyboard() -> InlineKeyboardMarkup:
    """
    Inline keyboard for /summary task summary view.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Refresh", callback_data=CB_SUMMARY_REFRESH),
                InlineKeyboardButton("📅 View Today", callback_data=CB_VIEW_TODAY),
            ]
        ]
    )



