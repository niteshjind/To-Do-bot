"""
utils/keyboards.py — InlineKeyboardMarkup factory functions.

All callback_data strings are defined as module-level constants so that
handlers can match them with equality checks rather than hard-coded strings.

Naming convention for callback_data:
  "<feature>:<action_or_value>"
  Examples: "priority:low", "confirm:save", "confirm:cancel"
"""

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
