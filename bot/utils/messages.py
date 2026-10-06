"""
utils/messages.py — All user-facing message strings in one place.

Keeping message text here (rather than inline in handlers) makes it easy to:
  • Edit wording without touching handler logic.
  • Add i18n / translations later without changing handler code.

Messages use Python str.format() placeholders like {first_name}.
HTML parse_mode is used so <b> and <code> tags render in Telegram.
"""

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

# --- Confirmation ---

ADD_TASK_CONFIRM = (
    "📋 <b>Review your task</b>\n\n"
    "📝 <b>Title:</b> {title}\n"
    "⏰ <b>Reminder:</b> {due_display}\n"
    "🏷️ <b>Priority:</b> {priority_icon} {priority_label}\n\n"
    "Shall I save this task?"
)

# --- Success ---

ADD_TASK_SUCCESS = (
    "✅ <b>Task saved!</b>\n\n"
    "📝 {title}\n"
    "⏰ <b>Reminder:</b> {due_display}\n"
    "🏷️ <b>Priority:</b> {priority_icon} {priority_label}\n"
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
