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
from datetime import date, datetime, time, timezone
from typing import Optional

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
from bot.database.models import RECURRENCE_LABELS, Task, TaskPriority, TaskRecurrence, TaskStatus
from bot.services.task_service import (
    _UNSET,
    complete_task,
    create_task,
    delete_task,
    edit_task,
    get_pending_tasks,
    get_task_by_id,
    get_today_tasks,
    get_upcoming_tasks,
    snooze_task,
)
from bot.services.user_service import get_or_create_user, get_user_by_telegram_id
from bot.utils.datetime_utils import (
    calculate_snooze_datetime,
    combine_to_utc,
    current_time_display,
    example_date_string,
    format_date_heading,
    format_date_only,
    format_dt_local,
    format_time_only,
    get_local_date_and_time,
    is_in_past,
    parse_date,
    parse_time,
)
from bot.utils.keyboards import (
    CB_CONFIRM_CANCEL,
    CB_CONFIRM_SAVE,
    CB_DELETE_CANCEL,
    CB_DONE_CANCEL,
    CB_EDIT_CANCEL,
    CB_EDIT_FIELD_DATE,
    CB_EDIT_FIELD_PRIORITY,
    CB_EDIT_FIELD_RECURRENCE,
    CB_EDIT_FIELD_TIME,
    CB_EDIT_FIELD_TITLE,
    CB_EDIT_SAVE,
    CB_PRIORITY_HIGH,
    CB_PRIORITY_LOW,
    CB_PRIORITY_MEDIUM,
    CB_REC_DAILY,
    CB_REC_MONTHLY,
    CB_REC_NONE,
    CB_REC_WEEKLY,
    CB_TODAY_REFRESH,
    CB_UPCOMING_REFRESH,
    CB_VIEW_TODAY,
    CB_VIEW_UPCOMING,
    PRIORITY_ICONS,
    STATUS_ICONS,
    action_nav_keyboard,
    confirm_delete_keyboard,
    confirm_edit_keyboard,
    confirm_task_keyboard,
    edit_fields_keyboard,
    priority_keyboard,
    recurrence_keyboard,
    task_selection_keyboard,
    today_keyboard,
    upcoming_keyboard,
)
from bot.utils.messages import (
    ADD_TASK_ASK_DATE,
    ADD_TASK_ASK_PRIORITY,
    ADD_TASK_ASK_RECURRENCE,
    ADD_TASK_ASK_TIME,
    ADD_TASK_CANCELLED,
    ADD_TASK_CONFIRM,
    ADD_TASK_START,
    ADD_TASK_SUCCESS,
    DELETE_CANCELLED,
    DELETE_CONFIRM,
    DELETE_NOT_FOUND,
    DELETE_NO_TASKS,
    DELETE_SELECT_TASK,
    DELETE_SUCCESS,
    DONE_ALREADY_CANCELLED,
    DONE_ALREADY_COMPLETED,
    DONE_CANCELLED,
    DONE_NOT_FOUND,
    DONE_NO_PENDING,
    DONE_SELECT_TASK,
    DONE_SUCCESS,
    DONE_SUCCESS_RECURRING,
    EDIT_ASK_DATE,
    EDIT_ASK_PRIORITY,
    EDIT_ASK_RECURRENCE,
    EDIT_ASK_TIME,
    EDIT_ASK_TITLE,
    EDIT_CANCELLED,
    EDIT_CONFIRM,
    EDIT_MENU,
    EDIT_NOT_FOUND,
    EDIT_NO_TASKS,
    EDIT_SELECT_TASK,
    EDIT_SUCCESS,
    ERR_DATETIME_IN_PAST,
    ERR_INVALID_DATE,
    ERR_INVALID_TIME,
    ERR_TITLE_EMPTY,
    ERR_TITLE_TOO_LONG,
    ERR_USE_BUTTONS,
    SNOOZE_ALREADY_CANCELLED,
    SNOOZE_ALREADY_COMPLETED,
    SNOOZE_NOT_FOUND,
    SNOOZE_SUCCESS,
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

ASK_TITLE, ASK_DATE, ASK_TIME, ASK_PRIORITY, ASK_RECURRENCE, CONFIRM = range(6)

# ---------------------------------------------------------------------------
# context.user_data keys — prefixed with "add_" to avoid collisions
# ---------------------------------------------------------------------------

UD_TITLE = "add_title"
UD_DATE = "add_date"
UD_TIME = "add_time"
UD_PRIORITY = "add_priority"
UD_RECURRENCE = "add_recurrence"
UD_TIMEZONE = "add_timezone"      # Cached at conversation start; avoids repeat DB calls

_ALL_ADD_KEYS = [UD_TITLE, UD_DATE, UD_TIME, UD_PRIORITY, UD_RECURRENCE, UD_TIMEZONE]

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
    Store the selected priority and prompt for recurrence schedule.

    Triggered by a CallbackQuery from the priority inline keyboard.
    Edits the keyboard message to ask for recurrence schedule.
    """
    query = update.callback_query
    await query.answer()  # Dismiss the loading spinner on the button

    priority = _PRIORITY_MAP.get(query.data)
    if priority is None:
        # Should never happen if keyboards.py callback_data values are correct
        await query.message.reply_text(ERR_USE_BUTTONS)
        return ASK_PRIORITY

    context.user_data[UD_PRIORITY] = priority  # type: ignore[index]

    await query.edit_message_text(
        ADD_TASK_ASK_RECURRENCE,
        parse_mode="HTML",
        reply_markup=recurrence_keyboard(),
    )
    return ASK_RECURRENCE


# ---------------------------------------------------------------------------
# Step 4b — Recurrence handling (inline keyboard callback & text guard)
# ---------------------------------------------------------------------------

_RECURRENCE_MAP: dict[str, Optional[str]] = {
    CB_REC_NONE: None,
    CB_REC_DAILY: TaskRecurrence.daily.value,
    CB_REC_WEEKLY: TaskRecurrence.weekly.value,
    CB_REC_MONTHLY: TaskRecurrence.monthly.value,
}


async def recurrence_text_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Politely redirect if the user types text instead of tapping a recurrence button."""
    await update.message.reply_text(ERR_USE_BUTTONS)
    return ASK_RECURRENCE


async def receive_recurrence(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Store the selected recurrence schedule and show the full task confirmation summary.
    """
    query = update.callback_query
    await query.answer()

    if query.data not in _RECURRENCE_MAP:
        await query.message.reply_text(ERR_USE_BUTTONS)
        return ASK_RECURRENCE

    recurrence_val = _RECURRENCE_MAP[query.data]
    context.user_data[UD_RECURRENCE] = recurrence_val  # type: ignore[index]

    # Build confirmation display using cached values
    tz: str = context.user_data[UD_TIMEZONE]  # type: ignore[index]
    title: str = context.user_data[UD_TITLE]  # type: ignore[index]
    task_date: date = context.user_data[UD_DATE]  # type: ignore[index]
    task_time: time = context.user_data[UD_TIME]  # type: ignore[index]
    priority: TaskPriority = context.user_data[UD_PRIORITY]  # type: ignore[index]

    due_at_utc = combine_to_utc(task_date, task_time, tz)
    due_display = format_dt_local(due_at_utc, tz)
    priority_icon = PRIORITY_ICONS.get(priority.value, "⚪")
    recurrence_label = RECURRENCE_LABELS.get(recurrence_val, "None (one-time)")

    await query.edit_message_text(
        ADD_TASK_CONFIRM.format(
            title=title,
            due_display=due_display,
            priority_icon=priority_icon,
            priority_label=priority.value.capitalize(),
            recurrence_label=recurrence_label,
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
    recurrence: Optional[str] = context.user_data.get(UD_RECURRENCE)  # type: ignore[union-attr]

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
                recurrence=recurrence,
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
    recurrence_label = RECURRENCE_LABELS.get(recurrence, "None (one-time)")
    _clear_add_state(context)

    await query.edit_message_text(
        ADD_TASK_SUCCESS.format(
            title=title,
            due_display=due_display,
            priority_icon=priority_icon,
            priority_label=priority.value.capitalize(),
            recurrence_label=recurrence_label,
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
        ASK_RECURRENCE: [
            # Inline keyboard response
            CallbackQueryHandler(receive_recurrence, pattern="^rec:"),
            # Guard: user typed text instead of pressing a button
            MessageHandler(filters.TEXT & ~filters.COMMAND, recurrence_text_guard),
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
# Phase 4: Task Actions (/done, /delete, /edit)
# ---------------------------------------------------------------------------

# ConversationHandler states for /edit
(
    STATE_EDIT_SELECT_TASK,
    STATE_EDIT_CHOOSE_FIELD,
    STATE_EDIT_INPUT_TITLE,
    STATE_EDIT_INPUT_DATE,
    STATE_EDIT_INPUT_TIME,
    STATE_EDIT_INPUT_PRIORITY,
    STATE_EDIT_INPUT_RECURRENCE,
    STATE_EDIT_CONFIRM,
) = range(10, 18)

# Keys for context.user_data in /edit
UD_EDIT_TASK_ID = "edit_task_id"
UD_EDIT_ORIG_TITLE = "edit_orig_title"
UD_EDIT_ORIG_DUE = "edit_orig_due"
UD_EDIT_ORIG_PRIORITY = "edit_orig_priority"
UD_EDIT_ORIG_RECURRENCE = "edit_orig_recurrence"
UD_EDIT_NEW_TITLE = "edit_new_title"
UD_EDIT_NEW_DUE = "edit_new_due"
UD_EDIT_NEW_PRIORITY = "edit_new_priority"
UD_EDIT_NEW_RECURRENCE = "edit_new_recurrence"
UD_EDIT_TIMEZONE = "edit_timezone"

_ALL_EDIT_KEYS = [
    UD_EDIT_TASK_ID,
    UD_EDIT_ORIG_TITLE,
    UD_EDIT_ORIG_DUE,
    UD_EDIT_ORIG_PRIORITY,
    UD_EDIT_ORIG_RECURRENCE,
    UD_EDIT_NEW_TITLE,
    UD_EDIT_NEW_DUE,
    UD_EDIT_NEW_PRIORITY,
    UD_EDIT_NEW_RECURRENCE,
    UD_EDIT_TIMEZONE,
]


def _clear_edit_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear all /edit keys from user_data."""
    for k in _ALL_EDIT_KEYS:
        context.user_data.pop(k, None)


def _render_edit_confirm_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Build summary text for edit confirmation."""
    task_id = context.user_data[UD_EDIT_TASK_ID]
    tz = context.user_data[UD_EDIT_TIMEZONE]
    title = context.user_data.get(UD_EDIT_NEW_TITLE) or context.user_data[UD_EDIT_ORIG_TITLE]
    due_at = context.user_data.get(UD_EDIT_NEW_DUE) or context.user_data[UD_EDIT_ORIG_DUE]
    priority = context.user_data.get(UD_EDIT_NEW_PRIORITY) or context.user_data[UD_EDIT_ORIG_PRIORITY]

    rec_val = (
        context.user_data[UD_EDIT_NEW_RECURRENCE]
        if UD_EDIT_NEW_RECURRENCE in context.user_data
        else context.user_data.get(UD_EDIT_ORIG_RECURRENCE)
    )
    rec_label = RECURRENCE_LABELS.get(rec_val, "None (one-time)")

    due_display = format_dt_local(due_at, tz) if due_at else "No reminder"
    p_icon = PRIORITY_ICONS.get(priority.value, "⚪")

    return EDIT_CONFIRM.format(
        task_id=task_id,
        title=html.escape(title),
        due_display=due_display,
        priority_icon=p_icon,
        priority_label=priority.value.capitalize(),
        recurrence_label=rec_label,
    )


# --- /done handlers ---

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /done [task_id]."""
    tg_user = update.effective_user
    if tg_user is None:
        return

    # Case 1: user passed argument e.g. /done 5
    if context.args and context.args[0].isdigit():
        task_id = int(context.args[0])
        with get_db() as db:
            user = get_or_create_user(db, tg_user.id, tg_user.username, tg_user.first_name)
            task = get_task_by_id(db, task_id, user.id)
            if task is None:
                await update.message.reply_text(
                    DONE_NOT_FOUND.format(task_id=task_id), parse_mode="HTML"
                )
                return
            if task.status == TaskStatus.completed:
                await update.message.reply_text(
                    DONE_ALREADY_COMPLETED.format(task_id=task_id), parse_mode="HTML"
                )
                return
            if task.status == TaskStatus.cancelled:
                await update.message.reply_text(
                    DONE_ALREADY_CANCELLED.format(task_id=task_id), parse_mode="HTML"
                )
                return

            complete_task(db, task)
            title = task.title
            next_task = getattr(task, "next_occurrence", None)
            if next_task and next_task.due_at:
                next_due_str = format_dt_local(next_task.due_at, user.timezone)
                msg_text = DONE_SUCCESS_RECURRING.format(
                    title=html.escape(title),
                    next_due_display=next_due_str,
                )
            else:
                msg_text = DONE_SUCCESS.format(title=html.escape(title))

        await update.message.reply_text(
            msg_text,
            parse_mode="HTML",
            reply_markup=action_nav_keyboard(),
        )
        return

    # Case 2: no arguments — show pending tasks as inline buttons
    with get_db() as db:
        user = get_or_create_user(db, tg_user.id, tg_user.username, tg_user.first_name)
        pending = get_pending_tasks(db, user)
        tz = user.timezone

    if not pending:
        await update.message.reply_text(
            DONE_NO_PENDING, parse_mode="HTML", reply_markup=action_nav_keyboard()
        )
        return

    await update.message.reply_text(
        DONE_SELECT_TASK,
        parse_mode="HTML",
        reply_markup=task_selection_keyboard(pending, "done:select", CB_DONE_CANCEL, tz),
    )


async def done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle done:select:<id> and done:cancel callbacks."""
    query = update.callback_query
    await query.answer()
    tg_user = update.effective_user
    if tg_user is None:
        return

    if query.data == CB_DONE_CANCEL:
        await query.edit_message_text(DONE_CANCELLED)
        return

    task_id_str = query.data.split(":")[2]
    task_id = int(task_id_str)

    with get_db() as db:
        user = get_or_create_user(db, tg_user.id, tg_user.username, tg_user.first_name)
        task = get_task_by_id(db, task_id, user.id)
        if task is None or task.status != TaskStatus.pending:
            await query.edit_message_text(
                DONE_ALREADY_COMPLETED.format(task_id=task_id), parse_mode="HTML"
            )
            return

        complete_task(db, task)
        title = task.title
        next_task = getattr(task, "next_occurrence", None)
        if next_task and next_task.due_at:
            next_due_str = format_dt_local(next_task.due_at, user.timezone)
            msg_text = DONE_SUCCESS_RECURRING.format(
                title=html.escape(title),
                next_due_display=next_due_str,
            )
        else:
            msg_text = DONE_SUCCESS.format(title=html.escape(title))

    await query.edit_message_text(
        msg_text,
        parse_mode="HTML",
        reply_markup=action_nav_keyboard(),
    )


# --- /delete handlers ---

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete [task_id]."""
    tg_user = update.effective_user
    if tg_user is None:
        return

    # Case 1: argument provided e.g. /delete 5
    if context.args and context.args[0].isdigit():
        task_id = int(context.args[0])
        with get_db() as db:
            user = get_or_create_user(db, tg_user.id, tg_user.username, tg_user.first_name)
            task = get_task_by_id(db, task_id, user.id)
            if task is None or task.status == TaskStatus.cancelled:
                await update.message.reply_text(
                    DELETE_NOT_FOUND.format(task_id=task_id), parse_mode="HTML"
                )
                return

            due_display = format_dt_local(task.due_at, user.timezone) if task.due_at else "No reminder"
            title = task.title

        await update.message.reply_text(
            DELETE_CONFIRM.format(
                task_id=task_id,
                title=html.escape(title),
                due_display=due_display,
            ),
            parse_mode="HTML",
            reply_markup=confirm_delete_keyboard(task_id),
        )
        return

    # Case 2: no arguments — list user's pending tasks
    with get_db() as db:
        user = get_or_create_user(db, tg_user.id, tg_user.username, tg_user.first_name)
        tasks = get_pending_tasks(db, user)
        tz = user.timezone

    if not tasks:
        await update.message.reply_text(
            DELETE_NO_TASKS, parse_mode="HTML", reply_markup=action_nav_keyboard()
        )
        return

    await update.message.reply_text(
        DELETE_SELECT_TASK,
        parse_mode="HTML",
        reply_markup=task_selection_keyboard(tasks, "delete:ask", CB_DELETE_CANCEL, tz),
    )


async def delete_ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show delete confirmation after selecting task from list."""
    query = update.callback_query
    await query.answer()
    tg_user = update.effective_user
    if tg_user is None:
        return

    task_id = int(query.data.split(":")[2])
    with get_db() as db:
        user = get_or_create_user(db, tg_user.id, tg_user.username, tg_user.first_name)
        task = get_task_by_id(db, task_id, user.id)
        if task is None or task.status == TaskStatus.cancelled:
            await query.edit_message_text(
                DELETE_NOT_FOUND.format(task_id=task_id), parse_mode="HTML"
            )
            return

        due_display = format_dt_local(task.due_at, user.timezone) if task.due_at else "No reminder"
        title = task.title

    await query.edit_message_text(
        DELETE_CONFIRM.format(
            task_id=task_id,
            title=html.escape(title),
            due_display=due_display,
        ),
        parse_mode="HTML",
        reply_markup=confirm_delete_keyboard(task_id),
    )


async def delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle actual deletion upon confirmation."""
    query = update.callback_query
    await query.answer()
    tg_user = update.effective_user
    if tg_user is None:
        return

    if query.data == CB_DELETE_CANCEL:
        await query.edit_message_text(DELETE_CANCELLED)
        return

    task_id = int(query.data.split(":")[2])
    with get_db() as db:
        user = get_or_create_user(db, tg_user.id, tg_user.username, tg_user.first_name)
        task = get_task_by_id(db, task_id, user.id)
        if task is None or task.status == TaskStatus.cancelled:
            await query.edit_message_text(
                DELETE_NOT_FOUND.format(task_id=task_id), parse_mode="HTML"
            )
            return

        delete_task(db, task)
        title = task.title

    await query.edit_message_text(
        DELETE_SUCCESS.format(task_id=task_id, title=html.escape(title)),
        parse_mode="HTML",
        reply_markup=action_nav_keyboard(),
    )


# --- /edit ConversationHandler handlers ---

async def edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /edit [task_id]."""
    tg_user = update.effective_user
    if tg_user is None:
        return ConversationHandler.END

    _clear_edit_state(context)

    # Case 1: user passed argument e.g. /edit 5
    if context.args and context.args[0].isdigit():
        task_id = int(context.args[0])
        with get_db() as db:
            user = get_or_create_user(db, tg_user.id, tg_user.username, tg_user.first_name)
            task = get_task_by_id(db, task_id, user.id)
            if task is None:
                await update.message.reply_text(
                    EDIT_NOT_FOUND.format(task_id=task_id), parse_mode="HTML"
                )
                return ConversationHandler.END
            if task.status == TaskStatus.cancelled:
                await update.message.reply_text(
                    "❌ Cannot edit a cancelled task."
                )
                return ConversationHandler.END

            context.user_data[UD_EDIT_TASK_ID] = task.id
            context.user_data[UD_EDIT_ORIG_TITLE] = task.title
            context.user_data[UD_EDIT_ORIG_DUE] = task.due_at
            context.user_data[UD_EDIT_ORIG_PRIORITY] = task.priority
            context.user_data[UD_EDIT_ORIG_RECURRENCE] = task.recurrence
            context.user_data[UD_EDIT_TIMEZONE] = user.timezone

            due_display = format_dt_local(task.due_at, user.timezone) if task.due_at else "No reminder"
            p_icon = PRIORITY_ICONS.get(task.priority.value, "⚪")
            rec_label = RECURRENCE_LABELS.get(task.recurrence, "None (one-time)")

        await update.message.reply_text(
            EDIT_MENU.format(
                task_id=task.id,
                title=html.escape(task.title),
                due_display=due_display,
                priority_icon=p_icon,
                priority_label=task.priority.value.capitalize(),
                recurrence_label=rec_label,
            ),
            parse_mode="HTML",
            reply_markup=edit_fields_keyboard(),
        )
        return STATE_EDIT_CHOOSE_FIELD

    # Case 2: no arguments — list pending tasks
    with get_db() as db:
        user = get_or_create_user(db, tg_user.id, tg_user.username, tg_user.first_name)
        tasks = get_pending_tasks(db, user)
        tz = user.timezone

    if not tasks:
        await update.message.reply_text(
            EDIT_NO_TASKS, parse_mode="HTML", reply_markup=action_nav_keyboard()
        )
        return ConversationHandler.END

    context.user_data[UD_EDIT_TIMEZONE] = tz
    await update.message.reply_text(
        EDIT_SELECT_TASK,
        parse_mode="HTML",
        reply_markup=task_selection_keyboard(tasks, "edit:select", CB_EDIT_CANCEL, tz),
    )
    return STATE_EDIT_SELECT_TASK


async def edit_select_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Load selected task and show edit field options."""
    query = update.callback_query
    await query.answer()
    tg_user = update.effective_user
    if tg_user is None:
        _clear_edit_state(context)
        return ConversationHandler.END

    task_id = int(query.data.split(":")[2])
    with get_db() as db:
        user = get_or_create_user(db, tg_user.id, tg_user.username, tg_user.first_name)
        task = get_task_by_id(db, task_id, user.id)
        if task is None or task.status == TaskStatus.cancelled:
            await query.edit_message_text(
                EDIT_NOT_FOUND.format(task_id=task_id), parse_mode="HTML"
            )
            _clear_edit_state(context)
            return ConversationHandler.END

        context.user_data[UD_EDIT_TASK_ID] = task.id
        context.user_data[UD_EDIT_ORIG_TITLE] = task.title
        context.user_data[UD_EDIT_ORIG_DUE] = task.due_at
        context.user_data[UD_EDIT_ORIG_PRIORITY] = task.priority
        context.user_data[UD_EDIT_ORIG_RECURRENCE] = task.recurrence
        context.user_data[UD_EDIT_TIMEZONE] = user.timezone

        due_display = format_dt_local(task.due_at, user.timezone) if task.due_at else "No reminder"
        p_icon = PRIORITY_ICONS.get(task.priority.value, "⚪")
        rec_label = RECURRENCE_LABELS.get(task.recurrence, "None (one-time)")

    await query.edit_message_text(
        EDIT_MENU.format(
            task_id=task.id,
            title=html.escape(task.title),
            due_display=due_display,
            priority_icon=p_icon,
            priority_label=task.priority.value.capitalize(),
            recurrence_label=rec_label,
        ),
        parse_mode="HTML",
        reply_markup=edit_fields_keyboard(),
    )
    return STATE_EDIT_CHOOSE_FIELD


async def edit_choose_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt user for new value depending on the chosen field."""
    query = update.callback_query
    await query.answer()
    data = query.data
    tz = context.user_data[UD_EDIT_TIMEZONE]
    due_at = context.user_data[UD_EDIT_ORIG_DUE]

    if data == CB_EDIT_FIELD_TITLE:
        current_title = context.user_data[UD_EDIT_ORIG_TITLE]
        await query.edit_message_text(
            EDIT_ASK_TITLE.format(current_title=html.escape(current_title)),
            parse_mode="HTML",
        )
        return STATE_EDIT_INPUT_TITLE

    elif data == CB_EDIT_FIELD_DATE:
        current_date_str = format_date_only(due_at, tz) if due_at else "None"
        await query.edit_message_text(
            EDIT_ASK_DATE.format(current_date=current_date_str),
            parse_mode="HTML",
        )
        return STATE_EDIT_INPUT_DATE

    elif data == CB_EDIT_FIELD_TIME:
        current_time_str = format_time_only(due_at, tz) if due_at else "None"
        await query.edit_message_text(
            EDIT_ASK_TIME.format(current_time=current_time_str),
            parse_mode="HTML",
        )
        return STATE_EDIT_INPUT_TIME

    elif data == CB_EDIT_FIELD_PRIORITY:
        priority = context.user_data[UD_EDIT_ORIG_PRIORITY]
        p_icon = PRIORITY_ICONS.get(priority.value, "⚪")
        await query.edit_message_text(
            EDIT_ASK_PRIORITY.format(
                priority_icon=p_icon,
                priority_label=priority.value.capitalize(),
            ),
            parse_mode="HTML",
            reply_markup=priority_keyboard(),
        )
        return STATE_EDIT_INPUT_PRIORITY

    elif data == CB_EDIT_FIELD_RECURRENCE:
        current_rec = context.user_data.get(UD_EDIT_ORIG_RECURRENCE)
        current_rec_label = RECURRENCE_LABELS.get(current_rec, "None (one-time)")
        await query.edit_message_text(
            EDIT_ASK_RECURRENCE.format(current_recurrence=current_rec_label),
            parse_mode="HTML",
            reply_markup=recurrence_keyboard(),
        )
        return STATE_EDIT_INPUT_RECURRENCE

    elif data == CB_EDIT_CANCEL:
        _clear_edit_state(context)
        await query.edit_message_text(EDIT_CANCELLED)
        return ConversationHandler.END

    return STATE_EDIT_CHOOSE_FIELD


async def receive_edit_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate new title and show confirmation summary."""
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text(ERR_TITLE_EMPTY, parse_mode="HTML")
        return STATE_EDIT_INPUT_TITLE
    if len(title) > 500:
        await update.message.reply_text(
            ERR_TITLE_TOO_LONG.format(length=len(title), max_length=500),
            parse_mode="HTML",
        )
        return STATE_EDIT_INPUT_TITLE

    context.user_data[UD_EDIT_NEW_TITLE] = title
    confirm_text = _render_edit_confirm_text(context)
    await update.message.reply_text(
        confirm_text,
        parse_mode="HTML",
        reply_markup=confirm_edit_keyboard(),
    )
    return STATE_EDIT_CONFIRM


async def receive_edit_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate new date, combine with existing time, and show confirmation summary."""
    text = update.message.text.strip()
    parsed_date = parse_date(text)
    tz = context.user_data[UD_EDIT_TIMEZONE]

    if parsed_date is None:
        await update.message.reply_text(
            ERR_INVALID_DATE.format(example_date=example_date_string(tz)),
            parse_mode="HTML",
        )
        return STATE_EDIT_INPUT_DATE

    orig_due = context.user_data[UD_EDIT_ORIG_DUE]
    if orig_due:
        existing_time = get_local_date_and_time(orig_due, tz)[1]
    else:
        existing_time = time(9, 0)  # default morning time

    combined_utc = combine_to_utc(parsed_date, existing_time, tz)
    if is_in_past(combined_utc):
        await update.message.reply_text(
            ERR_DATETIME_IN_PAST.format(current_time=current_time_display(tz)),
            parse_mode="HTML",
        )
        return STATE_EDIT_INPUT_DATE

    context.user_data[UD_EDIT_NEW_DUE] = combined_utc
    confirm_text = _render_edit_confirm_text(context)
    await update.message.reply_text(
        confirm_text,
        parse_mode="HTML",
        reply_markup=confirm_edit_keyboard(),
    )
    return STATE_EDIT_CONFIRM


async def receive_edit_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate new time, combine with existing date, and show confirmation summary."""
    text = update.message.text.strip()
    parsed_time = parse_time(text)
    tz = context.user_data[UD_EDIT_TIMEZONE]

    if parsed_time is None:
        await update.message.reply_text(ERR_INVALID_TIME, parse_mode="HTML")
        return STATE_EDIT_INPUT_TIME

    orig_due = context.user_data[UD_EDIT_ORIG_DUE]
    if orig_due:
        existing_date = get_local_date_and_time(orig_due, tz)[0]
    else:
        import pytz
        existing_date = datetime.now(pytz.timezone(tz)).date()

    combined_utc = combine_to_utc(existing_date, parsed_time, tz)
    if is_in_past(combined_utc):
        await update.message.reply_text(
            ERR_DATETIME_IN_PAST.format(current_time=current_time_display(tz)),
            parse_mode="HTML",
        )
        return STATE_EDIT_INPUT_TIME

    context.user_data[UD_EDIT_NEW_DUE] = combined_utc
    confirm_text = _render_edit_confirm_text(context)
    await update.message.reply_text(
        confirm_text,
        parse_mode="HTML",
        reply_markup=confirm_edit_keyboard(),
    )
    return STATE_EDIT_CONFIRM


async def receive_edit_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive new priority and show confirmation summary."""
    query = update.callback_query
    await query.answer()

    priority = _PRIORITY_MAP.get(query.data)
    if priority is None:
        await query.message.reply_text(ERR_USE_BUTTONS)
        return STATE_EDIT_INPUT_PRIORITY

    context.user_data[UD_EDIT_NEW_PRIORITY] = priority
    confirm_text = _render_edit_confirm_text(context)
    await query.edit_message_text(
        confirm_text,
        parse_mode="HTML",
        reply_markup=confirm_edit_keyboard(),
    )
    return STATE_EDIT_CONFIRM


async def receive_edit_recurrence(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive new recurrence schedule and show confirmation summary."""
    query = update.callback_query
    await query.answer()

    if query.data not in _RECURRENCE_MAP:
        await query.message.reply_text(ERR_USE_BUTTONS)
        return STATE_EDIT_INPUT_RECURRENCE

    recurrence_val = _RECURRENCE_MAP[query.data]
    context.user_data[UD_EDIT_NEW_RECURRENCE] = recurrence_val
    confirm_text = _render_edit_confirm_text(context)
    await query.edit_message_text(
        confirm_text,
        parse_mode="HTML",
        reply_markup=confirm_edit_keyboard(),
    )
    return STATE_EDIT_CONFIRM


async def receive_edit_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save changes to the database or cancel edit."""
    query = update.callback_query
    await query.answer()

    if query.data == CB_EDIT_CANCEL:
        _clear_edit_state(context)
        await query.edit_message_text(EDIT_CANCELLED)
        return ConversationHandler.END

    if query.data != CB_EDIT_SAVE:
        return STATE_EDIT_CONFIRM

    tg_user = update.effective_user
    if tg_user is None:
        _clear_edit_state(context)
        return ConversationHandler.END

    task_id = context.user_data[UD_EDIT_TASK_ID]
    tz = context.user_data[UD_EDIT_TIMEZONE]
    new_title = context.user_data.get(UD_EDIT_NEW_TITLE)
    new_due = context.user_data.get(UD_EDIT_NEW_DUE)
    new_priority = context.user_data.get(UD_EDIT_NEW_PRIORITY)
    new_recurrence = (
        context.user_data[UD_EDIT_NEW_RECURRENCE]
        if UD_EDIT_NEW_RECURRENCE in context.user_data
        else _UNSET
    )

    with get_db() as db:
        user = get_or_create_user(db, tg_user.id, tg_user.username, tg_user.first_name)
        task = get_task_by_id(db, task_id, user.id)
        if task is None:
            await query.edit_message_text(EDIT_NOT_FOUND.format(task_id=task_id), parse_mode="HTML")
            _clear_edit_state(context)
            return ConversationHandler.END

        edit_task(
            db=db,
            task=task,
            title=new_title,
            due_at_utc=new_due,
            priority=new_priority,
            recurrence=new_recurrence,
        )
        final_title = task.title
        final_due_str = format_dt_local(task.due_at, tz) if task.due_at else "No reminder"
        p_icon = PRIORITY_ICONS.get(task.priority.value, "⚪")
        p_label = task.priority.value.capitalize()
        rec_label = RECURRENCE_LABELS.get(task.recurrence, "None (one-time)")

    _clear_edit_state(context)
    await query.edit_message_text(
        EDIT_SUCCESS.format(
            task_id=task_id,
            title=html.escape(final_title),
            due_display=final_due_str,
            priority_icon=p_icon,
            priority_label=p_label,
            recurrence_label=rec_label,
        ),
        parse_mode="HTML",
        reply_markup=action_nav_keyboard(),
    )
    return ConversationHandler.END


async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fallback /cancel for editing."""
    _clear_edit_state(context)
    await update.message.reply_text(EDIT_CANCELLED)
    return ConversationHandler.END


# Assembly of /edit ConversationHandler
_edit_conversation = ConversationHandler(
    entry_points=[CommandHandler("edit", edit_start)],
    states={
        STATE_EDIT_SELECT_TASK: [
            CallbackQueryHandler(edit_select_task_callback, pattern=r"^edit:select:\d+$"),
            CallbackQueryHandler(edit_choose_field_callback, pattern=f"^{CB_EDIT_CANCEL}$"),
        ],
        STATE_EDIT_CHOOSE_FIELD: [
            CallbackQueryHandler(edit_choose_field_callback, pattern=r"^edit:(field:|cancel)"),
        ],
        STATE_EDIT_INPUT_TITLE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_title),
        ],
        STATE_EDIT_INPUT_DATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_date),
        ],
        STATE_EDIT_INPUT_TIME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_time),
        ],
        STATE_EDIT_INPUT_PRIORITY: [
            CallbackQueryHandler(receive_edit_priority, pattern="^priority:"),
        ],
        STATE_EDIT_INPUT_RECURRENCE: [
            CallbackQueryHandler(receive_edit_recurrence, pattern="^rec:"),
        ],
        STATE_EDIT_CONFIRM: [
            CallbackQueryHandler(receive_edit_confirmation, pattern=r"^edit:(save|cancel)$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_edit),
    ],
    allow_reentry=True,
    per_chat=True,
    per_user=True,
    per_message=False,
)


# ---------------------------------------------------------------------------
# Snooze Callback Handler
# ---------------------------------------------------------------------------

async def snooze_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle inline snooze button click from reminder notifications.
    Pattern: snooze:<task_id>:<snooze_type>
    """
    query = update.callback_query
    await query.answer()
    tg_user = update.effective_user
    if tg_user is None:
        return

    parts = query.data.split(":")
    task_id = int(parts[1])
    snooze_type = parts[2]

    with get_db() as db:
        user = get_or_create_user(db, tg_user.id, tg_user.username, tg_user.first_name)
        task = get_task_by_id(db, task_id, user.id)

        if task is None:
            await query.edit_message_text(
                SNOOZE_NOT_FOUND.format(task_id=task_id), parse_mode="HTML"
            )
            return

        if task.status == TaskStatus.completed:
            await query.edit_message_text(
                SNOOZE_ALREADY_COMPLETED.format(task_id=task_id), parse_mode="HTML"
            )
            return

        if task.status == TaskStatus.cancelled:
            await query.edit_message_text(
                SNOOZE_ALREADY_CANCELLED.format(task_id=task_id), parse_mode="HTML"
            )
            return

        now_utc = datetime.now(timezone.utc)
        new_due_utc = calculate_snooze_datetime(
            current_utc=now_utc,
            snooze_type=snooze_type,
            tz_string=user.timezone,
            original_due_utc=task.due_at,
        )

        snooze_task(db, task, new_due_utc)
        new_due_str = format_dt_local(new_due_utc, user.timezone)
        title = task.title

    await query.edit_message_text(
        SNOOZE_SUCCESS.format(
            title=html.escape(title),
            due_display=new_due_str,
        ),
        parse_mode="HTML",
        reply_markup=action_nav_keyboard(),
    )
    logger.info("Task %s snoozed for %s by user %s", task_id, snooze_type, tg_user.id)


# ---------------------------------------------------------------------------
# Exported handler list — consumed by main.py
# ---------------------------------------------------------------------------

handlers = [
    _add_conversation,
    _edit_conversation,
    CommandHandler("today", today_command),
    CommandHandler("upcoming", upcoming_command),
    CommandHandler("done", done_command),
    CommandHandler("delete", delete_command),
    CallbackQueryHandler(today_callback, pattern=f"^({CB_TODAY_REFRESH}|{CB_VIEW_TODAY})$"),
    CallbackQueryHandler(upcoming_callback, pattern=f"^({CB_UPCOMING_REFRESH}|{CB_VIEW_UPCOMING})$"),
    CallbackQueryHandler(done_callback, pattern=r"^(done:select:\d+|done:cancel)$"),
    CallbackQueryHandler(snooze_callback, pattern=r"^snooze:\d+:(10m|30m|1h|tomorrow)$"),
    CallbackQueryHandler(delete_ask_callback, pattern=r"^delete:ask:\d+$"),
    CallbackQueryHandler(delete_confirm_callback, pattern=r"^(delete:confirm:\d+|delete:cancel)$"),
]
