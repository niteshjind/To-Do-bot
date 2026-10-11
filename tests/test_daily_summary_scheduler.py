"""
tests/test_daily_summary_scheduler.py — Unit and integration tests for Phase 7 Step 5
daily summary scheduler, delivery deduplication, and reminder preference integration.

Tests cover:
  1. A due summary being sent at the configured local time.
  2. Summary skipped when poll runs before the configured local time.
  3. Summary sent when poll runs after configured local time on the same date.
  4. Users in different timezones receiving summaries at their own configured local times.
  5. Local date boundaries and UTC midnight (e.g. crossing calendar day).
  6. Disabled daily summary (daily_summary_enabled=False) being skipped.
  7. Disabled reminders (reminders_enabled=False) still receiving daily summary.
  8. Disabled summary (daily_summary_enabled=False) still receiving reminders.
  9. Reminders skipped when reminders_enabled=False.
  10. Successful delivery updating last_summary_date.
  11. Failed delivery (TelegramError) leaving last_summary_date unchanged.
  12. Retry on a later poll after previous failure.
  13. No duplicate summary on repeated polls on the same date.
  14. Fault tolerance: invalid timezone does not crash poll for other users.
  15. Fault tolerance: malformed summary time does not crash poll for other users.
  16. User with missing telegram_user_id skipped.
  17. Concurrent polling protection (_summary_poll_lock).
  18. process_daily_summaries with get_db context manager fallback.
  19. APScheduler create_scheduler registers both reminder and summary jobs.
  20. poll_daily_summaries_job exception containment.
  21. Snooze and recurrence compatibility with reminder preference.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from telegram.error import TelegramError

from bot.config import settings
from bot.database.models import Task, TaskPriority, TaskStatus, User
from bot.scheduler.jobs import (
    JOB_ID_DAILY_SUMMARY,
    JOB_ID_POLL_REMINDERS,
    create_scheduler,
    poll_daily_summaries_job,
)
from bot.services.reminder_service import process_due_reminders
from bot.services.summary_service import (
    _summary_poll_lock,
    process_daily_summaries,
    send_daily_summary,
)
from bot.services.task_service import complete_task, create_task, snooze_task
from bot.services.user_service import get_or_create_user, update_daily_summary_time, update_timezone


@pytest.fixture
def mock_bot() -> AsyncMock:
    """Mock Telegram Bot instance."""
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock())
    return bot


@pytest.fixture
def user_kolkata(db_session: Session) -> User:
    """User in Asia/Kolkata timezone with default settings."""
    user = get_or_create_user(
        db=db_session,
        telegram_user_id=11111,
        username="kolkata_user",
        first_name="Kolkata User",
    )
    user.timezone = "Asia/Kolkata"
    user.daily_summary_time = "09:00"
    user.daily_summary_enabled = True
    user.reminders_enabled = True
    user.last_summary_date = None
    db_session.commit()
    return user


@pytest.fixture
def user_ny(db_session: Session) -> User:
    """User in America/New_York timezone with default settings."""
    user = get_or_create_user(
        db=db_session,
        telegram_user_id=22222,
        username="ny_user",
        first_name="NY User",
    )
    user.timezone = "America/New_York"
    user.daily_summary_time = "09:00"
    user.daily_summary_enabled = True
    user.reminders_enabled = True
    user.last_summary_date = None
    db_session.commit()
    return user


# ===========================================================================
# 1. Eligibility & Local Time Scheduling Tests
# ===========================================================================

class TestDailySummaryEligibility:

    @pytest.mark.asyncio
    async def test_summary_sent_when_due_at_configured_time(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """Poll at exactly 09:00 local time delivers the daily summary."""
        # 09:00 in Asia/Kolkata (UTC+5:30) is 03:30 UTC
        now_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)

        delivered = await process_daily_summaries(mock_bot, now_utc=now_utc, db=db_session)

        assert delivered == 1
        mock_bot.send_message.assert_awaited_once()
        _, kwargs = mock_bot.send_message.call_args
        assert kwargs["chat_id"] == user_kolkata.telegram_user_id
        assert "Daily Task Summary" in kwargs["text"]

        refreshed = db_session.query(User).filter_by(id=user_kolkata.id).one()
        assert refreshed.last_summary_date == "2026-10-11"

    @pytest.mark.asyncio
    async def test_summary_not_sent_before_configured_time(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """Poll at 08:59 local time does NOT deliver summary."""
        # 08:59 in Asia/Kolkata is 03:29 UTC
        now_utc = datetime(2026, 10, 11, 3, 29, tzinfo=timezone.utc)

        delivered = await process_daily_summaries(mock_bot, now_utc=now_utc, db=db_session)

        assert delivered == 0
        mock_bot.send_message.assert_not_awaited()

        refreshed = db_session.query(User).filter_by(id=user_kolkata.id).one()
        assert refreshed.last_summary_date is None

    @pytest.mark.asyncio
    async def test_summary_sent_if_poll_runs_after_configured_time(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """Poll running after 09:00 (e.g. 09:15) still delivers if not yet sent today."""
        # 09:15 in Asia/Kolkata is 03:45 UTC
        now_utc = datetime(2026, 10, 11, 3, 45, tzinfo=timezone.utc)

        delivered = await process_daily_summaries(mock_bot, now_utc=now_utc, db=db_session)

        assert delivered == 1
        refreshed = db_session.query(User).filter_by(id=user_kolkata.id).one()
        assert refreshed.last_summary_date == "2026-10-11"

    @pytest.mark.asyncio
    async def test_users_in_different_timezones(
        self, user_kolkata: User, user_ny: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """
        Users in different timezones receive summaries at their own local 09:00 times.
        At UTC 03:30:
          - Kolkata is at 09:00 (due).
          - NY is at 23:30 of previous day (2026-10-10, not yet 09:00 of 2026-10-11).
        At UTC 13:00:
          - NY is at 09:00 (EDT is UTC-4).
          - Kolkata is at 18:30 (already delivered earlier).
        """
        user_ny.last_summary_date = "2026-10-10"
        db_session.commit()

        # Time 1: 03:30 UTC
        t1_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)
        d1 = await process_daily_summaries(mock_bot, now_utc=t1_utc, db=db_session)
        assert d1 == 1
        assert mock_bot.send_message.await_count == 1
        call_kwargs1 = mock_bot.send_message.call_args[1]
        assert call_kwargs1["chat_id"] == user_kolkata.telegram_user_id

        # Verify DB state after Time 1
        u1 = db_session.query(User).filter_by(id=user_kolkata.id).one()
        u2 = db_session.query(User).filter_by(id=user_ny.id).one()
        assert u1.last_summary_date == "2026-10-11"
        assert u2.last_summary_date == "2026-10-10"

        # Time 2: 13:00 UTC (09:00 EDT in New York)
        t2_utc = datetime(2026, 10, 11, 13, 0, tzinfo=timezone.utc)
        d2 = await process_daily_summaries(mock_bot, now_utc=t2_utc, db=db_session)
        assert d2 == 1
        assert mock_bot.send_message.await_count == 2
        call_kwargs2 = mock_bot.send_message.call_args[1]
        assert call_kwargs2["chat_id"] == user_ny.telegram_user_id

        # Verify DB state after Time 2
        db_session.refresh(u1)
        db_session.refresh(u2)
        assert u1.last_summary_date == "2026-10-11"
        assert u2.last_summary_date == "2026-10-11"

    @pytest.mark.asyncio
    async def test_local_date_boundaries_and_utc_midnight(
        self, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """
        User in Asia/Tokyo (UTC+9) near UTC midnight:
        UTC time: 2026-10-11 23:15:00 UTC
        Tokyo local time: 2026-10-12 08:15:00
        Configured time: 08:00
        Summary must be tagged and delivered for Tokyo's local calendar date: 2026-10-12.
        """
        tokyo_user = get_or_create_user(
            db=db_session,
            telegram_user_id=33333,
            username="tokyo_user",
        )
        tokyo_user.timezone = "Asia/Tokyo"
        tokyo_user.daily_summary_time = "08:00"
        tokyo_user.daily_summary_enabled = True
        tokyo_user.last_summary_date = "2026-10-11"  # Already delivered for yesterday
        db_session.commit()

        utc_now = datetime(2026, 10, 11, 23, 15, tzinfo=timezone.utc)

        delivered = await process_daily_summaries(mock_bot, now_utc=utc_now, db=db_session)

        assert delivered == 1
        db_session.refresh(tokyo_user)
        assert tokyo_user.last_summary_date == "2026-10-12"


# ===========================================================================
# 2. Preference Toggles & Independence Tests
# ===========================================================================

class TestPreferencesAndToggles:

    @pytest.mark.asyncio
    async def test_disabled_daily_summary_skipped(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """daily_summary_enabled=False skips user even when due."""
        user_kolkata.daily_summary_enabled = False
        db_session.commit()

        now_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)
        delivered = await process_daily_summaries(mock_bot, now_utc=now_utc, db=db_session)

        assert delivered == 0
        mock_bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disabled_reminders_still_receives_daily_summary(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """Disabling reminders (reminders_enabled=False) does NOT block daily summary."""
        user_kolkata.reminders_enabled = False
        user_kolkata.daily_summary_enabled = True
        db_session.commit()

        now_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)
        delivered = await process_daily_summaries(mock_bot, now_utc=now_utc, db=db_session)

        assert delivered == 1
        mock_bot.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disabled_summary_still_receives_reminders(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """Disabling daily summary (daily_summary_enabled=False) does NOT block task reminders."""
        user_kolkata.daily_summary_enabled = False
        user_kolkata.reminders_enabled = True
        db_session.commit()

        now_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)
        # Create due task
        t = create_task(
            db=db_session,
            user=user_kolkata,
            title="Important Task",
            due_at_utc=now_utc - timedelta(minutes=5),
        )
        db_session.commit()

        # Reminders run
        rem_delivered = await process_due_reminders(mock_bot, now_utc=now_utc, db=db_session)
        assert rem_delivered == 1
        mock_bot.send_message.assert_awaited_once()

        # Daily summary run returns 0
        sum_delivered = await process_daily_summaries(mock_bot, now_utc=now_utc, db=db_session)
        assert sum_delivered == 0

    @pytest.mark.asyncio
    async def test_reminders_skipped_when_reminders_disabled(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """Task reminders are not sent to users who turned off reminders_enabled."""
        user_kolkata.reminders_enabled = False
        db_session.commit()

        now_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)
        t = create_task(
            db=db_session,
            user=user_kolkata,
            title="Skipped Task",
            due_at_utc=now_utc - timedelta(minutes=5),
        )
        db_session.commit()

        delivered = await process_due_reminders(mock_bot, now_utc=now_utc, db=db_session)

        assert delivered == 0
        mock_bot.send_message.assert_not_awaited()
        db_session.refresh(t)
        assert t.reminder_sent is False

    @pytest.mark.asyncio
    async def test_snooze_and_recurrence_compatibility_with_reminders(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """
        Verify that snoozed and recurring tasks retain correct behavior with
        the reminder preferences in place.
        """
        now_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)
        # 1. Snooze task
        task = create_task(
            db=db_session,
            user=user_kolkata,
            title="Snoozable Task",
            due_at_utc=now_utc - timedelta(minutes=10),
            recurrence="daily",
        )
        db_session.commit()

        # Snooze 30m into future
        snoozed_due = now_utc + timedelta(minutes=30)
        snooze_task(db=db_session, task=task, new_due_at_utc=snoozed_due)
        db_session.commit()

        # At now_utc, snoozed task is in future -> 0 delivered
        d1 = await process_due_reminders(mock_bot, now_utc=now_utc, db=db_session)
        assert d1 == 0

        # At now_utc + 35m, snoozed task is due -> 1 delivered
        d2 = await process_due_reminders(mock_bot, now_utc=now_utc + timedelta(minutes=35), db=db_session)
        assert d2 == 1
        db_session.refresh(task)
        assert task.reminder_sent is True

        # 2. Complete recurring task schedules next recurrence
        complete_task(db=db_session, task=task)
        db_session.commit()
        db_session.refresh(task)
        assert task.status == TaskStatus.completed
        assert task.next_occurrence is not None
        assert task.next_occurrence.due_at == snoozed_due + timedelta(days=1)
        assert task.next_occurrence.reminder_sent is False


# ===========================================================================
# 3. Delivery, Deduplication & Retry Tests
# ===========================================================================

class TestDeliveryAndDeduplication:

    @pytest.mark.asyncio
    async def test_successful_delivery_updates_last_summary_date(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """Successful delivery records the local calendar date."""
        now_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)

        delivered = await process_daily_summaries(mock_bot, now_utc=now_utc, db=db_session)

        assert delivered == 1
        db_session.refresh(user_kolkata)
        assert user_kolkata.last_summary_date == "2026-10-11"

    @pytest.mark.asyncio
    async def test_failed_delivery_leaves_last_summary_date_unchanged(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """TelegramError leaves last_summary_date untouched so it can retry later."""
        mock_bot.send_message.side_effect = TelegramError("Network timeout")
        now_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)

        delivered = await process_daily_summaries(mock_bot, now_utc=now_utc, db=db_session)

        assert delivered == 0
        db_session.refresh(user_kolkata)
        assert user_kolkata.last_summary_date is None

    @pytest.mark.asyncio
    async def test_retry_on_later_poll(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """If poll 1 fails, poll 2 successfully delivers and stamps last_summary_date."""
        now_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)

        # Poll 1: Telegram fails
        mock_bot.send_message.side_effect = TelegramError("Temporary glitch")
        d1 = await process_daily_summaries(mock_bot, now_utc=now_utc, db=db_session)
        assert d1 == 0
        db_session.refresh(user_kolkata)
        assert user_kolkata.last_summary_date is None

        # Poll 2: Telegram succeeds 1 minute later
        mock_bot.send_message.side_effect = None
        d2 = await process_daily_summaries(
            mock_bot, now_utc=now_utc + timedelta(minutes=1), db=db_session
        )
        assert d2 == 1
        db_session.refresh(user_kolkata)
        assert user_kolkata.last_summary_date == "2026-10-11"

    @pytest.mark.asyncio
    async def test_no_duplicate_on_repeated_polls(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """Repeated polls on the same date send at most 1 summary."""
        now_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)

        # Poll 1
        d1 = await process_daily_summaries(mock_bot, now_utc=now_utc, db=db_session)
        assert d1 == 1
        assert mock_bot.send_message.await_count == 1

        # Poll 2 (5 minutes later)
        d2 = await process_daily_summaries(
            mock_bot, now_utc=now_utc + timedelta(minutes=5), db=db_session
        )
        assert d2 == 0
        # No additional Telegram message sent
        assert mock_bot.send_message.await_count == 1

        # Poll 3 (afternoon)
        d3 = await process_daily_summaries(
            mock_bot, now_utc=now_utc + timedelta(hours=4), db=db_session
        )
        assert d3 == 0
        assert mock_bot.send_message.await_count == 1

    @pytest.mark.asyncio
    async def test_send_daily_summary_direct(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """Test send_daily_summary helper directly with User instance and raw chat ID."""
        from bot.services.task_service import get_daily_summary

        summary_dto = get_daily_summary(db=db_session, user=user_kolkata, target_date=date(2026, 10, 11))

        # With User instance
        res1 = await send_daily_summary(mock_bot, user_kolkata, summary_dto)
        assert res1 is True

        # With chat_id int
        res2 = await send_daily_summary(mock_bot, 99999, summary_dto)
        assert res2 is True

        # With empty chat_id
        res3 = await send_daily_summary(mock_bot, 0, summary_dto)
        assert res3 is False


# ===========================================================================
# 4. Fault Tolerance & Safety Tests
# ===========================================================================

class TestFaultToleranceAndSafety:

    @pytest.mark.asyncio
    async def test_invalid_timezone_does_not_crash_other_users(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """User with invalid timezone is skipped without blocking valid users."""
        invalid_user = get_or_create_user(
            db=db_session, telegram_user_id=77777, username="bad_tz"
        )
        invalid_user.timezone = "NonExistent/Zone"
        invalid_user.daily_summary_time = "09:00"
        invalid_user.daily_summary_enabled = True
        db_session.commit()

        now_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)
        delivered = await process_daily_summaries(mock_bot, now_utc=now_utc, db=db_session)

        # Only the valid user received their summary
        assert delivered == 1
        db_session.refresh(user_kolkata)
        db_session.refresh(invalid_user)
        assert user_kolkata.last_summary_date == "2026-10-11"
        assert invalid_user.last_summary_date is None

    @pytest.mark.asyncio
    async def test_malformed_summary_time_does_not_crash_other_users(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """User with malformed summary time string is skipped without blocking valid users."""
        bad_time_user = get_or_create_user(
            db=db_session, telegram_user_id=66666, username="bad_time"
        )
        bad_time_user.timezone = "Asia/Kolkata"
        bad_time_user.daily_summary_time = "25:99"
        bad_time_user.daily_summary_enabled = True
        db_session.commit()

        now_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)
        delivered = await process_daily_summaries(mock_bot, now_utc=now_utc, db=db_session)

        assert delivered == 1
        db_session.refresh(user_kolkata)
        db_session.refresh(bad_time_user)
        assert user_kolkata.last_summary_date == "2026-10-11"
        assert bad_time_user.last_summary_date is None

    @pytest.mark.asyncio
    async def test_naive_datetime_raises_value_error(
        self, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """Passing a naive datetime to process_daily_summaries raises ValueError."""
        naive_dt = datetime(2026, 10, 11, 3, 30)  # No tzinfo
        with pytest.raises(ValueError, match="timezone-aware"):
            await process_daily_summaries(mock_bot, now_utc=naive_dt, db=db_session)

    @pytest.mark.asyncio
    async def test_concurrency_lock_skips_when_locked(
        self, mock_bot: AsyncMock
    ) -> None:
        """If _summary_poll_lock is already held, concurrent call returns 0 immediately."""
        async with _summary_poll_lock:
            delivered = await process_daily_summaries(mock_bot)
            assert delivered == 0
            mock_bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_process_daily_summaries_with_get_db(
        self, user_kolkata: User, db_session: Session, mock_bot: AsyncMock
    ) -> None:
        """When db is None, process_daily_summaries uses get_db context manager."""
        now_utc = datetime(2026, 10, 11, 3, 30, tzinfo=timezone.utc)

        with patch("bot.services.summary_service.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = db_session
            mock_get_db.return_value.__exit__.return_value = False

            delivered = await process_daily_summaries(mock_bot, now_utc=now_utc)

        assert delivered == 1
        db_session.refresh(user_kolkata)
        assert user_kolkata.last_summary_date == "2026-10-11"


# ===========================================================================
# 5. APScheduler Integration Tests
# ===========================================================================

class TestSchedulerIntegration:

    def test_create_scheduler_contains_both_jobs(self, mock_bot: AsyncMock) -> None:
        """Scheduler registers both poll_due_reminders and poll_daily_summaries jobs."""
        scheduler = create_scheduler(mock_bot)
        assert scheduler.running is False

        # Reminder job
        rem_job = scheduler.get_job(JOB_ID_POLL_REMINDERS)
        assert rem_job is not None
        assert rem_job.max_instances == 1
        assert rem_job.coalesce is True
        assert rem_job.misfire_grace_time == 60
        assert isinstance(rem_job.trigger, IntervalTrigger)

        # Daily summary job
        sum_job = scheduler.get_job(JOB_ID_DAILY_SUMMARY)
        assert sum_job is not None
        assert sum_job.name == "Poll and deliver daily task summaries"
        assert sum_job.max_instances == 1
        assert sum_job.coalesce is True
        assert sum_job.misfire_grace_time == 60
        assert isinstance(sum_job.trigger, IntervalTrigger)
        assert sum_job.trigger.interval.total_seconds() == settings.DAILY_SUMMARY_POLL_INTERVAL_SECONDS

    @pytest.mark.asyncio
    async def test_poll_daily_summaries_job_success(self, mock_bot: AsyncMock) -> None:
        """poll_daily_summaries_job calls process_daily_summaries and returns count."""
        with patch("bot.scheduler.jobs.process_daily_summaries", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = 5
            res = await poll_daily_summaries_job(mock_bot)

        assert res == 5
        mock_process.assert_awaited_once_with(mock_bot)

    @pytest.mark.asyncio
    async def test_poll_daily_summaries_job_exception_containment(self, mock_bot: AsyncMock) -> None:
        """poll_daily_summaries_job logs and returns 0 on unexpected exception without crashing."""
        with patch("bot.scheduler.jobs.process_daily_summaries", new_callable=AsyncMock) as mock_process:
            mock_process.side_effect = RuntimeError("DB engine disconnect")
            res = await poll_daily_summaries_job(mock_bot)

        assert res == 0
