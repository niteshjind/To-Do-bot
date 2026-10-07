"""
tests/test_scheduler.py — Unit and integration tests for APScheduler integration.

Tests cover:
  • create_scheduler() — job registration, interval, safety settings (max_instances=1, coalesce=True)
  • start_scheduler() and stop_scheduler() — clean lifecycle control
  • poll_reminders_job() — job execution and exception containment
  • _on_startup() and _on_shutdown() — application lifecycle integration in main.py
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.triggers.interval import IntervalTrigger

from bot.config import settings
from bot.main import _on_shutdown, _on_startup
from bot.scheduler.jobs import (
    JOB_ID_POLL_REMINDERS,
    create_scheduler,
    poll_reminders_job,
    start_scheduler,
    stop_scheduler,
)


@pytest.fixture
def mock_bot() -> AsyncMock:
    return AsyncMock()


def test_create_scheduler_configuration(mock_bot: AsyncMock) -> None:
    scheduler = create_scheduler(mock_bot)

    # Verify scheduler is not running yet
    assert scheduler.running is False

    # Verify job registered
    job = scheduler.get_job(JOB_ID_POLL_REMINDERS)
    assert job is not None
    assert job.name == "Poll and deliver due task reminders"
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.misfire_grace_time == 60
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == settings.REMINDER_POLL_INTERVAL_SECONDS


@pytest.mark.asyncio
async def test_scheduler_lifecycle(mock_bot: AsyncMock) -> None:
    scheduler = create_scheduler(mock_bot)
    assert scheduler.running is False

    start_scheduler(scheduler)
    assert scheduler.running is True

    # Repeated start call is safe
    start_scheduler(scheduler)
    assert scheduler.running is True

    stop_scheduler(scheduler)
    await asyncio.sleep(0)
    assert scheduler.running is False

    # Repeated stop call is safe
    stop_scheduler(scheduler)
    assert scheduler.running is False


@pytest.mark.asyncio
async def test_poll_reminders_job_success(mock_bot: AsyncMock) -> None:
    with patch("bot.scheduler.jobs.process_due_reminders", new_callable=AsyncMock) as mock_process:
        mock_process.return_value = 3
        delivered = await poll_reminders_job(mock_bot)

    assert delivered == 3
    mock_process.assert_awaited_once_with(mock_bot)


@pytest.mark.asyncio
async def test_poll_reminders_job_handles_exception(mock_bot: AsyncMock) -> None:
    with patch("bot.scheduler.jobs.process_due_reminders", new_callable=AsyncMock) as mock_process:
        mock_process.side_effect = RuntimeError("Database connection lost")
        delivered = await poll_reminders_job(mock_bot)

    # Does not crash; logs and returns 0
    assert delivered == 0


@pytest.mark.asyncio
async def test_application_startup_and_shutdown_hooks(mock_bot: AsyncMock) -> None:
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    mock_app.bot_data = {}

    with patch("bot.main.process_due_reminders", new_callable=AsyncMock) as mock_sweep:
        mock_sweep.return_value = 1
        await _on_startup(mock_app)

    # Scheduler stored in bot_data and running
    scheduler = mock_app.bot_data.get("scheduler")
    assert scheduler is not None
    assert scheduler.running is True

    # Startup sweep was invoked
    mock_sweep.assert_awaited_once_with(mock_bot)

    # Test clean shutdown hook
    await _on_shutdown(mock_app)
    assert scheduler.running is False
