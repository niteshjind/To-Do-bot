"""
tests/test_summary_service.py — Unit tests for Phase 7 Step 2 daily task summary service
and reminder preference compatibility.

Tests cover:
  • Summary for a day with no tasks
  • Completed and pending tasks due today with accurate counts
  • Incomplete overdue tasks due before today
  • Ensuring completed overdue tasks are NOT counted as overdue
  • Ensuring cancelled tasks are NOT counted as overdue
  • Disjoint separation: no double-counting between today and overdue tasks
  • Day boundary isolation across local midnight and UTC transitions
  • User ownership isolation in summaries
  • Reminder preference filtering in get_due_tasks (filter_reminders_enabled)
  • is_reminder_eligible helper
"""

from datetime import date, datetime, time as time_cls, timedelta, timezone
import pytest
import pytz
from sqlalchemy.orm import Session

from bot.database.models import Task, TaskPriority, TaskStatus, User
from bot.services.task_service import (
    DailySummaryDTO,
    complete_task,
    create_task,
    delete_task,
    get_daily_summary,
    get_due_tasks,
    get_overdue_tasks,
    is_reminder_eligible,
)
from bot.services.user_service import (
    get_or_create_user,
    update_reminders_enabled,
)
from bot.utils.datetime_utils import combine_to_utc


@pytest.fixture
def test_user(db_session: Session) -> User:
    """Create a test user with Asia/Kolkata timezone."""
    user = get_or_create_user(
        db=db_session,
        telegram_user_id=12345678,
        username="summary_user",
        first_name="Summary Tester",
    )
    db_session.commit()
    return user


@pytest.fixture
def other_user(db_session: Session) -> User:
    """Create a second test user to verify multi-tenant isolation."""
    user = get_or_create_user(
        db=db_session,
        telegram_user_id=87654321,
        username="other_user",
        first_name="Other Tester",
    )
    db_session.commit()
    return user


# ===========================================================================
# Daily Task Summary Tests
# ===========================================================================

class TestDailyTaskSummary:
    def test_summary_empty_day(self, db_session: Session, test_user: User) -> None:
        """User with no tasks receives clean summary with zero counts."""
        target_date = date(2026, 10, 11)
        summary = get_daily_summary(db=db_session, user=test_user, target_date=target_date)

        assert isinstance(summary, DailySummaryDTO)
        assert summary.user_id == test_user.id
        assert summary.telegram_user_id == test_user.telegram_user_id
        assert summary.date == target_date
        assert summary.timezone == test_user.timezone
        assert summary.today_tasks == []
        assert summary.today_pending_count == 0
        assert summary.today_completed_count == 0
        assert summary.today_total_count == 0
        assert summary.overdue_tasks == []
        assert summary.overdue_count == 0

    def test_summary_today_pending_and_completed_counts(
        self, db_session: Session, test_user: User
    ) -> None:
        """Tasks due today are correctly partitioned into pending and completed counts."""
        target_date = date(2026, 10, 11)

        # Task 1: pending at 10:00 local
        t1_due = combine_to_utc(target_date, time_cls(10, 0), test_user.timezone)
        create_task(db=db_session, user=test_user, title="Today Pending 1", due_at_utc=t1_due)

        # Task 2: pending at 14:00 local
        t2_due = combine_to_utc(target_date, time_cls(14, 0), test_user.timezone)
        create_task(db=db_session, user=test_user, title="Today Pending 2", due_at_utc=t2_due)

        # Task 3: completed at 16:00 local
        t3_due = combine_to_utc(target_date, time_cls(16, 0), test_user.timezone)
        t3 = create_task(db=db_session, user=test_user, title="Today Completed", due_at_utc=t3_due)
        complete_task(db=db_session, task=t3)

        db_session.commit()

        summary = get_daily_summary(db=db_session, user=test_user, target_date=target_date)

        assert summary.today_total_count == 3
        assert summary.today_pending_count == 2
        assert summary.today_completed_count == 1
        assert len(summary.today_tasks) == 3
        assert summary.overdue_count == 0
        assert summary.overdue_tasks == []

        # Chronological order of today_tasks
        assert [t.title for t in summary.today_tasks] == [
            "Today Pending 1",
            "Today Pending 2",
            "Today Completed",
        ]

    def test_overdue_incomplete_tasks_included(
        self, db_session: Session, test_user: User
    ) -> None:
        """Incomplete tasks due before target_date are included in overdue_tasks."""
        target_date = date(2026, 10, 11)
        yesterday = target_date - timedelta(days=1)
        two_days_ago = target_date - timedelta(days=2)

        # Overdue 1: 2 days ago
        t_old_due = combine_to_utc(two_days_ago, time_cls(15, 0), test_user.timezone)
        create_task(db=db_session, user=test_user, title="Old Overdue", due_at_utc=t_old_due)

        # Overdue 2: yesterday
        t_yest_due = combine_to_utc(yesterday, time_cls(18, 0), test_user.timezone)
        create_task(db=db_session, user=test_user, title="Yesterday Overdue", due_at_utc=t_yest_due)

        # Today task
        t_today_due = combine_to_utc(target_date, time_cls(9, 0), test_user.timezone)
        create_task(db=db_session, user=test_user, title="Today Task", due_at_utc=t_today_due)

        db_session.commit()

        summary = get_daily_summary(db=db_session, user=test_user, target_date=target_date)

        assert summary.today_total_count == 1
        assert summary.today_pending_count == 1
        assert summary.overdue_count == 2
        assert len(summary.overdue_tasks) == 2
        assert [t.title for t in summary.overdue_tasks] == ["Old Overdue", "Yesterday Overdue"]

    def test_completed_overdue_tasks_not_counted_as_overdue(
        self, db_session: Session, test_user: User
    ) -> None:
        """Past tasks that were completed are NOT counted as overdue."""
        target_date = date(2026, 10, 11)
        yesterday = target_date - timedelta(days=1)

        # Past completed task
        t_done_due = combine_to_utc(yesterday, time_cls(10, 0), test_user.timezone)
        t_done = create_task(db=db_session, user=test_user, title="Done in past", due_at_utc=t_done_due)
        complete_task(db=db_session, task=t_done)

        # Past cancelled task
        t_canc_due = combine_to_utc(yesterday, time_cls(12, 0), test_user.timezone)
        t_canc = create_task(db=db_session, user=test_user, title="Cancelled in past", due_at_utc=t_canc_due)
        delete_task(db=db_session, task=t_canc)

        # Past pending task (truly overdue)
        t_pend_due = combine_to_utc(yesterday, time_cls(14, 0), test_user.timezone)
        create_task(db=db_session, user=test_user, title="Still pending past", due_at_utc=t_pend_due)

        db_session.commit()

        summary = get_daily_summary(db=db_session, user=test_user, target_date=target_date)

        assert summary.overdue_count == 1
        assert len(summary.overdue_tasks) == 1
        assert summary.overdue_tasks[0].title == "Still pending past"

    def test_no_double_counting_between_today_and_overdue(
        self, db_session: Session, test_user: User
    ) -> None:
        """No task can ever appear in both today_tasks and overdue_tasks."""
        target_date = date(2026, 10, 11)
        yesterday = target_date - timedelta(days=1)

        t1_due = combine_to_utc(yesterday, time_cls(23, 59), test_user.timezone)
        create_task(db=db_session, user=test_user, title="Yesterday Task", due_at_utc=t1_due)

        t2_due = combine_to_utc(target_date, time_cls(0, 1), test_user.timezone)
        create_task(db=db_session, user=test_user, title="Today Task", due_at_utc=t2_due)

        db_session.commit()

        summary = get_daily_summary(db=db_session, user=test_user, target_date=target_date)

        today_ids = {t.id for t in summary.today_tasks}
        overdue_ids = {t.id for t in summary.overdue_tasks}

        # Sets must be completely disjoint
        assert today_ids.isdisjoint(overdue_ids)
        assert len(today_ids) == 1
        assert len(overdue_ids) == 1

    def test_midnight_and_day_boundary_isolation(
        self, db_session: Session, test_user: User
    ) -> None:
        """
        Tasks right at local day boundaries (23:59 yesterday, 00:00 today,
        23:59 today, 00:01 tomorrow) fall into the exact correct bucket.
        """
        target_date = date(2026, 10, 11)
        yesterday = target_date - timedelta(days=1)
        tomorrow = target_date + timedelta(days=1)

        # 1. Yesterday 23:59 local -> overdue
        due_yesterday_end = combine_to_utc(yesterday, time_cls(23, 59), test_user.timezone)
        create_task(db=db_session, user=test_user, title="Yesterday Boundary", due_at_utc=due_yesterday_end)

        # 2. Today 00:00 local -> today
        due_today_start = combine_to_utc(target_date, time_cls(0, 0), test_user.timezone)
        create_task(db=db_session, user=test_user, title="Today Start", due_at_utc=due_today_start)

        # 3. Today 23:59 local -> today
        due_today_end = combine_to_utc(target_date, time_cls(23, 59), test_user.timezone)
        create_task(db=db_session, user=test_user, title="Today End", due_at_utc=due_today_end)

        # 4. Tomorrow 00:01 local -> future (neither today nor overdue)
        due_tomorrow_start = combine_to_utc(tomorrow, time_cls(0, 1), test_user.timezone)
        create_task(db=db_session, user=test_user, title="Tomorrow Boundary", due_at_utc=due_tomorrow_start)

        db_session.commit()

        summary = get_daily_summary(db=db_session, user=test_user, target_date=target_date)

        assert [t.title for t in summary.overdue_tasks] == ["Yesterday Boundary"]
        assert [t.title for t in summary.today_tasks] == ["Today Start", "Today End"]
        assert summary.today_total_count == 2
        assert summary.overdue_count == 1

    def test_user_ownership_isolation(
        self, db_session: Session, test_user: User, other_user: User
    ) -> None:
        """User A never sees User B's today or overdue tasks in summary."""
        target_date = date(2026, 10, 11)
        yesterday = target_date - timedelta(days=1)

        # Other user's tasks
        t_other_today = combine_to_utc(target_date, time_cls(10, 0), other_user.timezone)
        create_task(db=db_session, user=other_user, title="Other's Today", due_at_utc=t_other_today)

        t_other_overdue = combine_to_utc(yesterday, time_cls(10, 0), other_user.timezone)
        create_task(db=db_session, user=other_user, title="Other's Overdue", due_at_utc=t_other_overdue)

        # Test user's task
        t_my_today = combine_to_utc(target_date, time_cls(11, 0), test_user.timezone)
        create_task(db=db_session, user=test_user, title="My Today", due_at_utc=t_my_today)

        db_session.commit()

        summary = get_daily_summary(db=db_session, user=test_user, target_date=target_date)

        assert summary.today_total_count == 1
        assert summary.today_tasks[0].title == "My Today"
        assert summary.overdue_count == 0


# ===========================================================================
# Reminder Preference Compatibility Tests
# ===========================================================================

class TestReminderPreferenceCompatibility:
    def test_get_due_tasks_respects_filter_reminders_enabled(
        self, db_session: Session, test_user: User, other_user: User
    ) -> None:
        """
        When filter_reminders_enabled=True, tasks owned by users with
        reminders_enabled=False are excluded.
        """
        now = datetime.now(timezone.utc)
        due_past = now - timedelta(minutes=10)

        # test_user has reminders ENABLED (default True)
        task_user_enabled = create_task(
            db=db_session, user=test_user, title="Reminder Enabled Task", due_at_utc=due_past
        )

        # other_user has reminders DISABLED
        update_reminders_enabled(db=db_session, user=other_user, enabled=False)
        task_user_disabled = create_task(
            db=db_session, user=other_user, title="Reminder Disabled Task", due_at_utc=due_past
        )
        db_session.commit()

        # 1. Unfiltered (default: filter_reminders_enabled=False) -> returns both
        all_due = get_due_tasks(db=db_session, now_utc=now, filter_reminders_enabled=False)
        all_ids = {t.id for t in all_due}
        assert task_user_enabled.id in all_ids
        assert task_user_disabled.id in all_ids

        # 2. Filtered (filter_reminders_enabled=True) -> only includes test_user
        filtered_due = get_due_tasks(db=db_session, now_utc=now, filter_reminders_enabled=True)
        filtered_ids = {t.id for t in filtered_due}
        assert task_user_enabled.id in filtered_ids
        assert task_user_disabled.id not in filtered_ids

    def test_is_reminder_eligible_helper(
        self, db_session: Session, test_user: User
    ) -> None:
        """is_reminder_eligible correctly identifies when user has reminders toggled."""
        now = datetime.now(timezone.utc)
        task = create_task(
            db=db_session, user=test_user, title="Eligibility Test Task", due_at_utc=now
        )
        db_session.commit()

        # User reminders default True
        assert is_reminder_eligible(task) is True

        # Disable reminders for user
        update_reminders_enabled(db=db_session, user=test_user, enabled=False)
        db_session.commit()
        assert is_reminder_eligible(task) is False

        # Re-enable
        update_reminders_enabled(db=db_session, user=test_user, enabled=True)
        db_session.commit()
        assert is_reminder_eligible(task) is True
