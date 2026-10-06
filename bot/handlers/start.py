"""
handlers/start.py — Handlers for /start, /help, and /cancel.

Design:
  • Each async function is a single-responsibility handler.
  • Calls user_service to upsert the user record on /start.
  • No business logic here — only Telegram I/O + service delegation.
  • Exported as `handlers` list for clean registration in main.py.
"""

import logging

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from bot.database.database import get_db
from bot.services.user_service import get_or_create_user
from bot.utils.messages import (
    CANCEL_MESSAGE,
    HELP_MESSAGE,
    UNKNOWN_COMMAND_MESSAGE,
    WELCOME_MESSAGE,
)

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /start.

    Creates the user record on first run, or silently updates their profile.
    Replies with the welcome message.
    """
    tg_user = update.effective_user
    if tg_user is None:
        return  # Safety guard — effective_user is None for channel posts

    logger.info(
        "/start called by telegram_user_id=%s username=%s",
        tg_user.id,
        tg_user.username,
    )

    # Upsert user record — safe to call every time
    with get_db() as db:
        get_or_create_user(
            db=db,
            telegram_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )

    await update.message.reply_text(
        WELCOME_MESSAGE.format(first_name=tg_user.first_name or "there"),
        parse_mode="HTML",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — send the command reference."""
    logger.debug("/help called by %s", update.effective_user.id if update.effective_user else "unknown")
    await update.message.reply_text(HELP_MESSAGE, parse_mode="HTML")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /cancel — terminates any active ConversationHandler state.

    In Phase 1 there are no ConversationHandlers yet, so this simply
    sends a friendly message. From Phase 2 onward, ConversationHandlers
    will register /cancel as their fallback.
    """
    logger.debug(
        "/cancel called by %s", update.effective_user.id if update.effective_user else "unknown"
    )
    await update.message.reply_text(CANCEL_MESSAGE)


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch-all for unrecognised commands."""
    await update.message.reply_text(UNKNOWN_COMMAND_MESSAGE)


# ---------------------------------------------------------------------------
# Exported handler list — imported and registered in main.py
# ---------------------------------------------------------------------------
handlers = [
    CommandHandler("start", start_command),
    CommandHandler("help", help_command),
    CommandHandler("cancel", cancel_command),
]
