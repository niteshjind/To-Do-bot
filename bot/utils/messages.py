"""
utils/messages.py — All user-facing message strings in one place.

Keeping message text here (rather than inline in handlers) makes it easy to:
  • Edit wording without touching handler logic.
  • Add i18n / translations later without changing handler code.

Messages use Python str.format() placeholders like {first_name}.
HTML parse_mode is used so <b> and <code> tags render in Telegram.
"""

import html
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bot.services.task_service import DailySummaryDTO
    from bot.services.user_service import UserSettingsDTO

# ===========================================================================
# Phase 1 — /start, /help, /cancel
# ===========================================================================

WELCOME_MESSAGE = """\
👋 Hello, <b>{first_name}</b>! Welcome to your <b>To-Do & Reminder Bot</b>.

I'm here to help you capture tasks, set reminders, and stay on top of your day — all without leaving Telegram.

<b>What I can do:</b>
• ✅ Create and manage your to-do tasks
• ⏰ Send reminders at the exact time you choose
• 📋 Show today's tasks and upcoming deadlines
• ✏️ Edit or delete tasks whenever you need
• 📅 Send you a daily morning summary

Use /help to see all available commands, or /add to create your first task right now!\
"""

HELP_MESSAGE = """\
<b>📖 Available Commands</b>

<b>Task Management</b>
/add — Create a new task with a reminder
/today — View today's tasks
/upcoming — View tasks for the next 7 days
/done — Mark a task as completed
/edit — Edit an existing task
/delete — Delete a task

<b>Settings</b>
/settings — Manage your timezone and preferences

<b>Navigation</b>
/start — Show the welcome message
/help — Show this help message
/cancel — Cancel the current action

<b>💡 Tip:</b> When creating a task with /add, I'll guide you step by step — no need to remember any special syntax!

<b>⏰ Reminder format:</b> <code>DD/MM/YYYY HH:MM</code> (24-hour, e.g. 07/10/2026 09:30)

Your current default timezone: <b>Asia/Kolkata</b> (change with /settings)\
"""

CANCEL_MESSAGE = "❌ Action cancelled. Type /help to see what I can do."

ERROR_UNEXPECTED = (
    "⚠️ Something went wrong on my end. Please try again in a moment.\n"
    "If the problem persists, use /cancel to reset."
)

UNKNOWN_COMMAND_MESSAGE = (
    "🤔 I don't recognise that command.\n"
    "Type /help to see everything I can do."
)


# ===========================================================================
# Phase 2 — /add ConversationHandler
# ===========================================================================

# --- Step prompts ---

ADD_TASK_START = (
    "📝 <b>New Task</b>\n\n"
    "What should I call this task?\n\n"
    "<i>Type /cancel at any step to abort.</i>"
)

ADD_TASK_ASK_DATE = (
    "✅ <b>Title saved.</b>\n\n"
    "📅 <b>What date should I remind you?</b>\n\n"
    "Format: <code>DD/MM/YYYY</code>\n"
    "Example: <code>{example_date}</code>"
)

ADD_TASK_ASK_TIME = (
    "✅ <b>Date saved.</b>\n\n"
    "⏰ <b>What time should I remind you?</b>\n\n"
    "Format: <code>HH:MM</code> (24-hour clock)\n"
    "Examples: <code>09:30</code> · <code>14:00</code> · <code>21:45</code>"
)

ADD_TASK_ASK_PRIORITY = "🏷️ <b>Choose the priority for this task:</b>"
ADD_TASK_ASK_RECURRENCE = (
    "🔁 <b>Does this task repeat?</b>\n\n"
    "Choose a recurrence schedule, or tap 'No Recurrence':"
)

# --- Confirmation ---

ADD_TASK_CONFIRM = (
    "📋 <b>Review your task</b>\n\n"
    "📝 <b>Title:</b> {title}\n"
    "⏰ <b>Reminder:</b> {due_display}\n"
    "🏷️ <b>Priority:</b> {priority_icon} {priority_label}\n"
    "🔁 <b>Repeat:</b> {recurrence_label}\n\n"
    "Shall I save this task?"
)

# --- Success ---

ADD_TASK_SUCCESS = (
    "✅ <b>Task saved!</b>\n\n"
    "📝 {title}\n"
    "⏰ <b>Reminder:</b> {due_display}\n"
    "🏷️ <b>Priority:</b> {priority_icon} {priority_label}\n"
    "🔁 <b>Repeat:</b> {recurrence_label}\n"
    "📌 <b>Task ID:</b> #{task_id}\n\n"
    "I'll send you a reminder at the scheduled time!"
)

# --- Cancellation ---

ADD_TASK_CANCELLED = "❌ Task creation cancelled. Type /add to start a new task."

# --- Validation errors ---

ERR_TITLE_EMPTY = (
    "❌ Task title cannot be empty.\n\n"
    "Please enter a title for your task:"
)

ERR_TITLE_TOO_LONG = (
    "❌ Title is too long — {length}/{max_length} characters.\n\n"
    "Please shorten your title:"
)

ERR_INVALID_DATE = (
    "❌ <b>Invalid date format.</b>\n\n"
    "Please use <code>DD/MM/YYYY</code>\n"
    "Example: <code>{example_date}</code>"
)

ERR_INVALID_TIME = (
    "❌ <b>Invalid time format.</b>\n\n"
    "Please use <code>HH:MM</code> (24-hour clock)\n"
    "Examples: <code>09:30</code> · <code>14:00</code> · <code>21:45</code>"
)

ERR_DATETIME_IN_PAST = (
    "❌ <b>That reminder time is in the past.</b>\n\n"
    "Current time: <code>{current_time}</code>\n\n"
    "Please enter a future time:"
)

ERR_USE_BUTTONS = "👆 Please use the buttons above to make your selection."


# ===========================================================================
# Phase 3 — Task Listing (/today & /upcoming)
# ===========================================================================

TODAY_HEADER = "📅 <b>Today's Tasks ({date_str})</b>\n"
TODAY_PROGRESS = "📊 <b>Progress:</b> {completed}/{total} completed ({pct}%)\n\n"
TODAY_EMPTY = (
    "📅 <b>Today's Tasks</b>\n\n"
    "No tasks scheduled for today! 🎉\n\n"
    "Use /add to create a task."
)

UPCOMING_HEADER = "📆 <b>Upcoming Tasks (Next {window_days} Days)</b>\n\n"
UPCOMING_EMPTY = (
    "📆 <b>Upcoming Tasks</b>\n\n"
    "No pending tasks scheduled for the next {window_days} days! 🎉\n\n"
    "Use /add to create a task."
)


# ===========================================================================
# Phase 4 — Task Actions (/done, /delete, /edit)
# ===========================================================================

# --- /done ---
DONE_NO_PENDING = "🎉 <b>All caught up!</b>\n\nYou have no pending tasks to complete."
DONE_SELECT_TASK = "✅ <b>Mark Task as Completed</b>\n\nSelect a task below:"
DONE_SUCCESS = "✅ <b>Task Completed!</b>\n\n<s>{title}</s>\n\nWell done! 🎉"
DONE_SUCCESS_RECURRING = (
    "✅ <b>Task Completed!</b>\n\n"
    "<s>{title}</s>\n\n"
    "🔁 <b>Next occurrence scheduled:</b> {next_due_display}\n\n"
    "Well done! 🎉"
)
DONE_ALREADY_COMPLETED = "ℹ️ Task #{task_id} is already completed."
DONE_ALREADY_CANCELLED = "⚠️ Task #{task_id} is cancelled and cannot be completed."
DONE_NOT_FOUND = "❌ Task #{task_id} was not found or is not owned by you."
DONE_CANCELLED = "❌ Action cancelled."

# --- /delete ---
DELETE_NO_TASKS = "ℹ️ You have no active tasks to delete."
DELETE_SELECT_TASK = "🗑️ <b>Delete Task</b>\n\nSelect a task below to delete:"
DELETE_CONFIRM = (
    "⚠️ <b>Are you sure you want to delete this task?</b>\n\n"
    "📌 <b>#{task_id}</b> {title}\n"
    "⏰ <b>Reminder:</b> {due_display}\n\n"
    "<i>This cannot be undone.</i>"
)
DELETE_SUCCESS = "🗑️ <b>Task Deleted</b>\n\nTask #{task_id} \"<b>{title}</b>\" has been deleted."
DELETE_NOT_FOUND = "❌ Task #{task_id} was not found or is not owned by you."
DELETE_CANCELLED = "❌ Deletion cancelled."

# --- /edit ---
EDIT_NO_TASKS = "ℹ️ You have no pending tasks to edit."
EDIT_SELECT_TASK = "✏️ <b>Edit Task</b>\n\nSelect a task below to edit:"
EDIT_MENU = (
    "✏️ <b>Editing Task #{task_id}</b>\n\n"
    "📝 <b>Title:</b> {title}\n"
    "⏰ <b>Reminder:</b> {due_display}\n"
    "🏷️ <b>Priority:</b> {priority_icon} {priority_label}\n"
    "🔁 <b>Repeat:</b> {recurrence_label}\n\n"
    "What would you like to edit?"
)
EDIT_ASK_TITLE = "📝 <b>Edit Title</b>\n\nCurrent: <i>{current_title}</i>\n\nPlease enter the new title:"
EDIT_ASK_DATE = (
    "📅 <b>Edit Date</b>\n\n"
    "Current date: <code>{current_date}</code>\n\n"
    "Please enter the new date (<code>DD/MM/YYYY</code>):"
)
EDIT_ASK_TIME = (
    "⏰ <b>Edit Time</b>\n\n"
    "Current time: <code>{current_time}</code>\n\n"
    "Please enter the new time (<code>HH:MM</code> 24-hour):"
)
EDIT_ASK_PRIORITY = "🏷️ <b>Edit Priority</b>\n\nCurrent: {priority_icon} {priority_label}\n\nSelect the new priority:"
EDIT_ASK_RECURRENCE = (
    "🔁 <b>Edit Recurrence</b>\n\n"
    "Current: <b>{current_recurrence}</b>\n\n"
    "Select the new recurrence schedule:"
)
EDIT_CONFIRM = (
    "📋 <b>Review Changes for Task #{task_id}</b>\n\n"
    "📝 <b>Title:</b> {title}\n"
    "⏰ <b>Reminder:</b> {due_display}\n"
    "🏷️ <b>Priority:</b> {priority_icon} {priority_label}\n"
    "🔁 <b>Repeat:</b> {recurrence_label}\n\n"
    "Save these changes?"
)
EDIT_SUCCESS = (
    "✅ <b>Task Updated!</b>\n\n"
    "📝 {title}\n"
    "⏰ <b>Reminder:</b> {due_display}\n"
    "🏷️ <b>Priority:</b> {priority_icon} {priority_label}\n"
    "🔁 <b>Repeat:</b> {recurrence_label}\n"
    "📌 <b>Task ID:</b> #{task_id}"
)
EDIT_NOT_FOUND = "❌ Task #{task_id} was not found or is not owned by you."
EDIT_CANCELLED = "❌ Edit cancelled. No changes were made."


# ===========================================================================
# Phase 5 & 6 — Reminder & Snooze Notifications
# ===========================================================================

REMINDER_NOTIFICATION = (
    "⏰ <b>Task Reminder!</b>\n\n"
    "📌 <b>{title}</b>\n"
    "⏰ <b>Due:</b> {due_display}\n"
    "🏷️ <b>Priority:</b> {priority_icon} {priority_label}\n"
    "🔁 <b>Repeat:</b> {recurrence_label}\n"
    "🆔 <b>Task ID:</b> #{task_id}"
)

SNOOZE_SUCCESS = (
    "😴 <b>Reminder Snoozed</b>\n\n"
    "📌 <b>{title}</b>\n"
    "⏰ <b>New reminder:</b> {due_display}\n\n"
    "<i>We'll remind you then!</i>"
)
SNOOZE_NOT_FOUND = "❌ Task #{task_id} was not found or is not owned by you."
SNOOZE_ALREADY_COMPLETED = "ℹ️ Task #{task_id} is already completed and cannot be snoozed."
SNOOZE_ALREADY_CANCELLED = "⚠️ Task #{task_id} is deleted and cannot be snoozed."


# ===========================================================================
# Phase 7 — User Settings & Daily Summary Message Formatting
# ===========================================================================

TIMEZONE_SELECTION_PROMPT = """\
🌐 <b>Select Your Timezone</b>

Current timezone: <b>{current_timezone}</b>

Choose a quick-pick timezone below, or tap <b>Custom Timezone</b> to enter any valid IANA timezone (e.g. <code>Asia/Singapore</code>, <code>America/Los_Angeles</code>).\
"""

SUMMARY_TIME_SELECTION_PROMPT = """\
⏰ <b>Select Daily Summary Time</b>

Current delivery time: <b>{current_time}</b> (local time)

Choose a quick-pick time below, or tap <b>Custom Time</b> to enter any 24-hour time (<code>HH:MM</code>).\
"""


def format_settings_message(settings: "UserSettingsDTO") -> str:
    """
    Format user settings into an HTML dashboard message.

    Displays:
      • Current timezone
      • Task reminders: enabled/disabled (with icon)
      • Daily summary: enabled/disabled (with icon)
      • Daily summary delivery time (local)
      • Last delivered summary date (if present)
    """
    rem_status = "🔔 Enabled" if settings.reminders_enabled else "🔕 Disabled"
    sum_status = "📊 Enabled" if settings.daily_summary_enabled else "⏹️ Disabled"

    lines = [
        "⚙️ <b>Settings & Preferences</b>",
        "",
        f"🌐 <b>Timezone:</b> <code>{html.escape(settings.timezone)}</code>",
        f"🔔 <b>Task Reminders:</b> {rem_status}",
        f"📊 <b>Daily Summary:</b> {sum_status}",
        f"⏰ <b>Summary Delivery Time:</b> <code>{html.escape(settings.daily_summary_time)}</code> (local)",
    ]

    if getattr(settings, "last_summary_date", None):
        lines.append(f"🗓️ <b>Last Summary Sent:</b> <code>{html.escape(str(settings.last_summary_date))}</code>")

    lines.extend([
        "",
        "<i>Use the buttons below to toggle options or change your schedule.</i>",
    ])
    return "\n".join(lines)


def format_daily_summary_message(
    summary: "DailySummaryDTO",
    max_length: int = 4000,
) -> str:
    """
    Format a DailySummaryDTO into an HTML Telegram message.

    Guarantees:
      • User-submitted task titles are safely HTML-escaped.
      • Clear distinction between overdue tasks and today's tasks.
      • Empty state message when there are no relevant tasks.
      • Output is bounded and never exceeds max_length (Telegram limit is 4096).
    """
    from bot.utils.datetime_utils import format_date_only, format_time_only
    from bot.utils.keyboards import PRIORITY_ICONS, STATUS_ICONS

    date_str = summary.date.strftime("%d %b %Y")

    if summary.today_total_count == 0 and summary.overdue_count == 0:
        return (
            f"📊 <b>Daily Task Summary ({date_str})</b>\n\n"
            "🎉 <b>No tasks scheduled for today and no overdue items!</b>\n\n"
            "Enjoy your day, or use /add to create a new task."
        )

    header_lines = [
        f"📊 <b>Daily Task Summary ({date_str})</b>",
        "",
        f"📋 <b>Today's Tasks:</b> {summary.today_total_count} "
        f"({summary.today_completed_count} completed, {summary.today_pending_count} pending)",
    ]
    if summary.overdue_count > 0:
        header_lines.append(f"⚠️ <b>Overdue Tasks:</b> {summary.overdue_count}")

    # Build overdue section lines
    overdue_lines: list[str] = []
    if summary.overdue_tasks:
        overdue_lines.append("\n<b>⚠️ Overdue Backlog:</b>")
        for t in summary.overdue_tasks:
            priority_val = getattr(t.priority, "value", t.priority)
            p_icon = PRIORITY_ICONS.get(priority_val, "⚪")
            due_str = format_date_only(t.due_at, summary.timezone) if t.due_at else "Past"
            escaped_title = html.escape(t.title)
            overdue_lines.append(f"• [{p_icon}] {escaped_title} <i>(due {due_str})</i>")

    # Build today's agenda lines
    today_lines: list[str] = []
    if summary.today_tasks:
        today_lines.append("\n<b>📅 Today's Agenda:</b>")
        for idx, t in enumerate(summary.today_tasks, start=1):
            status_val = getattr(t.status, "value", t.status)
            priority_val = getattr(t.priority, "value", t.priority)
            s_icon = STATUS_ICONS.get(status_val, "•")
            p_icon = PRIORITY_ICONS.get(priority_val, "⚪")
            time_str = format_time_only(t.due_at, summary.timezone) if t.due_at else "--:--"
            escaped_title = html.escape(t.title)
            if status_val == "completed":
                today_lines.append(f"{idx}. {s_icon} <b>{time_str}</b> [{p_icon}] <s>{escaped_title}</s>")
            else:
                today_lines.append(f"{idx}. {s_icon} <b>{time_str}</b> [{p_icon}] {escaped_title}")

    # Combine with length budget enforcement
    all_content_lines = overdue_lines + today_lines
    rendered_parts = ["\n".join(header_lines)]
    current_length = len(rendered_parts[0])
    truncated_count = 0

    for line in all_content_lines:
        line_cost = len(line) + 1  # newline + line length
        # Reserve 120 characters for truncation footnote if needed
        if current_length + line_cost + 120 > max_length:
            # If line is an item (not a sub-header like \n<b>...</b>)
            if not line.startswith("\n<b>"):
                truncated_count += 1
        else:
            rendered_parts.append(line)
            current_length += line_cost

    if truncated_count > 0:
        footnote = f"\n<i>… and {truncated_count} more tasks (use /today or /upcoming to view all)</i>"
        rendered_parts.append(footnote)

    return "\n".join(rendered_parts)


