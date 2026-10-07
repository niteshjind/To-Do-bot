"""
tests/test_task_service.py — Unit and integration tests for task_service.py.

Tests cover:
  • create_task()    — happy path, all priorities, validation errors
  • get_task_by_id() — found, not found, wrong owner (ownership check)

All tests use the in-memory `db_session` fixture from conftest.py.
No real database file is created or modified.
"""

from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy.orm import Session

from bot.database.models import Task, TaskPriority, TaskStatus, User
from bot.services.task_service import (
    MAX_TITLE_LENGTH,
    complete_task,
    create_task,
    delete_task,
    edit_task,
    get_due_tasks,
    get_pending_tasks,
    get_task_by_id,
    get_today_tasks,
    get_upcoming_tasks,
    mark_reminder_sent,
)
from bot.services.user_service import get_or_create_user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def user(db_session: Session) -> User:
    """A test user persisted in the in-memory DB."""
    u = get_or_create_user(
        db=db_session,
        telegram_user_id=10001,
        username="test_user",
        first_name="Test",
    )
    db_session.commit()
    return u


@pytest.fixture
def other_user(db_session: Session) -> User:
    """A second test user — used to verify ownership checks."""
    u = get_or_create_user(
        db=db_session,
        telegram_user_id=10002,
        username="other_user",
        first_name="Other",
    )
    db_session.commit()
    return u


def _future_utc(hours: int = 1) -> datetime:
    """Return a UTC-aware datetime N hours in the future."""
    return datetime.now(timezone.utc) + timedelta(hours=hours)


# ===========================================================================
# create_task — Happy path
# ===========================================================================

class TestCreateTaskHappyPath:
    def test_creates_task_with_correct_fields(
        self, db_session: Session, user: User
    ) -> None:
        """A successfully created task has all expected field values."""
        due = _future_utc(2)
        task = create_task(
            db=db_session,
            user=user,
            title="Buy groceries",
            due_at_utc=due,
            priority=TaskPriority.medium,
        )
        db_session.commit()

        assert task.id is not None
        assert task.user_id == user.id
        assert task.title == "Buy groceries"
        assert task.status == TaskStatus.pending
        assert task.priority == TaskPriority.medium
        assert task.due_at == due
        assert task.reminder_sent is False
        assert task.completed_at is None

    def test_task_persisted_in_db(self, db_session: Session, user: User) -> None:
        """The task is actually written to the database."""
        due = _future_utc(1)
        task = create_task(
            db=db_session,
            user=user,
            title="Write tests",
            due_at_utc=due,
        )
        db_session.commit()

        retrieved = db_session.query(Task).filter_by(id=task.id).first()
        assert retrieved is not None
        assert retrieved.title == "Write tests"

    def test_default_priority_is_medium(self, db_session: Session, user: User) -> None:
        """When priority is not specified, it defaults to medium."""
        task = create_task(
            db=db_session,
            user=user,
            title="Default priority task",
            due_at_utc=_future_utc(),
        )
        db_session.commit()
        assert task.priority == TaskPriority.medium

    def test_creates_task_with_low_priority(
        self, db_session: Session, user: User
    ) -> None:
        task = create_task(
            db=db_session,
            user=user,
            title="Low priority task",
            due_at_utc=_future_utc(),
            priority=TaskPriority.low,
        )
        db_session.commit()
        assert task.priority == TaskPriority.low

    def test_creates_task_with_high_priority(
        self, db_session: Session, user: User
    ) -> None:
        task = create_task(
            db=db_session,
            user=user,
            title="High priority task",
            due_at_utc=_future_utc(),
            priority=TaskPriority.high,
        )
        db_session.commit()
        assert task.priority == TaskPriority.high

    def test_strips_whitespace_from_title(
        self, db_session: Session, user: User
    ) -> None:
        """Leading/trailing whitespace in the title is removed."""
        task = create_task(
            db=db_session,
            user=user,
            title="  Submit report  ",
            due_at_utc=_future_utc(),
        )
        db_session.commit()
        assert task.title == "Submit report"

    def test_created_at_is_set(self, db_session: Session, user: User) -> None:
        task = create_task(
            db=db_session,
            user=user,
            title="Check created_at",
            due_at_utc=_future_utc(),
        )
        db_session.commit()
        assert task.created_at is not None

    def test_multiple_tasks_for_same_user(
        self, db_session: Session, user: User
    ) -> None:
        """A user can have multiple tasks."""
        t1 = create_task(db=db_session, user=user, title="Task 1", due_at_utc=_future_utc(1))
        t2 = create_task(db=db_session, user=user, title="Task 2", due_at_utc=_future_utc(2))
        db_session.commit()

        assert t1.id != t2.id
        count = db_session.query(Task).filter_by(user_id=user.id).count()
        assert count == 2

    def test_max_length_title_accepted(self, db_session: Session, user: User) -> None:
        """A title exactly at MAX_TITLE_LENGTH characters is valid."""
        title = "A" * MAX_TITLE_LENGTH
        task = create_task(
            db=db_session,
            user=user,
            title=title,
            due_at_utc=_future_utc(),
        )
        db_session.commit()
        assert len(task.title) == MAX_TITLE_LENGTH


# ===========================================================================
# create_task — Validation failures
# ===========================================================================

class TestCreateTaskValidation:
    def test_empty_title_raises(self, db_session: Session, user: User) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            create_task(
                db=db_session,
                user=user,
                title="",
                due_at_utc=_future_utc(),
            )

    def test_whitespace_only_title_raises(
        self, db_session: Session, user: User
    ) -> None:
        """A title of only spaces is functionally empty after strip()."""
        with pytest.raises(ValueError, match="cannot be empty"):
            create_task(
                db=db_session,
                user=user,
                title="   ",
                due_at_utc=_future_utc(),
            )

    def test_title_too_long_raises(self, db_session: Session, user: User) -> None:
        long_title = "B" * (MAX_TITLE_LENGTH + 1)
        with pytest.raises(ValueError, match="exceeds maximum length"):
            create_task(
                db=db_session,
                user=user,
                title=long_title,
                due_at_utc=_future_utc(),
            )

    def test_naive_datetime_raises(self, db_session: Session, user: User) -> None:
        """
        due_at_utc must be timezone-aware.
        Passing a naive datetime (no tzinfo) should raise ValueError.
        """
        naive_dt = datetime(2026, 10, 8, 9, 0)  # No tzinfo
        with pytest.raises(ValueError, match="timezone-aware"):
            create_task(
                db=db_session,
                user=user,
                title="Valid title",
                due_at_utc=naive_dt,
            )

    def test_failed_validation_does_not_write_to_db(
        self, db_session: Session, user: User
    ) -> None:
        """A validation failure must not partially persist any data."""
        count_before = db_session.query(Task).count()

        with pytest.raises(ValueError):
            create_task(
                db=db_session,
                user=user,
                title="",  # Invalid
                due_at_utc=_future_utc(),
            )

        db_session.rollback()
        count_after = db_session.query(Task).count()
        assert count_after == count_before


# ===========================================================================
# get_task_by_id
# ===========================================================================

class TestGetTaskById:
    def test_returns_task_for_correct_owner(
        self, db_session: Session, user: User
    ) -> None:
        task = create_task(
            db=db_session,
            user=user,
            title="Find me",
            due_at_utc=_future_utc(),
        )
        db_session.commit()

        found = get_task_by_id(db=db_session, task_id=task.id, user_id=user.id)
        assert found is not None
        assert found.id == task.id
        assert found.title == "Find me"

    def test_returns_none_for_nonexistent_task(
        self, db_session: Session, user: User
    ) -> None:
        result = get_task_by_id(db=db_session, task_id=99999, user_id=user.id)
        assert result is None

    def test_returns_none_for_wrong_owner(
        self,
        db_session: Session,
        user: User,
        other_user: User,
    ) -> None:
        """
        Ownership check: a task belonging to `user` must NOT be visible
        when queried with `other_user`'s ID.
        """
        task = create_task(
            db=db_session,
            user=user,
            title="Owner's task",
            due_at_utc=_future_utc(),
        )
        db_session.commit()

        # other_user attempts to access user's task
        result = get_task_by_id(
            db=db_session, task_id=task.id, user_id=other_user.id
        )
        assert result is None, "Other user should not be able to access this task"


# ===========================================================================
# Phase 3: get_today_tasks
# ===========================================================================

class TestGetTodayTasks:
    def test_empty_today_tasks(self, db_session: Session, user: User) -> None:
        """Returns empty list when user has no tasks today."""
        tasks = get_today_tasks(db=db_session, user=user)
        assert tasks == []

    def test_single_task_today(self, db_session: Session, user: User) -> None:
        """A task due today is returned."""
        import pytz
        from bot.utils.datetime_utils import combine_to_utc
        from datetime import date as date_cls, time as time_cls

        tz = pytz.timezone(user.timezone)
        today = datetime.now(tz).date()
        due_utc = combine_to_utc(today, time_cls(10, 0), user.timezone)

        task = create_task(db=db_session, user=user, title="Today's task", due_at_utc=due_utc)
        db_session.commit()

        tasks = get_today_tasks(db=db_session, user=user)
        assert len(tasks) == 1
        assert tasks[0].id == task.id

    def test_chronological_ordering(self, db_session: Session, user: User) -> None:
        """Tasks due today are ordered chronologically (earliest first)."""
        import pytz
        from bot.utils.datetime_utils import combine_to_utc
        from datetime import time as time_cls

        tz = pytz.timezone(user.timezone)
        today = datetime.now(tz).date()

        t_late = create_task(
            db=db_session, user=user, title="Late",
            due_at_utc=combine_to_utc(today, time_cls(20, 0), user.timezone)
        )
        t_early = create_task(
            db=db_session, user=user, title="Early",
            due_at_utc=combine_to_utc(today, time_cls(8, 0), user.timezone)
        )
        t_mid = create_task(
            db=db_session, user=user, title="Mid",
            due_at_utc=combine_to_utc(today, time_cls(12, 0), user.timezone)
        )
        db_session.commit()

        tasks = get_today_tasks(db=db_session, user=user)
        assert len(tasks) == 3
        assert [t.title for t in tasks] == ["Early", "Mid", "Late"]

    def test_includes_completed_and_pending_tasks(self, db_session: Session, user: User) -> None:
        """Both pending and completed tasks are returned for today."""
        import pytz
        from bot.utils.datetime_utils import combine_to_utc
        from datetime import time as time_cls

        tz = pytz.timezone(user.timezone)
        today = datetime.now(tz).date()

        t1 = create_task(
            db=db_session, user=user, title="Pending task",
            due_at_utc=combine_to_utc(today, time_cls(9, 0), user.timezone)
        )
        t2 = create_task(
            db=db_session, user=user, title="Completed task",
            due_at_utc=combine_to_utc(today, time_cls(11, 0), user.timezone)
        )
        t2.status = TaskStatus.completed
        db_session.commit()

        tasks = get_today_tasks(db=db_session, user=user)
        assert len(tasks) == 2
        statuses = {t.status for t in tasks}
        assert TaskStatus.pending in statuses
        assert TaskStatus.completed in statuses

    def test_today_boundary_isolation(self, db_session: Session, user: User) -> None:
        """Tasks from yesterday or tomorrow must NOT appear in today's tasks."""
        import pytz
        from bot.utils.datetime_utils import combine_to_utc
        from datetime import time as time_cls

        tz = pytz.timezone(user.timezone)
        today = datetime.now(tz).date()
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)

        # Yesterday 23:59 local
        create_task(db=db_session, user=user, title="Yesterday",
                    due_at_utc=combine_to_utc(yesterday, time_cls(23, 59), user.timezone))
        # Today 00:01 local
        t_today = create_task(db=db_session, user=user, title="Today",
                              due_at_utc=combine_to_utc(today, time_cls(0, 1), user.timezone))
        # Tomorrow 00:01 local
        create_task(db=db_session, user=user, title="Tomorrow",
                    due_at_utc=combine_to_utc(tomorrow, time_cls(0, 1), user.timezone))
        db_session.commit()

        tasks = get_today_tasks(db=db_session, user=user)
        assert len(tasks) == 1
        assert tasks[0].title == "Today"

    def test_user_ownership_isolation(
        self, db_session: Session, user: User, other_user: User
    ) -> None:
        """User A cannot see User B's today tasks."""
        import pytz
        from bot.utils.datetime_utils import combine_to_utc
        from datetime import time as time_cls

        tz = pytz.timezone(user.timezone)
        today = datetime.now(tz).date()

        create_task(db=db_session, user=other_user, title="Other's task",
                    due_at_utc=combine_to_utc(today, time_cls(10, 0), other_user.timezone))
        create_task(db=db_session, user=user, title="My task",
                    due_at_utc=combine_to_utc(today, time_cls(10, 0), user.timezone))
        db_session.commit()

        my_tasks = get_today_tasks(db=db_session, user=user)
        assert len(my_tasks) == 1
        assert my_tasks[0].title == "My task"


# ===========================================================================
# Phase 3: get_upcoming_tasks
# ===========================================================================

class TestGetUpcomingTasks:
    def test_empty_upcoming_tasks(self, db_session: Session, user: User) -> None:
        """Returns empty list when there are no upcoming tasks."""
        tasks = get_upcoming_tasks(db=db_session, user=user, days=7)
        assert tasks == []

    def test_window_boundary(self, db_session: Session, user: User) -> None:
        """Tasks within 7 days are included; tasks at 8+ days are excluded."""
        import pytz
        from bot.utils.datetime_utils import combine_to_utc
        from datetime import time as time_cls

        tz = pytz.timezone(user.timezone)
        today = datetime.now(tz).date()

        # Day 3 (within window)
        t_in = create_task(db=db_session, user=user, title="Day 3 task",
                           due_at_utc=combine_to_utc(today + timedelta(days=3), time_cls(12, 0), user.timezone))
        # Day 7 (at boundary)
        t_boundary = create_task(db=db_session, user=user, title="Day 7 task",
                                 due_at_utc=combine_to_utc(today + timedelta(days=7), time_cls(12, 0), user.timezone))
        # Day 9 (outside window)
        create_task(db=db_session, user=user, title="Day 9 task",
                    due_at_utc=combine_to_utc(today + timedelta(days=9), time_cls(12, 0), user.timezone))
        db_session.commit()

        tasks = get_upcoming_tasks(db=db_session, user=user, days=7)
        titles = [t.title for t in tasks]
        assert "Day 3 task" in titles
        assert "Day 7 task" in titles
        assert "Day 9 task" not in titles

    def test_only_pending_tasks_included(self, db_session: Session, user: User) -> None:
        """Completed or cancelled tasks must NOT appear in upcoming list."""
        import pytz
        from bot.utils.datetime_utils import combine_to_utc
        from datetime import time as time_cls

        tz = pytz.timezone(user.timezone)
        today = datetime.now(tz).date()

        t_pending = create_task(db=db_session, user=user, title="Pending",
                                due_at_utc=combine_to_utc(today + timedelta(days=2), time_cls(10, 0), user.timezone))
        t_completed = create_task(db=db_session, user=user, title="Completed",
                                  due_at_utc=combine_to_utc(today + timedelta(days=2), time_cls(12, 0), user.timezone))
        t_completed.status = TaskStatus.completed
        t_cancelled = create_task(db=db_session, user=user, title="Cancelled",
                                  due_at_utc=combine_to_utc(today + timedelta(days=2), time_cls(14, 0), user.timezone))
        t_cancelled.status = TaskStatus.cancelled
        db_session.commit()

        tasks = get_upcoming_tasks(db=db_session, user=user, days=7)
        assert len(tasks) == 1
        assert tasks[0].title == "Pending"

    def test_chronological_ordering(self, db_session: Session, user: User) -> None:
        """Upcoming tasks are ordered ascending by due_at."""
        import pytz
        from bot.utils.datetime_utils import combine_to_utc
        from datetime import time as time_cls

        tz = pytz.timezone(user.timezone)
        today = datetime.now(tz).date()

        create_task(db=db_session, user=user, title="In 4 days",
                    due_at_utc=combine_to_utc(today + timedelta(days=4), time_cls(10, 0), user.timezone))
        create_task(db=db_session, user=user, title="Tomorrow",
                    due_at_utc=combine_to_utc(today + timedelta(days=1), time_cls(10, 0), user.timezone))
        create_task(db=db_session, user=user, title="In 2 days",
                    due_at_utc=combine_to_utc(today + timedelta(days=2), time_cls(10, 0), user.timezone))
        db_session.commit()

        tasks = get_upcoming_tasks(db=db_session, user=user, days=7)
        assert [t.title for t in tasks] == ["Tomorrow", "In 2 days", "In 4 days"]

    def test_user_ownership_isolation(
        self, db_session: Session, user: User, other_user: User
    ) -> None:
        """User A cannot see User B's upcoming tasks."""
        import pytz
        from bot.utils.datetime_utils import combine_to_utc
        from datetime import time as time_cls

        tz = pytz.timezone(user.timezone)
        today = datetime.now(tz).date()

        create_task(db=db_session, user=other_user, title="Other upcoming",
                    due_at_utc=combine_to_utc(today + timedelta(days=2), time_cls(10, 0), other_user.timezone))
        create_task(db=db_session, user=user, title="My upcoming",
                    due_at_utc=combine_to_utc(today + timedelta(days=2), time_cls(10, 0), user.timezone))
        db_session.commit()

        tasks = get_upcoming_tasks(db=db_session, user=user, days=7)
        assert len(tasks) == 1
        assert tasks[0].title == "My upcoming"


# ===========================================================================
# Phase 4: complete_task
# ===========================================================================

class TestCompleteTask:
    def test_complete_pending_task(self, db_session: Session, user: User) -> None:
        task = create_task(db=db_session, user=user, title="Do laundry", due_at_utc=_future_utc())
        db_session.commit()

        completed = complete_task(db=db_session, task=task)
        db_session.commit()

        assert completed.status == TaskStatus.completed
        assert completed.completed_at is not None
        assert completed.completed_at.tzinfo is not None

    def test_complete_already_completed_raises(self, db_session: Session, user: User) -> None:
        task = create_task(db=db_session, user=user, title="Already done", due_at_utc=_future_utc())
        complete_task(db=db_session, task=task)
        db_session.commit()

        with pytest.raises(ValueError, match="already completed"):
            complete_task(db=db_session, task=task)

    def test_complete_cancelled_task_raises(self, db_session: Session, user: User) -> None:
        task = create_task(db=db_session, user=user, title="Cancelled item", due_at_utc=_future_utc())
        delete_task(db=db_session, task=task)
        db_session.commit()

        with pytest.raises(ValueError, match="cancelled"):
            complete_task(db=db_session, task=task)


# ===========================================================================
# Phase 4: delete_task
# ===========================================================================

class TestDeleteTask:
    def test_soft_delete_sets_status_cancelled(self, db_session: Session, user: User) -> None:
        task = create_task(db=db_session, user=user, title="Delete me", due_at_utc=_future_utc())
        db_session.commit()

        deleted = delete_task(db=db_session, task=task)
        db_session.commit()

        assert deleted.status == TaskStatus.cancelled
        # Row still in DB
        retrieved = db_session.query(Task).filter_by(id=task.id).first()
        assert retrieved is not None
        assert retrieved.status == TaskStatus.cancelled

    def test_delete_already_cancelled_raises(self, db_session: Session, user: User) -> None:
        task = create_task(db=db_session, user=user, title="Double cancel", due_at_utc=_future_utc())
        delete_task(db=db_session, task=task)
        db_session.commit()

        with pytest.raises(ValueError, match="already cancelled"):
            delete_task(db=db_session, task=task)

    def test_hard_delete_removes_row(self, db_session: Session, user: User) -> None:
        task = create_task(db=db_session, user=user, title="Hard delete me", due_at_utc=_future_utc())
        db_session.commit()
        task_id = task.id

        delete_task(db=db_session, task=task, hard_delete=True)
        db_session.commit()

        retrieved = db_session.query(Task).filter_by(id=task_id).first()
        assert retrieved is None


# ===========================================================================
# Phase 4: edit_task
# ===========================================================================

class TestEditTask:
    def test_edit_title_only(self, db_session: Session, user: User) -> None:
        due = _future_utc(2)
        task = create_task(db=db_session, user=user, title="Original title", due_at_utc=due, priority=TaskPriority.low)
        db_session.commit()

        edited = edit_task(db=db_session, task=task, title="New title")
        db_session.commit()

        assert edited.title == "New title"
        assert edited.due_at == due
        assert edited.priority == TaskPriority.low

    def test_edit_due_at_only(self, db_session: Session, user: User) -> None:
        due_orig = _future_utc(1)
        due_new = _future_utc(5)
        task = create_task(db=db_session, user=user, title="Keep title", due_at_utc=due_orig, priority=TaskPriority.medium)
        task.reminder_sent = True
        db_session.commit()

        edited = edit_task(db=db_session, task=task, due_at_utc=due_new)
        db_session.commit()

        assert edited.title == "Keep title"
        assert edited.due_at == due_new
        assert edited.reminder_sent is False  # reset on due_at change

    def test_edit_priority_only(self, db_session: Session, user: User) -> None:
        due = _future_utc()
        task = create_task(db=db_session, user=user, title="Keep title", due_at_utc=due, priority=TaskPriority.low)
        db_session.commit()

        edited = edit_task(db=db_session, task=task, priority=TaskPriority.high)
        db_session.commit()

        assert edited.priority == TaskPriority.high
        assert edited.title == "Keep title"

    def test_edit_multiple_fields(self, db_session: Session, user: User) -> None:
        task = create_task(db=db_session, user=user, title="Orig", due_at_utc=_future_utc(1), priority=TaskPriority.low)
        db_session.commit()

        new_due = _future_utc(3)
        edited = edit_task(db=db_session, task=task, title="Updated", due_at_utc=new_due, priority=TaskPriority.high)
        db_session.commit()

        assert edited.title == "Updated"
        assert edited.due_at == new_due
        assert edited.priority == TaskPriority.high

    def test_edit_empty_title_raises(self, db_session: Session, user: User) -> None:
        task = create_task(db=db_session, user=user, title="Valid", due_at_utc=_future_utc())
        db_session.commit()

        with pytest.raises(ValueError, match="cannot be empty"):
            edit_task(db=db_session, task=task, title="   ")

    def test_edit_title_too_long_raises(self, db_session: Session, user: User) -> None:
        task = create_task(db=db_session, user=user, title="Valid", due_at_utc=_future_utc())
        db_session.commit()

        with pytest.raises(ValueError, match="exceeds maximum length"):
            edit_task(db=db_session, task=task, title="X" * (MAX_TITLE_LENGTH + 1))

    def test_edit_naive_datetime_raises(self, db_session: Session, user: User) -> None:
        task = create_task(db=db_session, user=user, title="Valid", due_at_utc=_future_utc())
        db_session.commit()

        with pytest.raises(ValueError, match="timezone-aware"):
            edit_task(db=db_session, task=task, due_at_utc=datetime(2026, 12, 1, 10, 0))

    def test_edit_cancelled_task_raises(self, db_session: Session, user: User) -> None:
        task = create_task(db=db_session, user=user, title="Valid", due_at_utc=_future_utc())
        delete_task(db=db_session, task=task)
        db_session.commit()

        with pytest.raises(ValueError, match="cancelled"):
            edit_task(db=db_session, task=task, title="Revived")


# ===========================================================================
# Phase 4: get_pending_tasks
# ===========================================================================

class TestGetPendingTasks:
    def test_empty_pending_tasks(self, db_session: Session, user: User) -> None:
        tasks = get_pending_tasks(db=db_session, user=user)
        assert tasks == []

    def test_filters_completed_and_cancelled(self, db_session: Session, user: User) -> None:
        t_pending = create_task(db=db_session, user=user, title="Pending", due_at_utc=_future_utc(1))
        t_done = create_task(db=db_session, user=user, title="Done", due_at_utc=_future_utc(2))
        complete_task(db=db_session, task=t_done)
        t_cancelled = create_task(db=db_session, user=user, title="Cancel", due_at_utc=_future_utc(3))
        delete_task(db=db_session, task=t_cancelled)
        db_session.commit()

        pending = get_pending_tasks(db=db_session, user=user)
        assert len(pending) == 1
        assert pending[0].id == t_pending.id

    def test_chronological_ordering(self, db_session: Session, user: User) -> None:
        t2 = create_task(db=db_session, user=user, title="Later", due_at_utc=_future_utc(4))
        t1 = create_task(db=db_session, user=user, title="Earlier", due_at_utc=_future_utc(1))
        db_session.commit()

        pending = get_pending_tasks(db=db_session, user=user)
        assert [t.title for t in pending] == ["Earlier", "Later"]

    def test_user_ownership_isolation(
        self, db_session: Session, user: User, other_user: User
    ) -> None:
        create_task(db=db_session, user=other_user, title="Other's pending", due_at_utc=_future_utc(1))
        create_task(db=db_session, user=user, title="My pending", due_at_utc=_future_utc(2))
        db_session.commit()

        my_pending = get_pending_tasks(db=db_session, user=user)
        assert len(my_pending) == 1
        assert my_pending[0].title == "My pending"


# ===========================================================================
# Phase 5: get_due_tasks & mark_reminder_sent
# ===========================================================================

class TestGetDueTasks:
    def test_detects_due_task(self, db_session: Session, user: User) -> None:
        now = datetime.now(timezone.utc)
        due_time = now - timedelta(minutes=5)
        task = create_task(db=db_session, user=user, title="Due task", due_at_utc=due_time)
        db_session.commit()

        due_tasks = get_due_tasks(db=db_session, now_utc=now)
        assert len(due_tasks) == 1
        assert due_tasks[0].id == task.id
        assert due_tasks[0].user.telegram_user_id == user.telegram_user_id

    def test_excludes_future_task(self, db_session: Session, user: User) -> None:
        now = datetime.now(timezone.utc)
        future_time = now + timedelta(minutes=15)
        create_task(db=db_session, user=user, title="Future task", due_at_utc=future_time)
        db_session.commit()

        due_tasks = get_due_tasks(db=db_session, now_utc=now)
        assert due_tasks == []

    def test_excludes_completed_task(self, db_session: Session, user: User) -> None:
        now = datetime.now(timezone.utc)
        past_time = now - timedelta(minutes=10)
        task = create_task(db=db_session, user=user, title="Done task", due_at_utc=past_time)
        complete_task(db=db_session, task=task)
        db_session.commit()

        due_tasks = get_due_tasks(db=db_session, now_utc=now)
        assert due_tasks == []

    def test_excludes_cancelled_task(self, db_session: Session, user: User) -> None:
        now = datetime.now(timezone.utc)
        past_time = now - timedelta(minutes=10)
        task = create_task(db=db_session, user=user, title="Cancelled task", due_at_utc=past_time)
        delete_task(db=db_session, task=task)
        db_session.commit()

        due_tasks = get_due_tasks(db=db_session, now_utc=now)
        assert due_tasks == []

    def test_excludes_already_reminded_task(self, db_session: Session, user: User) -> None:
        now = datetime.now(timezone.utc)
        past_time = now - timedelta(minutes=10)
        task = create_task(db=db_session, user=user, title="Reminded task", due_at_utc=past_time)
        task.reminder_sent = True
        db_session.commit()

        due_tasks = get_due_tasks(db=db_session, now_utc=now)
        assert due_tasks == []

    def test_excludes_task_without_due_at(self, db_session: Session, user: User) -> None:
        now = datetime.now(timezone.utc)
        task = create_task(db=db_session, user=user, title="No due", due_at_utc=now - timedelta(hours=1))
        task.due_at = None
        db_session.commit()

        due_tasks = get_due_tasks(db=db_session, now_utc=now)
        assert due_tasks == []

    def test_chronological_ordering(self, db_session: Session, user: User) -> None:
        now = datetime.now(timezone.utc)
        t_older = create_task(db=db_session, user=user, title="Older due", due_at_utc=now - timedelta(minutes=30))
        t_recent = create_task(db=db_session, user=user, title="Recent due", due_at_utc=now - timedelta(minutes=5))
        db_session.commit()

        due_tasks = get_due_tasks(db=db_session, now_utc=now)
        assert len(due_tasks) == 2
        assert [t.id for t in due_tasks] == [t_older.id, t_recent.id]

    def test_naive_datetime_raises_value_error(self, db_session: Session) -> None:
        naive_now = datetime(2026, 10, 7, 10, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            get_due_tasks(db=db_session, now_utc=naive_now)

    def test_user_ownership_and_relationship(
        self, db_session: Session, user: User, other_user: User
    ) -> None:
        now = datetime.now(timezone.utc)
        t_my = create_task(db=db_session, user=user, title="My task", due_at_utc=now - timedelta(minutes=5))
        t_other = create_task(db=db_session, user=other_user, title="Other task", due_at_utc=now - timedelta(minutes=10))
        db_session.commit()

        due_tasks = get_due_tasks(db=db_session, now_utc=now)
        assert len(due_tasks) == 2
        # Tasks are ordered by due_at: t_other is 10 mins ago, t_my is 5 mins ago
        assert due_tasks[0].id == t_other.id
        assert due_tasks[0].user.telegram_user_id == other_user.telegram_user_id
        assert due_tasks[1].id == t_my.id
        assert due_tasks[1].user.telegram_user_id == user.telegram_user_id


class TestMarkReminderSent:
    def test_mark_reminder_sent_success(self, db_session: Session, user: User) -> None:
        now = datetime.now(timezone.utc)
        task = create_task(db=db_session, user=user, title="Task to remind", due_at_utc=now)
        db_session.commit()
        assert task.reminder_sent is False

        updated = mark_reminder_sent(db=db_session, task=task)
        db_session.commit()

        assert updated.reminder_sent is True
        # Verify persisted in database
        refreshed = db_session.query(Task).filter_by(id=task.id).one()
        assert refreshed.reminder_sent is True

