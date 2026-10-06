"""
services/user_service.py — User-related business logic.

Responsibilities:
  • get_or_create_user(): upsert a user record on every Telegram interaction
  • get_user_by_telegram_id(): lookup helper used by other services
  • update_timezone(): used by /settings handler (Phase 7)

No Telegram objects are imported here — pure Python + SQLAlchemy.
"""

import logging
from typing import Optional

import pytz
from sqlalchemy.orm import Session

from bot.database.models import User

logger = logging.getLogger(__name__)


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
