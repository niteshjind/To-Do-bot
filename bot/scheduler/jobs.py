"""
scheduler/jobs.py — APScheduler job definitions and lifecycle management.

Phase 5:
  • create_scheduler(bot): configures AsyncIOScheduler with poll_due_reminders
  • poll_reminders_job(bot): periodic callback that calls reminder_service.process_due_reminders
  • start_scheduler(scheduler): starts scheduler safely
  • stop_scheduler(scheduler): stops scheduler cleanly
"""

import logging
from typing import Optional

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import settings
from bot.services.reminder_service import process_due_reminders
from bot.services.summary_service import process_daily_summaries

logger = logging.getLogger(__name__)

JOB_ID_POLL_REMINDERS = "poll_due_reminders"
JOB_ID_DAILY_SUMMARY = "poll_daily_summaries"


async def poll_reminders_job(bot) -> int:
    """
    APScheduler job callback.
    Polls database for due tasks and sends reminders via the Telegram bot.
    """
    try:
        delivered = await process_due_reminders(bot)
        if delivered > 0:
            logger.info("poll_reminders_job: delivered %d reminder(s).", delivered)
        return delivered
    except Exception as exc:
        logger.error("Error during poll_reminders_job: %s", exc, exc_info=True)
        return 0


async def poll_daily_summaries_job(bot) -> int:
    """
    APScheduler job callback.
    Polls database for users due for their daily task summary and delivers it.
    """
    try:
        delivered = await process_daily_summaries(bot)
        if delivered > 0:
            logger.info("poll_daily_summaries_job: delivered %d daily summary/summaries.", delivered)
        return delivered
    except Exception as exc:
        logger.error("Error during poll_daily_summaries_job: %s", exc, exc_info=True)
        return 0


def create_scheduler(bot) -> AsyncIOScheduler:
    """
    Configure and instantiate the AsyncIOScheduler.

    Adds two interval jobs:
      1. `poll_reminders_job` (every REMINDER_POLL_INTERVAL_SECONDS)
      2. `poll_daily_summaries_job` (every DAILY_SUMMARY_POLL_INTERVAL_SECONDS)

    Both jobs are configured with:
      - max_instances: 1 (strictly prevents overlapping runs)
      - coalesce: True (combines missed runs into one)
      - misfire_grace_time: 60 (allows firing if event loop was briefly delayed)

    Args:
        bot: Telegram Bot instance passed to the job callbacks.

    Returns:
        Configured, unstarted AsyncIOScheduler instance.
    """
    scheduler = AsyncIOScheduler(timezone=pytz.utc)

    scheduler.add_job(
        poll_reminders_job,
        trigger="interval",
        seconds=settings.REMINDER_POLL_INTERVAL_SECONDS,
        id=JOB_ID_POLL_REMINDERS,
        name="Poll and deliver due task reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        args=[bot],
    )
    scheduler.add_job(
        poll_daily_summaries_job,
        trigger="interval",
        seconds=settings.DAILY_SUMMARY_POLL_INTERVAL_SECONDS,
        id=JOB_ID_DAILY_SUMMARY,
        name="Poll and deliver daily task summaries",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        args=[bot],
    )
    logger.info(
        "Created AsyncIOScheduler with jobs '%s' (interval=%ds) and '%s' (interval=%ds).",
        JOB_ID_POLL_REMINDERS,
        settings.REMINDER_POLL_INTERVAL_SECONDS,
        JOB_ID_DAILY_SUMMARY,
        settings.DAILY_SUMMARY_POLL_INTERVAL_SECONDS,
    )
    return scheduler


def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    """
    Start the scheduler if it is not already running.
    """
    if scheduler and not scheduler.running:
        scheduler.start()
        logger.info("AsyncIOScheduler started successfully.")


def stop_scheduler(scheduler: Optional[AsyncIOScheduler]) -> None:
    """
    Cleanly shut down the scheduler if running.
    """
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("AsyncIOScheduler stopped.")
