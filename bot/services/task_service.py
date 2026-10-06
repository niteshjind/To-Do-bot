"""
services/task_service.py — Task business logic.

Phase 2 implements: create_task()
Phase 3 will add:  get_today_tasks(), get_upcoming_tasks()
Phase 4 will add:  complete_task(), edit_task(), cancel_task()
Phase 5 will add:  get_due_tasks() (used by scheduler)

Design rules:
  • No Telegram objects imported here — pure Python + SQLAlchemy.
  • All datetimes accepted/returned here are UTC-aware.
  • The service layer is the only place that touches Task ORM objects.
  • Handlers call service functions; they never query the DB directly.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from bot.database.models import Task, TaskPriority, TaskStatus, User
from bot.utils.datetime_utils import get_day_boundaries_utc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task creation
# ---------------------------------------------------------------------------

MAX_TITLE_LENGTH = 500  # Enforce in service AND handler for defence-in-depth


def create_task(
    db: Session,
    user: User,
    title: str,
    due_at_utc: datetime,
    priority: TaskPriority = TaskPriority.medium,
) -> Task:
    """
    Create and persist a new pending task for the given user.

    Args:
        db:          Active SQLAlchemy session (commit happens in get_db()).
        user:        Owner of the task — must already exist in the DB.
        title:       Task description. Stripped of leading/trailing whitespace.
        due_at_utc:  Reminder datetime as a UTC-aware datetime.
        priority:    Task priority (default: medium).

    Returns:
        The newly created :class:`Task` ORM instance with ``id`` set.

    Raises:
        ValueError: If ``title`` is empty or exceeds ``MAX_TITLE_LENGTH``.
        ValueError: If ``due_at_utc`` is not timezone-aware.
    """
    # --- Input validation (defence-in-depth; handlers also validate) ---
    title = title.strip()
    if not title:
        raise ValueError("Task title cannot be empty.")
    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError(
            f"Task title exceeds maximum length of {MAX_TITLE_LENGTH} characters."
        )
    if due_at_utc.tzinfo is None:
        raise ValueError(
            "due_at_utc must be a timezone-aware datetime. "
            "Use combine_to_utc() from datetime_utils to create it."
        )

    task = Task(
        user_id=user.id,
        title=title,
        due_at=due_at_utc,
        priority=priority,
        status=TaskStatus.pending,
        reminder_sent=False,
    )
    db.add(task)
    db.flush()  # Assigns task.id without committing the outer transaction

    logger.info(
        "Task created: id=%s user_id=%s priority=%s due_at=%s title=%r",
        task.id,
        user.id,
        priority.value,
        due_at_utc.isoformat(),
        title[:50],
    )
    return task


# ---------------------------------------------------------------------------
# Phase 3: Task listing
# ---------------------------------------------------------------------------


def get_today_tasks(
    db: Session, user: User, target_date: Optional[date] = None
) -> list[Task]:
    """
    Return all tasks due today in the user's timezone, ordered chronologically.

    Includes pending, completed, and cancelled tasks so the user sees their
    full day's itinerary and completion rate.
    """
    start_utc, end_utc = get_day_boundaries_utc(user.timezone, target_date)
    return (
        db.query(Task)
        .filter(
            Task.user_id == user.id,
            Task.due_at >= start_utc,
            Task.due_at <= end_utc,
        )
        .order_by(Task.due_at.asc(), Task.id.asc())
        .all()
    )


def get_upcoming_tasks(
    db: Session,
    user: User,
    days: int = 7,
    reference_date: Optional[date] = None,
) -> list[Task]:
    """
    Return upcoming pending tasks for the user within the specified window (in days).

    Covers from the start of today through end of (today + days) in user's timezone.
    Only includes pending tasks (completed and cancelled are omitted).
    Ordered chronologically by reminder time.
    """
    import pytz

    local_tz = pytz.timezone(user.timezone)
    ref_date = reference_date or datetime.now(local_tz).date()
    start_utc, _ = get_day_boundaries_utc(user.timezone, ref_date)

    end_date = ref_date + timedelta(days=days)
    _, end_utc = get_day_boundaries_utc(user.timezone, end_date)

    return (
        db.query(Task)
        .filter(
            Task.user_id == user.id,
            Task.status == TaskStatus.pending,
            Task.due_at >= start_utc,
            Task.due_at <= end_utc,
        )
        .order_by(Task.due_at.asc(), Task.id.asc())
        .all()
    )


# Phase 4: actions
def complete_task(db: Session, task: Task) -> Task:  # type: ignore[return]
    """Mark a task as completed. Implemented in Phase 4."""
    raise NotImplementedError("Implemented in Phase 4")


def cancel_task(db: Session, task: Task) -> Task:  # type: ignore[return]
    """Mark a task as cancelled. Implemented in Phase 4."""
    raise NotImplementedError("Implemented in Phase 4")


def get_task_by_id(
    db: Session, task_id: int, user_id: int
) -> Optional[Task]:
    """
    Fetch a task by ID, verifying it belongs to the given user.

    Returns None if the task doesn't exist or belongs to a different user.
    Used in Phase 4 and beyond for all task actions.
    """
    return (
        db.query(Task)
        .filter(Task.id == task_id, Task.user_id == user_id)
        .first()
    )
