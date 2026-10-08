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
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from bot.config import settings
from bot.database.models import Task, TaskPriority, TaskStatus, User
from bot.utils.datetime_utils import calculate_next_occurrence, get_day_boundaries_utc

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
    recurrence: Optional[str] = None,
) -> Task:
    """
    Create and persist a new pending task for the given user.

    Args:
        db:          Active SQLAlchemy session (commit happens in get_db()).
        user:        Owner of the task — must already exist in the DB.
        title:       Task description. Stripped of leading/trailing whitespace.
        due_at_utc:  Reminder datetime as a UTC-aware datetime.
        priority:    Task priority (default: medium).
        recurrence:  Optional recurrence rule ("daily", "weekly", "monthly", or None).

    Returns:
        The newly created :class:`Task` ORM instance with ``id`` set.

    Raises:
        ValueError: If ``title`` is empty or exceeds ``MAX_TITLE_LENGTH``.
        ValueError: If ``due_at_utc`` is not timezone-aware.
        ValueError: If ``recurrence`` is invalid.
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
    if recurrence is not None and recurrence not in {"daily", "weekly", "monthly"}:
        raise ValueError(f"Invalid recurrence: {recurrence!r}")

    task = Task(
        user_id=user.id,
        title=title,
        due_at=due_at_utc,
        priority=priority,
        status=TaskStatus.pending,
        recurrence=recurrence,
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


# ---------------------------------------------------------------------------
# Phase 4: Task Actions (/done, /delete, /edit)
# ---------------------------------------------------------------------------

def get_pending_tasks(db: Session, user: User) -> list[Task]:
    """
    Return all pending tasks for the given user, ordered chronologically.
    """
    return (
        db.query(Task)
        .filter(
            Task.user_id == user.id,
            Task.status == TaskStatus.pending,
        )
        .order_by(Task.due_at.asc(), Task.id.asc())
        .all()
    )


def get_task_by_id(
    db: Session, task_id: int, user_id: int
) -> Optional[Task]:
    """
    Fetch a task by ID, verifying it belongs to the given user.

    Returns None if the task doesn't exist or belongs to a different user.
    """
    return (
        db.query(Task)
        .filter(Task.id == task_id, Task.user_id == user_id)
        .first()
    )


def complete_task(
    db: Session,
    task: Task,
    now_utc: Optional[datetime] = None,
) -> Task:
    """
    Mark a task as completed and record completed_at in UTC.
    If the task is recurring, automatically schedule the next occurrence.

    Raises:
        ValueError: If the task is already completed or cancelled.
    """
    if task.status == TaskStatus.completed:
        raise ValueError("Task is already completed.")
    if task.status == TaskStatus.cancelled:
        raise ValueError("Task is cancelled and cannot be completed.")

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        raise ValueError("now_utc must be a timezone-aware datetime.")

    task.status = TaskStatus.completed
    task.completed_at = now_utc
    task.next_occurrence = None

    # If task has a recurrence rule, schedule the next occurrence
    if task.recurrence and task.due_at:
        user_tz = task.user.timezone if task.user else settings.TIMEZONE
        next_due_utc = calculate_next_occurrence(
            base_dt_utc=task.due_at,
            recurrence=task.recurrence,
            tz_string=user_tz,
            after_utc=now_utc,
        )
        next_task = Task(
            user_id=task.user_id,
            title=task.title,
            status=TaskStatus.pending,
            priority=task.priority,
            due_at=next_due_utc,
            recurrence=task.recurrence,
            reminder_sent=False,
            created_at=now_utc,
            updated_at=now_utc,
        )
        db.add(next_task)
        db.flush()
        task.next_occurrence = next_task
        logger.info(
            "Scheduled next recurring task: id=%s parent_id=%s due_at=%s",
            next_task.id,
            task.id,
            next_due_utc.isoformat(),
        )

    db.flush()
    logger.info("Task completed: id=%s user_id=%s", task.id, task.user_id)
    return task


def snooze_task(
    db: Session,
    task: Task,
    new_due_at_utc: datetime,
) -> Task:
    """
    Snooze a pending task to a new reminder time.

    Updates due_at, records snoozed_until, and resets reminder_sent to False
    so the scheduler will pick it up again at the new due time.

    Raises:
        ValueError: If task is completed or cancelled.
        ValueError: If new_due_at_utc is not timezone-aware.
    """
    if task.status == TaskStatus.completed:
        raise ValueError("Cannot snooze a completed task.")
    if task.status == TaskStatus.cancelled:
        raise ValueError("Cannot snooze a cancelled task.")
    if new_due_at_utc.tzinfo is None:
        raise ValueError("new_due_at_utc must be a timezone-aware datetime.")

    task.due_at = new_due_at_utc
    task.snoozed_until = new_due_at_utc
    task.reminder_sent = False
    db.flush()
    logger.info("Task snoozed: id=%s new_due=%s", task.id, new_due_at_utc.isoformat())
    return task


def delete_task(db: Session, task: Task, hard_delete: bool = False) -> Task:
    """
    Delete a task (defaults to soft delete by setting status to cancelled).

    Raises:
        ValueError: If the task is already cancelled.
    """
    if task.status == TaskStatus.cancelled:
        raise ValueError("Task is already cancelled.")

    if hard_delete:
        db.delete(task)
    else:
        task.status = TaskStatus.cancelled

    db.flush()
    logger.info("Task deleted: id=%s user_id=%s hard_delete=%s", task.id, task.user_id, hard_delete)
    return task


# Alias for backwards compatibility / semantic clarity
cancel_task = delete_task


_UNSET = object()


def edit_task(
    db: Session,
    task: Task,
    title: Optional[str] = None,
    due_at_utc: Optional[datetime] = None,
    priority: Optional[TaskPriority] = None,
    recurrence: Optional[object] = _UNSET,
) -> Task:
    """
    Edit specific fields of an existing task without altering untouched fields.

    Raises:
        ValueError: If title is empty or exceeds MAX_TITLE_LENGTH.
        ValueError: If due_at_utc is naive.
        ValueError: If task is cancelled.
        ValueError: If recurrence is invalid.
    """
    if task.status == TaskStatus.cancelled:
        raise ValueError("Cannot edit a cancelled task.")

    if title is not None:
        cleaned_title = title.strip()
        if not cleaned_title:
            raise ValueError("Task title cannot be empty.")
        if len(cleaned_title) > MAX_TITLE_LENGTH:
            raise ValueError(
                f"Task title exceeds maximum length of {MAX_TITLE_LENGTH} characters."
            )
        task.title = cleaned_title

    if due_at_utc is not None:
        if due_at_utc.tzinfo is None:
            raise ValueError("due_at_utc must be a timezone-aware datetime.")
        task.due_at = due_at_utc
        # Reset reminder sent flag if time changes so reminder can be delivered
        task.reminder_sent = False

    if priority is not None:
        task.priority = priority

    if recurrence is not _UNSET:
        if recurrence is not None and recurrence not in {"daily", "weekly", "monthly"}:
            raise ValueError(f"Invalid recurrence: {recurrence!r}")
        task.recurrence = recurrence  # type: ignore[assignment]

    db.flush()
    logger.info("Task edited: id=%s user_id=%s", task.id, task.user_id)
    return task


# ---------------------------------------------------------------------------
# Phase 5: Reminder & Scheduling Queries
# ---------------------------------------------------------------------------

def get_due_tasks(
    db: Session,
    now_utc: Optional[datetime] = None,
) -> list[Task]:
    """
    Return all pending tasks eligible for reminder delivery.

    A task is eligible if and only if:
      1. status == TaskStatus.pending
      2. reminder_sent is False
      3. due_at is not None
      4. due_at <= now_utc (defaults to current UTC time)
      5. Associated with an existing user who has a valid telegram_user_id

    Tasks are ordered chronologically by due_at ascending, then id ascending.

    Args:
        db: Active SQLAlchemy database session.
        now_utc: Reference UTC datetime to compare against (defaults to now).

    Returns:
        List of eligible Task objects with their User relationship eagerly loaded.

    Raises:
        ValueError: If now_utc is provided but naive (lacks timezone).
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        raise ValueError("now_utc must be a timezone-aware datetime.")

    return (
        db.query(Task)
        .options(joinedload(Task.user))
        .join(User, Task.user_id == User.id)
        .filter(
            Task.status == TaskStatus.pending,
            Task.reminder_sent.is_(False),
            Task.due_at.isnot(None),
            Task.due_at <= now_utc,
            User.telegram_user_id.isnot(None),
        )
        .order_by(Task.due_at.asc(), Task.id.asc())
        .all()
    )


def mark_reminder_sent(
    db: Session,
    task: Task,
) -> Task:
    """
    Mark a task's reminder as sent.

    Sets reminder_sent = True and flushes changes to the database.

    Args:
        db: Active database session.
        task: Task instance to update.

    Returns:
        The updated Task instance.
    """
    task.reminder_sent = True
    db.flush()
    logger.info("Reminder marked sent for task: id=%d", task.id)
    return task

