"""
handlers/tasks.py — Task management ConversationHandler.

Phase 2: /add — guided 5-step task creation flow.
Phase 3: /today, /upcoming  (stubs below)
Phase 4: /done, /edit, /delete  (stubs below)

Conversation flow for /add:
  /add
    ↓ [ASK_TITLE]   — bot asks for task title
    ↓ [ASK_DATE]    — bot asks for date  (DD/MM/YYYY)
    ↓ [ASK_TIME]    — bot asks for time  (HH:MM 24h)
    ↓ [ASK_PRIORITY]— bot shows priority inline keyboard
    ↓ [CONFIRM]     — bot shows summary + Save/Cancel inline keyboard
    → Saved to DB / Cancelled

Design rules:
  • All Telegram I/O (reply, edit_message, query.answer) stays HERE.
  • All business logic (validation rules, DB writes) lives in services/.
  • Inline keyboard callback_data constants are imported from keyboards.py.
  • Intermediate form data is held in context.user_data under UD_* keys.
  • context.user_data is always fully cleared when the conversation ends
    (success, cancel, or error).
"""

import html
import logging
from datetime import date, datetime, time

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.config import settings
from bot.database.database import get_db
from bot.database.models import Task, TaskPriority, TaskStatus
from bot.services.task_service import create_task, get_today_tasks, get_upcoming_tasks
from bot.services.user_service import get_or_create_user, get_user_by_telegram_id
from bot.utils.datetime_utils import (
    combine_to_utc,
    current_time_display,
    example_date_string,
    format_date_heading,
    format_date_only,
    format_dt_local,
    format_time_only,
    is_in_past,
    parse_date,
    parse_time,
)
from bot.utils.keyboards import (
    CB_CONFIRM_CANCEL,
    CB_CONFIRM_SAVE,
    CB_PRIORITY_HIGH,
    CB_PRIORITY_LOW,
    CB_PRIORITY_MEDIUM,
    CB_TODAY_REFRESH,
    CB_UPCOMING_REFRESH,
    CB_VIEW_TODAY,
    CB_VIEW_UPCOMING,
    PRIORITY_ICONS,
    STATUS_ICONS,
    confirm_task_keyboard,
    priority_keyboard,
    today_keyboard,
    upcoming_keyboard,
)
from bot.utils.messages import (
    ADD_TASK_ASK_DATE,
    ADD_TASK_ASK_PRIORITY,
    ADD_TASK_ASK_TIME,
    ADD_TASK_CANCELLED,
    ADD_TASK_CONFIRM,
    ADD_TASK_START,
    ADD_TASK_SUCCESS,
    ERR_DATETIME_IN_PAST,
    ERR_INVALID_DATE,
    ERR_INVALID_TIME,
    ERR_TITLE_EMPTY,
    ERR_TITLE_TOO_LONG,
    ERR_USE_BUTTONS,
    TODAY_EMPTY,
    TODAY_HEADER,
    TODAY_PROGRESS,
    UPCOMING_EMPTY,
    UPCOMING_HEADER,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ConversationHandler state identifiers
# ---------------------------------------------------------------------------

ASK_TITLE, ASK_DATE, ASK_TIME, ASK_PRIORITY, CONFIRM = range(5)

# ---------------------------------------------------------------------------
# context.user_data keys — prefixed with "add_" to avoid collisions
# ---------------------------------------------------------------------------

UD_TITLE = "add_title"
UD_DATE = "add_date"
UD_TIME = "add_time"
UD_PRIORITY = "add_priority"
UD_TIMEZONE = "add_timezone"      # Cached at conversation start; avoids repeat DB calls

_ALL_ADD_KEYS = [UD_TITLE, UD_DATE, UD_TIME, UD_PRIORITY, UD_TIMEZONE]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PRIORITY_MAP: dict[str, TaskPriority] = {
    CB_PRIORITY_LOW: TaskPriority.low,
    CB_PRIORITY_MEDIUM: TaskPriority.medium,
    CB_PRIORITY_HIGH: TaskPriority.high,
}


def _clear_add_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove all /add conversation keys from context.user_data."""
    for key in _ALL_ADD_KEYS:
        context.user_data.pop(key, None)  # type: ignore[union-attr]


def _priority_label(priority: TaskPriority) -> str:
    """Return a human-readable label with emoji for a priority value."""
    icon = PRIORITY_ICONS.get(priority.value, "⚪")
    return f"{icon} {priority.value.capitalize()}"


# ---------------------------------------------------------------------------
# Step 0 — Entry: /add command
# ---------------------------------------------------------------------------

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Entry point for /add.

    Ensures the user record exists (creates it if not), caches their
    timezone for the duration of the conversation, then asks for the title.
    """
    tg_user = update.effective_user
    if tg_user is None:
        return ConversationHandler.END

    logger.info("/add started by telegram_user_id=%s", tg_user.id)

    # Upsert user record and cache timezone — one DB call at conversation start.
    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        cached_tz = user.timezone

    # Clear any stale state from a previous interrupted /add, then set timezone.
    _clear_add_state(context)
    context.user_data[UD_TIMEZONE] = cached_tz  # type: ignore[index]

    await update.message.reply_text(ADD_TASK_START, parse_mode="HTML")
    return ASK_TITLE


# ---------------------------------------------------------------------------
# Step 1 — Receive task title
# ---------------------------------------------------------------------------

async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Validate and store the task title, then ask for the date.

    Validation:
      • Not empty (after stripping whitespace).
      • Not longer than 500 characters.
    """
    title = update.message.text.strip()

    if not title:
        await update.message.reply_text(ERR_TITLE_EMPTY, parse_mode="HTML")
        return ASK_TITLE

    max_len = 500
    if len(title) > max_len:
        await update.message.reply_text(
            ERR_TITLE_TOO_LONG.format(length=len(title), max_length=max_len),
            parse_mode="HTML",
        )
        return ASK_TITLE

    context.user_data[UD_TITLE] = title  # type: ignore[index]

    tz = context.user_data.get(UD_TIMEZONE, "Asia/Kolkata")  # type: ignore[union-attr]
    await update.message.reply_text(
        ADD_TASK_ASK_DATE.format(example_date=example_date_string(tz)),
        parse_mode="HTML",
    )
    return ASK_DATE


# ---------------------------------------------------------------------------
# Step 2 — Receive date
# ---------------------------------------------------------------------------

async def receive_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Validate and store the task date, then ask for the time.

    Validation:
      • Must match DD/MM/YYYY format exactly.
      (Full past-datetime check is deferred to receive_time, when we have
      both date and time and can form the complete UTC datetime.)
    """
    text = update.message.text.strip()
    parsed = parse_date(text)

    if parsed is None:
        tz = context.user_data.get(UD_TIMEZONE, "Asia/Kolkata")  # type: ignore[union-attr]
        await update.message.reply_text(
            ERR_INVALID_DATE.format(example_date=example_date_string(tz)),
            parse_mode="HTML",
        )
        return ASK_DATE

    context.user_data[UD_DATE] = parsed  # type: ignore[index]

    await update.message.reply_text(ADD_TASK_ASK_TIME, parse_mode="HTML")
    return ASK_TIME


# ---------------------------------------------------------------------------
# Step 3 — Receive time
# ---------------------------------------------------------------------------

async def receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Validate and store the task time, then ask for priority.

    Validation:
      • Must match HH:MM (24-hour) format exactly.
      • The combined date + time (in the user's timezone) must be in the future.
    """
    text = update.message.text.strip()
    parsed = parse_time(text)

    if parsed is None:
        await update.message.reply_text(ERR_INVALID_TIME, parse_mode="HTML")
        return ASK_TIME

    tz: str = context.user_data.get(UD_TIMEZONE, "Asia/Kolkata")  # type: ignore[union-attr]
    task_date: date = context.user_data[UD_DATE]  # type: ignore[index]
    due_at_utc = combine_to_utc(task_date, parsed, tz)

    if is_in_past(due_at_utc):
        await update.message.reply_text(
            ERR_DATETIME_IN_PAST.format(current_time=current_time_display(tz)),
            parse_mode="HTML",
        )
        return ASK_TIME

    context.user_data[UD_TIME] = parsed  # type: ignore[index]

    await update.message.reply_text(
        ADD_TASK_ASK_PRIORITY,
        parse_mode="HTML",
        reply_markup=priority_keyboard(),
    )
    return ASK_PRIORITY


# ---------------------------------------------------------------------------
# Step 3b — Text received while waiting for priority button (guard)
# ---------------------------------------------------------------------------

async def priority_text_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Politely redirect if the user types text instead of tapping a priority button."""
    await update.message.reply_text(ERR_USE_BUTTONS)
    return ASK_PRIORITY


# ---------------------------------------------------------------------------
# Step 4 — Receive priority (inline keyboard callback)
# ---------------------------------------------------------------------------

async def receive_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Store the selected priority and show the full task confirmation summary.

    Triggered by a CallbackQuery from the priority inline keyboard.
    Edits the keyboard message to show the confirmation instead of
    adding a new message (cleaner UX).
    """
    query = update.callback_query
    await query.answer()  # Dismiss the loading spinner on the button

    priority = _PRIORITY_MAP.get(query.data)
    if priority is None:
        # Should never happen if keyboards.py callback_data values are correct
        await query.message.reply_text(ERR_USE_BUTTONS)
        return ASK_PRIORITY

    context.user_data[UD_PRIORITY] = priority  # type: ignore[index]

    # Build confirmation display using cached values
    tz: str = context.user_data[UD_TIMEZONE]  # type: ignore[index]
    title: str = context.user_data[UD_TITLE]  # type: ignore[index]
    task_date: date = context.user_data[UD_DATE]  # type: ignore[index]
    task_time: time = context.user_data[UD_TIME]  # type: ignore[index]

    due_at_utc = combine_to_utc(task_date, task_time, tz)
    due_display = format_dt_local(due_at_utc, tz)
    priority_icon = PRIORITY_ICONS.get(priority.value, "⚪")

    await query.edit_message_text(
        ADD_TASK_CONFIRM.format(
            title=title,
            due_display=due_display,
            priority_icon=priority_icon,
            priority_label=priority.value.capitalize(),
        ),
        parse_mode="HTML",
        reply_markup=confirm_task_keyboard(),
    )
    return CONFIRM


# ---------------------------------------------------------------------------
# Step 4b — Text received while waiting for confirm button (guard)
# ---------------------------------------------------------------------------

async def confirm_text_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Politely redirect if the user types text instead of tapping Save/Cancel."""
    await update.message.reply_text(ERR_USE_BUTTONS)
    return CONFIRM


# ---------------------------------------------------------------------------
# Step 5 — Receive confirmation (inline keyboard callback)
# ---------------------------------------------------------------------------

async def receive_confirmation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Final step: either save the task to the database or cancel.

    On Save:
      • Reads all cached form data from context.user_data.
      • Calls task_service.create_task() — the only place DB write happens.
      • Clears conversation state.
      • Edits the confirmation message to show the success summary.

    On Cancel:
      • Clears conversation state.
      • Edits the confirmation message to show a cancellation notice.
    """
    query = update.callback_query
    await query.answer()

    if query.data == CB_CONFIRM_CANCEL:
        _clear_add_state(context)
        await query.edit_message_text(ADD_TASK_CANCELLED)
        logger.info(
            "Task creation cancelled at confirmation by %s",
            update.effective_user.id if update.effective_user else "unknown",
        )
        return ConversationHandler.END

    if query.data != CB_CONFIRM_SAVE:
        # Unexpected callback — stay in CONFIRM state
        await query.message.reply_text(ERR_USE_BUTTONS)
        return CONFIRM

    # --- Save path ---
    tg_user = update.effective_user
    if tg_user is None:
        _clear_add_state(context)
        return ConversationHandler.END

    # Read all cached form data BEFORE clearing
    tz: str = context.user_data[UD_TIMEZONE]  # type: ignore[index]
    title: str = context.user_data[UD_TITLE]  # type: ignore[index]
    task_date: date = context.user_data[UD_DATE]  # type: ignore[index]
    task_time: time = context.user_data[UD_TIME]  # type: ignore[index]
    priority: TaskPriority = context.user_data[UD_PRIORITY]  # type: ignore[index]

    due_at_utc = combine_to_utc(task_date, task_time, tz)

    try:
        with get_db() as db:
            user = get_user_by_telegram_id(db, tg_user.id)
            if user is None:
                # Edge case: user record somehow missing — create it
                user = get_or_create_user(
                    db=db,
                    telegram_user_id=tg_user.id,
                    username=tg_user.username,
                    first_name=tg_user.first_name,
                )
            task = create_task(
                db=db,
                user=user,
                title=title,
                due_at_utc=due_at_utc,
                priority=priority,
            )
            # Read task.id and due_at inside the session before closing
            task_id = task.id
            due_display = format_dt_local(task.due_at, tz)

    except Exception:
        logger.exception(
            "Failed to save task for telegram_user_id=%s", tg_user.id
        )
        _clear_add_state(context)
        from bot.utils.messages import ERROR_UNEXPECTED
        await query.edit_message_text(ERROR_UNEXPECTED)
        return ConversationHandler.END

    # Clear conversation state AFTER successful save
    priority_icon = PRIORITY_ICONS.get(priority.value, "⚪")
    _clear_add_state(context)

    await query.edit_message_text(
        ADD_TASK_SUCCESS.format(
            title=title,
            due_display=due_display,
            priority_icon=priority_icon,
            priority_label=priority.value.capitalize(),
            task_id=task_id,
        ),
        parse_mode="HTML",
    )

    logger.info(
        "Task saved: id=%s telegram_user_id=%s", task_id, tg_user.id
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Fallback — /cancel works at every step
# ---------------------------------------------------------------------------

async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    /cancel fallback handler — terminates the conversation from any state.

    Clears all cached form data so a subsequent /add starts clean.
    """
    _clear_add_state(context)
    await update.message.reply_text(ADD_TASK_CANCELLED)
    logger.info(
        "/cancel during /add from %s",
        update.effective_user.id if update.effective_user else "unknown",
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# ConversationHandler assembly
# ---------------------------------------------------------------------------

import warnings
from telegram.warnings import PTBUserWarning

# Filter warning: per_message=False is intentional since this is a user-level conversation
warnings.filterwarnings("ignore", message=r".*per_message=False.*", category=PTBUserWarning)

_add_conversation = ConversationHandler(
    entry_points=[CommandHandler("add", add_start)],
    states={
        ASK_TITLE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title),
        ],
        ASK_DATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_date),
        ],
        ASK_TIME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_time),
        ],
        ASK_PRIORITY: [
            # Inline keyboard response
            CallbackQueryHandler(receive_priority, pattern="^priority:"),
            # Guard: user typed text instead of pressing a button
            MessageHandler(filters.TEXT & ~filters.COMMAND, priority_text_guard),
        ],
        CONFIRM: [
            # Inline keyboard response
            CallbackQueryHandler(receive_confirmation, pattern="^confirm:"),
            # Guard: user typed text instead of pressing a button
            MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_text_guard),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_add),
    ],
    # If the user sends /add while mid-conversation, restart cleanly
    allow_reentry=True,
    # Track state per-chat (correct for a personal single-user bot)
    per_chat=True,
    per_user=True,
    per_message=False,
)


# ---------------------------------------------------------------------------
# Phase 3: Task Listing Views (/today & /upcoming)
# ---------------------------------------------------------------------------

def format_today_view(tasks: list[Task], tz_string: str) -> str:
    """Format the list of tasks for the /today message."""
    if not tasks:
        return TODAY_EMPTY

    import pytz

    local_now = datetime.now(pytz.timezone(tz_string))
    date_str = local_now.strftime("%d %b %Y")

    completed_count = sum(1 for t in tasks if t.status == TaskStatus.completed)
    total_count = len(tasks)
    pct = int((completed_count / total_count) * 100) if total_count > 0 else 0

    lines = [
        TODAY_HEADER.format(date_str=date_str),
        TODAY_PROGRESS.format(completed=completed_count, total=total_count, pct=pct),
    ]

    for idx, t in enumerate(tasks, start=1):
        s_icon = STATUS_ICONS.get(t.status.value, "•")
        p_icon = PRIORITY_ICONS.get(t.priority.value, "⚪")
        time_str = format_time_only(t.due_at, tz_string) if t.due_at else "--:--"
        escaped_title = html.escape(t.title)

        if t.status == TaskStatus.completed:
            task_line = f"{idx}. {s_icon} <b>{time_str}</b> [{p_icon}] <s>{escaped_title}</s>"
        else:
            task_line = f"{idx}. {s_icon} <b>{time_str}</b> [{p_icon}] {escaped_title}"
        lines.append(task_line)

    return "\n".join(lines)


def format_upcoming_view(tasks: list[Task], tz_string: str, window_days: int) -> str:
    """Format the list of upcoming pending tasks grouped by date."""
    if not tasks:
        return UPCOMING_EMPTY.format(window_days=window_days)

    lines = [UPCOMING_HEADER.format(window_days=window_days).strip()]

    current_heading = None
    for t in tasks:
        if not t.due_at:
            continue
        heading = format_date_heading(t.due_at, tz_string)
        if heading != current_heading:
            current_heading = heading
            lines.append(f"\n<b>📌 {heading}</b>")

        s_icon = STATUS_ICONS.get(t.status.value, "⏳")
        p_icon = PRIORITY_ICONS.get(t.priority.value, "⚪")
        time_str = format_time_only(t.due_at, tz_string)
        escaped_title = html.escape(t.title)
        lines.append(f"  • {s_icon} <b>{time_str}</b> [{p_icon}] {escaped_title}")

    return "\n".join(lines)


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /today — display today's tasks."""
    tg_user = update.effective_user
    if tg_user is None:
        return

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        tasks = get_today_tasks(db, user)
        tz = user.timezone

    message_text = format_today_view(tasks, tz)
    await update.message.reply_text(
        message_text,
        parse_mode="HTML",
        reply_markup=today_keyboard(),
    )


async def upcoming_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /upcoming — display upcoming tasks."""
    tg_user = update.effective_user
    if tg_user is None:
        return

    window = settings.UPCOMING_DAYS_WINDOW
    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        tasks = get_upcoming_tasks(db, user, days=window)
        tz = user.timezone

    message_text = format_upcoming_view(tasks, tz, window)
    await update.message.reply_text(
        message_text,
        parse_mode="HTML",
        reply_markup=upcoming_keyboard(),
    )


async def today_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle refresh and navigation to today view from inline buttons."""
    query = update.callback_query
    await query.answer()
    tg_user = update.effective_user
    if tg_user is None:
        return

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        tasks = get_today_tasks(db, user)
        tz = user.timezone

    text = format_today_view(tasks, tz)
    try:
        await query.edit_message_text(
            text, parse_mode="HTML", reply_markup=today_keyboard()
        )
    except Exception:
        pass


async def upcoming_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle refresh and navigation to upcoming view from inline buttons."""
    query = update.callback_query
    await query.answer()
    tg_user = update.effective_user
    if tg_user is None:
        return

    window = settings.UPCOMING_DAYS_WINDOW
    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        tasks = get_upcoming_tasks(db, user, days=window)
        tz = user.timezone

    text = format_upcoming_view(tasks, tz, window)
    try:
        await query.edit_message_text(
            text, parse_mode="HTML", reply_markup=upcoming_keyboard()
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Exported handler list — consumed by main.py
# ---------------------------------------------------------------------------

handlers = [
    _add_conversation,
    CommandHandler("today", today_command),
    CommandHandler("upcoming", upcoming_command),
    CallbackQueryHandler(today_callback, pattern=f"^({CB_TODAY_REFRESH}|{CB_VIEW_TODAY})$"),
    CallbackQueryHandler(upcoming_callback, pattern=f"^({CB_UPCOMING_REFRESH}|{CB_VIEW_UPCOMING})$"),
]
