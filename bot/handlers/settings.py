"""
handlers/settings.py — /settings and /summary handlers for Phase 7.

Responsibilities:
  • /settings: Display user settings dashboard with live toggles and schedule buttons.
  • /summary: Display formatted daily task summary for the user's current local date.
  • Settings callback handling:
      - Toggle task reminders (ON/OFF).
      - Toggle daily summaries (ON/OFF).
      - Quick-pick timezone selection and custom IANA timezone conversation flow.
      - Quick-pick summary delivery time selection and custom 24-hour time conversation flow.
      - Dashboard refresh and back-to-dashboard navigation.
  • Summary callback handling:
      - Refresh daily summary.
      - Quick-link to view today's tasks (/today view).
"""

import html
import logging
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

from bot.database.database import get_db
from bot.services.task_service import get_daily_summary, get_today_tasks
from bot.services.user_service import (
    get_or_create_user,
    get_user_settings,
    update_daily_summary_enabled,
    update_daily_summary_time,
    update_reminders_enabled,
    update_timezone,
)
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
    settings_keyboard,
    summary_keyboard,
    summary_time_keyboard,
    timezone_keyboard,
    today_keyboard,
)
from bot.utils.messages import (
    SUMMARY_TIME_SELECTION_PROMPT,
    TIMEZONE_SELECTION_PROMPT,
    format_daily_summary_message,
    format_settings_message,
)

logger = logging.getLogger(__name__)

# ConversationHandler states for custom settings entry
STATE_CUSTOM_TIMEZONE = 1
STATE_CUSTOM_TIME = 2


# ---------------------------------------------------------------------------
# /settings Command Handler
# ---------------------------------------------------------------------------

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /settings command — display user settings dashboard with interactive buttons.
    """
    tg_user = update.effective_user
    if tg_user is None or update.message is None:
        return

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        settings = get_user_settings(user)

    msg_text = format_settings_message(settings)
    kb = settings_keyboard(
        reminders_enabled=settings.reminders_enabled,
        daily_summary_enabled=settings.daily_summary_enabled,
    )
    await update.message.reply_text(msg_text, parse_mode="HTML", reply_markup=kb)
    logger.info("Settings dashboard displayed for user telegram_id=%d", tg_user.id)


# ---------------------------------------------------------------------------
# Settings Callback Handlers
# ---------------------------------------------------------------------------

async def settings_toggle_reminders_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Toggle task reminders ON / OFF."""
    query = update.callback_query
    if query is None:
        return

    tg_user = update.effective_user
    if tg_user is None:
        await query.answer()
        return

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        new_val = not user.reminders_enabled
        update_reminders_enabled(db, user, new_val)
        settings = get_user_settings(user)

    status_word = "enabled" if new_val else "disabled"
    await query.answer(f"Reminders {status_word}.")
    await query.edit_message_text(
        format_settings_message(settings),
        parse_mode="HTML",
        reply_markup=settings_keyboard(
            reminders_enabled=settings.reminders_enabled,
            daily_summary_enabled=settings.daily_summary_enabled,
        ),
    )
    logger.info("User telegram_id=%d toggled reminders to %s", tg_user.id, new_val)


async def settings_toggle_summary_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Toggle daily summary notifications ON / OFF."""
    query = update.callback_query
    if query is None:
        return

    tg_user = update.effective_user
    if tg_user is None:
        await query.answer()
        return

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        new_val = not user.daily_summary_enabled
        update_daily_summary_enabled(db, user, new_val)
        settings = get_user_settings(user)

    status_word = "enabled" if new_val else "disabled"
    await query.answer(f"Daily summary {status_word}.")
    await query.edit_message_text(
        format_settings_message(settings),
        parse_mode="HTML",
        reply_markup=settings_keyboard(
            reminders_enabled=settings.reminders_enabled,
            daily_summary_enabled=settings.daily_summary_enabled,
        ),
    )
    logger.info("User telegram_id=%d toggled daily summary to %s", tg_user.id, new_val)


async def settings_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle menu navigation callbacks:
      • Change timezone menu
      • Change summary time menu
      • Refresh dashboard
      • Back to dashboard
    """
    query = update.callback_query
    if query is None or query.data is None:
        return

    tg_user = update.effective_user
    if tg_user is None:
        await query.answer()
        return

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        settings = get_user_settings(user)

    if query.data == CB_SETTINGS_CHANGE_TZ:
        await query.answer()
        prompt = TIMEZONE_SELECTION_PROMPT.format(current_timezone=settings.timezone)
        await query.edit_message_text(
            prompt,
            parse_mode="HTML",
            reply_markup=timezone_keyboard(current_timezone=settings.timezone),
        )

    elif query.data == CB_SETTINGS_CHANGE_TIME:
        await query.answer()
        prompt = SUMMARY_TIME_SELECTION_PROMPT.format(current_time=settings.daily_summary_time)
        await query.edit_message_text(
            prompt,
            parse_mode="HTML",
            reply_markup=summary_time_keyboard(current_time=settings.daily_summary_time),
        )

    elif query.data in (CB_SETTINGS_REFRESH, CB_SETTINGS_BACK):
        if query.data == CB_SETTINGS_REFRESH:
            await query.answer("Settings refreshed.")
        else:
            await query.answer()

        await query.edit_message_text(
            format_settings_message(settings),
            parse_mode="HTML",
            reply_markup=settings_keyboard(
                reminders_enabled=settings.reminders_enabled,
                daily_summary_enabled=settings.daily_summary_enabled,
            ),
        )


async def timezone_quick_pick_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle quick-pick timezone selection button tap."""
    query = update.callback_query
    if query is None or not query.data or not query.data.startswith(CB_TZ_SET_PREFIX):
        return

    tg_user = update.effective_user
    if tg_user is None:
        await query.answer()
        return

    tz_string = query.data[len(CB_TZ_SET_PREFIX):]

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        try:
            update_timezone(db, user, tz_string)
            settings = get_user_settings(user)
        except ValueError as exc:
            await query.answer(f"Error: {exc}", show_alert=True)
            return

    await query.answer(f"Timezone updated to {tz_string}.")
    await query.edit_message_text(
        format_settings_message(settings),
        parse_mode="HTML",
        reply_markup=settings_keyboard(
            reminders_enabled=settings.reminders_enabled,
            daily_summary_enabled=settings.daily_summary_enabled,
        ),
    )
    logger.info("User telegram_id=%d updated timezone to %s", tg_user.id, tz_string)


async def summary_time_quick_pick_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle quick-pick summary time selection button tap."""
    query = update.callback_query
    if query is None or not query.data or not query.data.startswith(CB_TIME_SET_PREFIX):
        return

    tg_user = update.effective_user
    if tg_user is None:
        await query.answer()
        return

    time_string = query.data[len(CB_TIME_SET_PREFIX):]

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        try:
            update_daily_summary_time(db, user, time_string)
            settings = get_user_settings(user)
        except ValueError as exc:
            await query.answer(f"Error: {exc}", show_alert=True)
            return

    await query.answer(f"Summary time set to {time_string}.")
    await query.edit_message_text(
        format_settings_message(settings),
        parse_mode="HTML",
        reply_markup=settings_keyboard(
            reminders_enabled=settings.reminders_enabled,
            daily_summary_enabled=settings.daily_summary_enabled,
        ),
    )
    logger.info("User telegram_id=%d updated summary time to %s", tg_user.id, time_string)


# ---------------------------------------------------------------------------
# Custom Timezone Conversation Flow
# ---------------------------------------------------------------------------

async def start_custom_timezone(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Prompt user to type their custom IANA timezone string."""
    query = update.callback_query
    if query is None:
        return ConversationHandler.END

    await query.answer()
    prompt = (
        "✏️ <b>Enter Custom Timezone</b>\n\n"
        "Please send your IANA timezone name (e.g. <code>Asia/Singapore</code>, "
        "<code>America/Chicago</code>, <code>Europe/Berlin</code>).\n\n"
        "<i>Type /cancel to abort and return to settings.</i>"
    )
    await query.edit_message_text(prompt, parse_mode="HTML")
    return STATE_CUSTOM_TIMEZONE


async def receive_custom_timezone(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Validate user-entered timezone and update user record."""
    tg_user = update.effective_user
    if tg_user is None or not update.message or not update.message.text:
        return STATE_CUSTOM_TIMEZONE

    tz_input = update.message.text.strip()

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        try:
            update_timezone(db, user, tz_input)
            settings = get_user_settings(user)
        except ValueError:
            await update.message.reply_text(
                f"❌ <b>Invalid timezone:</b> '<code>{html.escape(tz_input)}</code>'.\n\n"
                "Please enter a valid IANA timezone name (e.g. <code>Asia/Kolkata</code>, <code>UTC</code>, "
                "<code>America/New_York</code>), or /cancel to abort:",
                parse_mode="HTML",
            )
            return STATE_CUSTOM_TIMEZONE

    success_text = (
        f"✅ <b>Timezone updated to:</b> <code>{html.escape(tz_input)}</code>\n\n"
        + format_settings_message(settings)
    )
    await update.message.reply_text(
        success_text,
        parse_mode="HTML",
        reply_markup=settings_keyboard(
            reminders_enabled=settings.reminders_enabled,
            daily_summary_enabled=settings.daily_summary_enabled,
        ),
    )
    logger.info("User telegram_id=%d custom-set timezone to %s", tg_user.id, tz_input)
    return ConversationHandler.END


async def cancel_custom_timezone(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Cancel custom timezone entry and show settings dashboard."""
    tg_user = update.effective_user
    if tg_user is None or not update.message:
        return ConversationHandler.END

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        settings = get_user_settings(user)

    msg = "❌ Timezone change cancelled.\n\n" + format_settings_message(settings)
    await update.message.reply_text(
        msg,
        parse_mode="HTML",
        reply_markup=settings_keyboard(
            reminders_enabled=settings.reminders_enabled,
            daily_summary_enabled=settings.daily_summary_enabled,
        ),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Custom Summary Time Conversation Flow
# ---------------------------------------------------------------------------

async def start_custom_time(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Prompt user to type their custom 24-hour summary time."""
    query = update.callback_query
    if query is None:
        return ConversationHandler.END

    await query.answer()
    prompt = (
        "⏰ <b>Enter Custom Summary Time</b>\n\n"
        "Please send your preferred delivery time in 24-hour format (<code>HH:MM</code>, "
        "e.g. <code>08:30</code>, <code>19:00</code>).\n\n"
        "<i>Type /cancel to abort and return to settings.</i>"
    )
    await query.edit_message_text(prompt, parse_mode="HTML")
    return STATE_CUSTOM_TIME


async def receive_custom_time(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Validate user-entered summary time and update user record."""
    tg_user = update.effective_user
    if tg_user is None or not update.message or not update.message.text:
        return STATE_CUSTOM_TIME

    time_input = update.message.text.strip()

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        try:
            update_daily_summary_time(db, user, time_input)
            settings = get_user_settings(user)
        except ValueError:
            await update.message.reply_text(
                f"❌ <b>Invalid time format:</b> '<code>{html.escape(time_input)}</code>'.\n\n"
                "Please enter a valid 24-hour time in <code>HH:MM</code> format (between <code>00:00</code> and "
                "<code>23:59</code>), or /cancel to abort:",
                parse_mode="HTML",
            )
            return STATE_CUSTOM_TIME

    success_text = (
        f"✅ <b>Daily summary time updated to:</b> <code>{html.escape(time_input)}</code>\n\n"
        + format_settings_message(settings)
    )
    await update.message.reply_text(
        success_text,
        parse_mode="HTML",
        reply_markup=settings_keyboard(
            reminders_enabled=settings.reminders_enabled,
            daily_summary_enabled=settings.daily_summary_enabled,
        ),
    )
    logger.info("User telegram_id=%d custom-set summary time to %s", tg_user.id, time_input)
    return ConversationHandler.END


async def cancel_custom_time(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Cancel custom time entry and show settings dashboard."""
    tg_user = update.effective_user
    if tg_user is None or not update.message:
        return ConversationHandler.END

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        settings = get_user_settings(user)

    msg = "❌ Summary time change cancelled.\n\n" + format_settings_message(settings)
    await update.message.reply_text(
        msg,
        parse_mode="HTML",
        reply_markup=settings_keyboard(
            reminders_enabled=settings.reminders_enabled,
            daily_summary_enabled=settings.daily_summary_enabled,
        ),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /summary Command Handler
# ---------------------------------------------------------------------------

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /summary command — display formatted task summary for the current local date.
    """
    tg_user = update.effective_user
    if tg_user is None or update.message is None:
        return

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        summary = get_daily_summary(db=db, user=user)

    msg_text = format_daily_summary_message(summary)
    kb = summary_keyboard()
    await update.message.reply_text(msg_text, parse_mode="HTML", reply_markup=kb)
    logger.info("Daily summary displayed for user telegram_id=%d", tg_user.id)


# ---------------------------------------------------------------------------
# Summary Callback Handlers
# ---------------------------------------------------------------------------

async def summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle callbacks from /summary view:
      • summary:refresh -> Refresh summary for today
      • view:today -> Switch to today's task itinerary view
    """
    query = update.callback_query
    if query is None or query.data is None:
        return

    tg_user = update.effective_user
    if tg_user is None:
        await query.answer()
        return

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )

        if query.data == CB_SUMMARY_REFRESH:
            summary = get_daily_summary(db=db, user=user)
            await query.answer("Summary refreshed.")
            await query.edit_message_text(
                format_daily_summary_message(summary),
                parse_mode="HTML",
                reply_markup=summary_keyboard(),
            )
            logger.info("User telegram_id=%d refreshed summary", tg_user.id)

        elif query.data == CB_VIEW_TODAY:
            from bot.handlers.tasks import format_today_view
            tasks = get_today_tasks(db=db, user=user)
            await query.answer()
            await query.edit_message_text(
                format_today_view(tasks, user.timezone),
                parse_mode="HTML",
                reply_markup=today_keyboard(),
            )
            logger.info("User telegram_id=%d switched to /today from summary", tg_user.id)


# ---------------------------------------------------------------------------
# ConversationHandlers Definition
# ---------------------------------------------------------------------------

_custom_tz_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_custom_timezone, pattern=f"^{CB_TZ_CUSTOM}$"),
    ],
    states={
        STATE_CUSTOM_TIMEZONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_timezone),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_custom_timezone),
        CommandHandler("settings", cancel_custom_timezone),
    ],
    allow_reentry=True,
    per_chat=True,
    per_user=True,
    per_message=False,
)

_custom_time_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_custom_time, pattern=f"^{CB_TIME_CUSTOM}$"),
    ],
    states={
        STATE_CUSTOM_TIME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_time),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_custom_time),
        CommandHandler("settings", cancel_custom_time),
    ],
    allow_reentry=True,
    per_chat=True,
    per_user=True,
    per_message=False,
)


# ---------------------------------------------------------------------------
# Handlers Export List — consumed by main.py
# ---------------------------------------------------------------------------

handlers = [
    _custom_tz_conversation,
    _custom_time_conversation,
    CommandHandler("settings", settings_command),
    CommandHandler("summary", summary_command),
    CallbackQueryHandler(settings_toggle_reminders_callback, pattern=f"^{CB_SETTINGS_TOGGLE_REMINDERS}$"),
    CallbackQueryHandler(settings_toggle_summary_callback, pattern=f"^{CB_SETTINGS_TOGGLE_SUMMARY}$"),
    CallbackQueryHandler(settings_menu_callback, pattern=f"^({CB_SETTINGS_CHANGE_TZ}|{CB_SETTINGS_CHANGE_TIME}|{CB_SETTINGS_REFRESH}|{CB_SETTINGS_BACK})$"),
    CallbackQueryHandler(timezone_quick_pick_callback, pattern=f"^{CB_TZ_SET_PREFIX}(.+)$"),
    CallbackQueryHandler(summary_time_quick_pick_callback, pattern=f"^{CB_TIME_SET_PREFIX}([0-9]{{2}}:[0-9]{{2}})$"),
    CallbackQueryHandler(summary_callback, pattern=f"^({CB_SUMMARY_REFRESH}|{CB_VIEW_TODAY})$"),
]
