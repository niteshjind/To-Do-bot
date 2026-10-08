"""
database/models.py — SQLAlchemy ORM models.

Two tables:
  • users  — one row per Telegram user
  • tasks  — many rows per user

All DATETIME columns store UTC.  Timezone conversion for display
happens in the service/utils layer, never here.

Enums are plain Python str-enums so they serialize cleanly to SQLite
VARCHAR and PostgreSQL ENUM alike.
"""

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, relationship


# ---------------------------------------------------------------------------
# Helpers & Custom Types
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """
    Platform-independent DateTime type that stores UTC in the database
    and always returns timezone-aware UTC datetime instances in Python.
    """
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("Cannot store naive datetime; must be timezone-aware UTC.")
            return value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    cancelled = "cancelled"


class TaskPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TaskRecurrence(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


RECURRENCE_LABELS = {
    TaskRecurrence.daily.value: "Daily",
    TaskRecurrence.weekly.value: "Weekly",
    TaskRecurrence.monthly.value: "Monthly",
}

RECURRENCE_ICONS = {
    TaskRecurrence.daily.value: "🔁",
    TaskRecurrence.weekly.value: "🔁",
    TaskRecurrence.monthly.value: "🔁",
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(Base):
    """
    Represents a Telegram user who has interacted with the bot.

    Created automatically on the first /start (or any command) via
    user_service.get_or_create_user().
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Telegram's own integer user ID — this is the natural lookup key.
    telegram_user_id = Column(
        BigInteger, unique=True, nullable=False, index=True
    )

    # Optional Telegram profile fields; kept in sync on every interaction.
    username = Column(String(64), nullable=True)
    first_name = Column(String(128), nullable=True)

    # IANA timezone string (e.g. "Asia/Kolkata").
    # Default set to Asia/Kolkata per F1 decision.
    timezone = Column(String(64), nullable=False, default="Asia/Kolkata")

    created_at = Column(
        UTCDateTime, nullable=False, default=_utcnow
    )
    updated_at = Column(
        UTCDateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    # Relationship — access user.tasks to get all tasks for this user.
    tasks = relationship(
        "Task", back_populates="user", lazy="select", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<User id={self.id} telegram_user_id={self.telegram_user_id} "
            f"username={self.username!r}>"
        )


class Task(Base):
    """
    A single to-do item owned by a User.

    Key fields:
      • due_at         — when the reminder should fire (UTC)
      • reminder_sent  — prevents duplicate reminder delivery
      • snoozed_until  — set when user snoozes; clears reminder_sent flag
      • recurrence     — reserved for post-MVP recurring tasks
    """

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title = Column(String(512), nullable=False)

    status = Column(
        Enum(TaskStatus),
        nullable=False,
        default=TaskStatus.pending,
    )

    priority = Column(
        Enum(TaskPriority),
        nullable=False,
        default=TaskPriority.medium,
    )

    # Stored in UTC; displayed in user's local timezone via datetime_utils.
    due_at = Column(UTCDateTime, nullable=True)

    # Reserved column — recurrence rules (e.g. "daily", "weekly").
    # No implementation in MVP; column exists so schema doesn't change later.
    recurrence = Column(String(64), nullable=True)

    # Deduplication: True after the reminder message has been sent.
    # Reset to False when task is snoozed.
    reminder_sent = Column(Boolean, nullable=False, default=False)

    # When the user snoozes, we set this to now + snooze_minutes.
    # The scheduler uses max(due_at, snoozed_until) when deciding what is "due".
    snoozed_until = Column(UTCDateTime, nullable=True)

    completed_at = Column(UTCDateTime, nullable=True)

    created_at = Column(
        UTCDateTime, nullable=False, default=_utcnow
    )
    updated_at = Column(
        UTCDateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    # Relationship
    user = relationship("User", back_populates="tasks")

    def __repr__(self) -> str:
        return (
            f"<Task id={self.id} user_id={self.user_id} "
            f"status={self.status!r} title={self.title[:30]!r}>"
        )
