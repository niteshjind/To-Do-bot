"""
services/user_service.py — User-related business logic.

Responsibilities:
  • get_or_create_user(): upsert a user record on every Telegram interaction
  • get_user_by_telegram_id(): lookup helper used by other services
  • get_user_settings(): snapshot of user preferences as a detached DTO
  • update_timezone(): update user's IANA timezone preference
  • update_reminders_enabled(): toggle task reminder notifications
  • update_daily_summary_enabled(): toggle daily task summary notifications
  • update_daily_summary_time(): configure local time for daily task summary
  • update_last_summary_date(): record date of last successful daily summary

No Telegram objects are imported here — pure Python + SQLAlchemy.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Union

import pytz
from sqlalchemy.orm import Session

from bot.database.models import User

logger = logging.getLogger(__name__)

# Strict 24-hour time format: HH:MM from 00:00 to 23:59
SUMMARY_TIME_REGEX = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# ISO date format: YYYY-MM-DD
SUMMARY_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Data Transfer Object (DTO)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UserSettingsDTO:
    """
    Safe detached snapshot of a user's settings and preferences.

    Safe to pass across handler boundaries, async calls, or after session close.
    """

    user_id: int
    telegram_user_id: int
    timezone: str
    reminders_enabled: bool
    daily_summary_enabled: bool
    daily_summary_time: str
    last_summary_date: Optional[str]

    @classmethod
    def from_orm(cls, user: User) -> "UserSettingsDTO":
        """Create a UserSettingsDTO snapshot from a User ORM instance."""
        return cls(
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            timezone=user.timezone,
            reminders_enabled=user.reminders_enabled,
            daily_summary_enabled=user.daily_summary_enabled,
            daily_summary_time=user.daily_summary_time,
            last_summary_date=user.last_summary_date,
        )


# ---------------------------------------------------------------------------
# User retrieval and creation
# ---------------------------------------------------------------------------

def get_or_create_user(
    db: Session,
    telegram_user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
) -> User:
    """
    Return the User for this telegram_user_id, creating it if it doesn't exist.

    Also keeps username / first_name in sync with the latest Telegram data
    (these can change if the user updates their Telegram profile).

    Args:
        db:               Active SQLAlchemy session.
        telegram_user_id: Telegram's integer user ID.
        username:         Telegram @username (optional, may be None).
        first_name:       Telegram display name (optional).

    Returns:
        The User ORM instance (already added to session; commit happens in get_db()).
    """
    user: Optional[User] = (
        db.query(User)
        .filter(User.telegram_user_id == telegram_user_id)
        .first()
    )

    if user is None:
        # First time we see this user — create their record
        user = User(
            telegram_user_id=telegram_user_id,
            username=username,
            first_name=first_name,
            # timezone defaults to "Asia/Kolkata" as declared in the model
            # notification preferences default to True / "09:00" as declared in the model
        )
        db.add(user)
        db.flush()  # Assigns user.id without committing the transaction
        logger.info(
            "New user created: telegram_user_id=%s username=%s",
            telegram_user_id,
            username,
        )
    else:
        # Update profile fields if they changed on Telegram's side
        changed = False
        if user.username != username:
            user.username = username
            changed = True
        if user.first_name != first_name:
            user.first_name = first_name
            changed = True
        if changed:
            db.flush()
            logger.debug(
                "User profile updated: telegram_user_id=%s", telegram_user_id
            )

    return user


def get_user_by_telegram_id(
    db: Session, telegram_user_id: int
) -> Optional[User]:
    """
    Fetch a user by their Telegram ID without creating one.

    Returns None if the user has never used the bot.
    """
    return (
        db.query(User)
        .filter(User.telegram_user_id == telegram_user_id)
        .first()
    )


# ---------------------------------------------------------------------------
# Phase 7: Settings & Preferences Services
# ---------------------------------------------------------------------------

def get_user_settings(
    user_or_db: Union[Session, User],
    user: Optional[User] = None,
) -> UserSettingsDTO:
    """
    Return a detached UserSettingsDTO snapshot of the user's settings.

    Can be called as `get_user_settings(user)` or `get_user_settings(db, user)`.
    """
    target_user = user if user is not None else user_or_db
    if not isinstance(target_user, User):
        raise ValueError("A valid User instance must be provided.")
    return UserSettingsDTO.from_orm(target_user)


def get_user_settings_by_telegram_id(
    db: Session, telegram_user_id: int
) -> Optional[UserSettingsDTO]:
    """
    Fetch settings for a user by telegram_user_id, or None if user not found.
    """
    user = get_user_by_telegram_id(db, telegram_user_id)
    if user is None:
        return None
    return UserSettingsDTO.from_orm(user)


def update_timezone(db: Session, user: User, tz_string: str) -> User:
    """
    Update the user's timezone preference.

    Args:
        db:        Active SQLAlchemy session.
        user:      User ORM instance to update.
        tz_string: IANA timezone string (e.g. "Asia/Kolkata", "UTC", "America/New_York").

    Raises:
        ValueError: If tz_string is not a valid IANA timezone.

    Returns:
        Updated User instance.
    """
    try:
        pytz.timezone(tz_string)  # Validate before saving
    except pytz.exceptions.UnknownTimeZoneError:
        raise ValueError(f"Unknown timezone: '{tz_string}'")

    user.timezone = tz_string
    db.flush()
    logger.info(
        "Timezone updated for user %s: %s", user.telegram_user_id, tz_string
    )
    return user


def update_reminders_enabled(db: Session, user: User, enabled: bool) -> User:
    """
    Update the user's reminder notification preference.

    Args:
        db:      Active SQLAlchemy session.
        user:    User ORM instance to update.
        enabled: True to enable reminders, False to disable.

    Raises:
        ValueError: If enabled is not a boolean.

    Returns:
        Updated User instance.
    """
    if not isinstance(enabled, bool):
        raise ValueError(f"reminders_enabled must be a boolean, got {type(enabled).__name__}")

    user.reminders_enabled = enabled
    db.flush()
    logger.info(
        "reminders_enabled updated for user %s: %s",
        user.telegram_user_id,
        enabled,
    )
    return user


def update_daily_summary_enabled(db: Session, user: User, enabled: bool) -> User:
    """
    Update the user's daily summary preference.

    Args:
        db:      Active SQLAlchemy session.
        user:    User ORM instance to update.
        enabled: True to enable daily summaries, False to disable.

    Raises:
        ValueError: If enabled is not a boolean.

    Returns:
        Updated User instance.
    """
    if not isinstance(enabled, bool):
        raise ValueError(f"daily_summary_enabled must be a boolean, got {type(enabled).__name__}")

    user.daily_summary_enabled = enabled
    db.flush()
    logger.info(
        "daily_summary_enabled updated for user %s: %s",
        user.telegram_user_id,
        enabled,
    )
    return user


def update_daily_summary_time(db: Session, user: User, time_str: str) -> User:
    """
    Update the user's daily summary scheduled time in local 24-hour format.

    Args:
        db:       Active SQLAlchemy session.
        user:     User ORM instance to update.
        time_str: 24-hour time string strictly formatted as 'HH:MM' (00:00 to 23:59).

    Raises:
        ValueError: If time_str is not a valid 24-hour HH:MM time.

    Returns:
        Updated User instance.
    """
    if not isinstance(time_str, str) or not SUMMARY_TIME_REGEX.match(time_str):
        raise ValueError(
            f"Invalid summary time: '{time_str}'. Expected 'HH:MM' in 24-hour format (00:00 to 23:59)."
        )

    user.daily_summary_time = time_str
    db.flush()
    logger.info(
        "daily_summary_time updated for user %s: %s",
        user.telegram_user_id,
        time_str,
    )
    return user


def update_last_summary_date(
    db: Session,
    user: User,
    summary_date: Optional[Union[str, date]],
) -> User:
    """
    Update the recorded date of the user's last delivered daily summary.

    Args:
        db:           Active SQLAlchemy session.
        user:         User ORM instance to update.
        summary_date: Either a date instance, 'YYYY-MM-DD' string, or None.

    Raises:
        ValueError: If summary_date is an invalid date string.

    Returns:
        Updated User instance.
    """
    if summary_date is None:
        val_str = None
    elif isinstance(summary_date, date):
        val_str = summary_date.isoformat()
    elif isinstance(summary_date, str):
        if not SUMMARY_DATE_REGEX.match(summary_date):
            raise ValueError(
                f"Invalid summary date: '{summary_date}'. Expected 'YYYY-MM-DD' or None."
            )
        try:
            datetime.strptime(summary_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError(
                f"Invalid summary date: '{summary_date}'. Not a valid calendar date."
            )
        val_str = summary_date
    else:
        raise ValueError(
            f"Invalid summary date type: {type(summary_date).__name__}. Expected date, str, or None."
        )

    user.last_summary_date = val_str
    db.flush()
    logger.info(
        "last_summary_date updated for user %s: %s",
        user.telegram_user_id,
        val_str,
    )
    return user
