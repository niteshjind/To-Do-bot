"""
tests/test_user_service.py — Unit tests for user_service.py.

Tests cover:
  • Creating a new user on first interaction
  • Returning an existing user on repeat interactions (no duplicate)
  • Updating stale username / first_name automatically
  • Timezone validation in update_timezone()
  • Lookup by telegram_user_id

All tests use the in-memory `db_session` fixture from conftest.py.
No real database file is created.
"""

import pytest
from sqlalchemy.orm import Session

from bot.database.models import User
from bot.services.user_service import (
    get_or_create_user,
    get_user_by_telegram_id,
    update_timezone,
)


# ---------------------------------------------------------------------------
# get_or_create_user
# ---------------------------------------------------------------------------

class TestGetOrCreateUser:
    def test_creates_new_user(self, db_session: Session) -> None:
        """A new user record is created on first call."""
        user = get_or_create_user(
            db=db_session,
            telegram_user_id=111111,
            username="alice",
            first_name="Alice",
        )
        db_session.commit()

        assert user.id is not None
        assert user.telegram_user_id == 111111
        assert user.username == "alice"
        assert user.first_name == "Alice"

    def test_default_timezone_is_kolkata(self, db_session: Session) -> None:
        """New users get Asia/Kolkata as the default timezone (F1 decision)."""
        user = get_or_create_user(db=db_session, telegram_user_id=222222)
        db_session.commit()

        assert user.timezone == "Asia/Kolkata"

    def test_returns_existing_user_on_repeat_call(self, db_session: Session) -> None:
        """Calling get_or_create_user twice with the same ID returns the same row."""
        user_first = get_or_create_user(
            db=db_session, telegram_user_id=333333, username="bob"
        )
        db_session.commit()

        user_second = get_or_create_user(
            db=db_session, telegram_user_id=333333, username="bob"
        )
        db_session.commit()

        # Same database row — IDs must match
        assert user_first.id == user_second.id

        # Only one row should exist in the table
        count = db_session.query(User).filter_by(telegram_user_id=333333).count()
        assert count == 1

    def test_updates_username_when_changed(self, db_session: Session) -> None:
        """If a user changes their Telegram username, the DB record is updated."""
        get_or_create_user(
            db=db_session, telegram_user_id=444444, username="old_handle"
        )
        db_session.commit()

        updated = get_or_create_user(
            db=db_session, telegram_user_id=444444, username="new_handle"
        )
        db_session.commit()

        assert updated.username == "new_handle"

    def test_updates_first_name_when_changed(self, db_session: Session) -> None:
        """If a user changes their Telegram first name, the DB record is updated."""
        get_or_create_user(
            db=db_session, telegram_user_id=555555, first_name="Carol"
        )
        db_session.commit()

        updated = get_or_create_user(
            db=db_session, telegram_user_id=555555, first_name="Carolina"
        )
        db_session.commit()

        assert updated.first_name == "Carolina"

    def test_none_username_is_stored(self, db_session: Session) -> None:
        """Users without a Telegram @username are stored correctly with username=None."""
        user = get_or_create_user(
            db=db_session, telegram_user_id=666666, username=None
        )
        db_session.commit()

        assert user.username is None

    def test_created_at_is_set(self, db_session: Session) -> None:
        """created_at is automatically populated."""
        user = get_or_create_user(db=db_session, telegram_user_id=777777)
        db_session.commit()

        assert user.created_at is not None


# ---------------------------------------------------------------------------
# get_user_by_telegram_id
# ---------------------------------------------------------------------------

class TestGetUserByTelegramId:
    def test_returns_existing_user(self, db_session: Session) -> None:
        """Returns the User if they exist."""
        get_or_create_user(db=db_session, telegram_user_id=888888)
        db_session.commit()

        found = get_user_by_telegram_id(db=db_session, telegram_user_id=888888)
        assert found is not None
        assert found.telegram_user_id == 888888

    def test_returns_none_for_unknown_user(self, db_session: Session) -> None:
        """Returns None for a telegram_user_id that has never been seen."""
        result = get_user_by_telegram_id(db=db_session, telegram_user_id=999999)
        assert result is None


# ---------------------------------------------------------------------------
# update_timezone
# ---------------------------------------------------------------------------

class TestUpdateTimezone:
    def test_valid_timezone_is_saved(self, db_session: Session) -> None:
        """A valid IANA timezone string is accepted and persisted."""
        user = get_or_create_user(db=db_session, telegram_user_id=101010)
        db_session.commit()

        updated = update_timezone(db=db_session, user=user, tz_string="America/New_York")
        db_session.commit()

        assert updated.timezone == "America/New_York"

    def test_invalid_timezone_raises_value_error(self, db_session: Session) -> None:
        """An invalid timezone string raises ValueError — not saved."""
        user = get_or_create_user(db=db_session, telegram_user_id=202020)
        db_session.commit()

        with pytest.raises(ValueError, match="Unknown timezone"):
            update_timezone(db=db_session, user=user, tz_string="Mars/Olympus")

    def test_utc_timezone_is_valid(self, db_session: Session) -> None:
        """UTC is a valid timezone."""
        user = get_or_create_user(db=db_session, telegram_user_id=303030)
        db_session.commit()

        updated = update_timezone(db=db_session, user=user, tz_string="UTC")
        db_session.commit()

        assert updated.timezone == "UTC"
