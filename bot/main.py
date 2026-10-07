"""
main.py — Application entry point.

Responsibilities:
  1. Configure structured logging.
  2. Validate critical settings (token present, webhook URL if webhook mode).
  3. Initialize the database (create tables for dev; use Alembic for prod).
  4. Build the python-telegram-bot Application.
  5. Register all handlers from each handler module.
  6. Register a global error handler.
  7. Start the bot in polling or webhook mode based on BOT_MODE env var.

Run with:
    python -m bot.main
"""

import asyncio
import logging
import sys
from typing import Optional

from telegram import Update
from telegram.ext import Application, MessageHandler, filters

from bot.config import settings
from bot.database.database import init_db
from bot.handlers.settings import handlers as settings_handlers
from bot.handlers.start import handlers as start_handlers, unknown_command
from bot.handlers.tasks import handlers as task_handlers
from bot.scheduler import create_scheduler, start_scheduler, stop_scheduler
from bot.services.reminder_service import process_due_reminders


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    """Configure root logger with a clean, timestamped format."""
    log_level = getattr(logging, settings.LOG_LEVEL, logging.INFO)

    logging.basicConfig(
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=log_level,
        stream=sys.stdout,
    )

    # Reduce noise from third-party libraries unless we're debugging
    if log_level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("apscheduler").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Global error handler
# ---------------------------------------------------------------------------

async def _error_handler(update: Optional[object], context) -> None:  # type: ignore[type-arg]
    """
    Log all unhandled exceptions raised inside handlers.

    Does NOT send the full traceback to the user — only a friendly message.
    The full error is available in the application logs.
    """
    logger = logging.getLogger(__name__)
    logger.error(
        "Unhandled exception while processing update.",
        exc_info=context.error,
    )

    # Attempt to notify the user if we have a valid message context
    if isinstance(update, Update) and update.effective_message:
        from bot.utils.messages import ERROR_UNEXPECTED
        try:
            await update.effective_message.reply_text(ERROR_UNEXPECTED)
        except Exception:
            pass  # If we can't even send the error message, just log and move on


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def _validate_settings() -> None:
    """
    Raise early with a clear error message if required settings are missing.
    Avoids cryptic errors later at runtime.
    """
    if not settings.TELEGRAM_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN == "your_bot_token_here":
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Copy .env.example to .env and fill in your bot token."
        )

    if settings.BOT_MODE == "webhook" and not settings.WEBHOOK_URL:
        raise ValueError(
            "BOT_MODE is set to 'webhook' but WEBHOOK_URL is empty. "
            "Set WEBHOOK_URL in your .env file or switch BOT_MODE to 'polling'."
        )


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
# Lifecycle hooks (Scheduler & Background Workers)
# ---------------------------------------------------------------------------

async def _on_startup(application: Application) -> None:
    """
    Application post_init lifecycle hook.

    Starts the background APScheduler instance and runs an immediate startup sweep
    for any tasks that came due while the bot was offline.
    """
    logger = logging.getLogger(__name__)
    logger.info("Initializing background reminder scheduler...")
    scheduler = create_scheduler(application.bot)
    start_scheduler(scheduler)
    application.bot_data["scheduler"] = scheduler
    logger.info(
        "Background scheduler started (polling interval=%ds).",
        settings.REMINDER_POLL_INTERVAL_SECONDS,
    )

    # Recovery sweep on startup for tasks due during downtime
    try:
        delivered = await process_due_reminders(application.bot)
        if delivered > 0:
            logger.info("Startup sweep: delivered %d overdue reminder(s).", delivered)
    except Exception as exc:
        logger.error("Error during startup reminder sweep: %s", exc, exc_info=True)


async def _on_shutdown(application: Application) -> None:
    """
    Application post_shutdown lifecycle hook.

    Cleanly shuts down the background scheduler.
    """
    logger = logging.getLogger(__name__)
    scheduler = application.bot_data.get("scheduler")
    if scheduler:
        logger.info("Shutting down background scheduler...")
        stop_scheduler(scheduler)
        await asyncio.sleep(0)
        logger.info("Background scheduler stopped cleanly.")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def _build_application() -> Application:
    """Create and configure the python-telegram-bot Application."""
    app = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
        .build()
    )

    # --- Register handlers in priority order ---
    # 1. Core navigation handlers (/start, /help, /cancel)
    for handler in start_handlers:
        app.add_handler(handler)

    # 2. Task management handlers (populated from Phase 2 onward)
    for handler in task_handlers:
        app.add_handler(handler)

    # 3. Settings handler (populated from Phase 7 onward)
    for handler in settings_handlers:
        app.add_handler(handler)

    # 4. Catch-all for unknown commands — must be last
    app.add_handler(
        MessageHandler(filters.COMMAND, unknown_command)
    )

    # 5. Global error handler
    app.add_error_handler(_error_handler)

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logger = logging.getLogger(__name__)

    _setup_logging()

    logger.info("=" * 60)
    logger.info("  Telegram To-Do Bot starting up...")
    logger.info("  Mode    : %s", settings.BOT_MODE)
    logger.info("  DB URL  : %s", settings.DATABASE_URL)
    logger.info("  Timezone: %s", settings.TIMEZONE)
    logger.info("  Log level: %s", settings.LOG_LEVEL)
    logger.info("=" * 60)

    # Validate settings before touching the network or DB
    _validate_settings()

    # Initialize database (creates tables if they don't exist)
    init_db()

    # Build the Telegram application
    application = _build_application()
    logger.info("Bot application built. Registering handlers done.")

    # Start bot
    if settings.BOT_MODE == "polling":
        logger.info("Starting in POLLING mode. Press Ctrl+C to stop.")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,  # Ignore messages received while bot was offline
        )

    elif settings.BOT_MODE == "webhook":
        logger.info(
            "Starting in WEBHOOK mode on port %s. URL: %s",
            settings.WEBHOOK_PORT,
            settings.WEBHOOK_URL,
        )
        application.run_webhook(
            listen="0.0.0.0",
            port=settings.WEBHOOK_PORT,
            webhook_url=settings.WEBHOOK_URL,
            secret_token=settings.WEBHOOK_SECRET_TOKEN or None,
            drop_pending_updates=True,
        )

    else:
        raise ValueError(f"Unknown BOT_MODE: {settings.BOT_MODE!r}")


if __name__ == "__main__":
    main()
