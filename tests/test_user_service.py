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

from datetime import date
import pytest
from sqlalchemy.orm import Session

from bot.database.models import User
from bot.services.user_service import (
    UserSettingsDTO,
    get_or_create_user,
    get_user_by_telegram_id,
    get_user_settings,
    get_user_settings_by_telegram_id,
    update_daily_summary_enabled,
    update_daily_summary_time,
    update_last_summary_date,
    update_reminders_enabled,
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

    def test_default_preferences_for_new_user(self, db_session: Session) -> None:
        """New users receive Phase 7 default notification and summary preferences."""
        user = get_or_create_user(db=db_session, telegram_user_id=222223)
        db_session.commit()

        assert user.reminders_enabled is True
        assert user.daily_summary_enabled is True
        assert user.daily_summary_time == "09:00"
        assert user.last_summary_date is None

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


# ---------------------------------------------------------------------------
# Phase 7: get_user_settings & get_user_settings_by_telegram_id
# ---------------------------------------------------------------------------

class TestUserSettings:
    def test_get_user_settings_returns_defaults(self, db_session: Session) -> None:
        """New user receives expected default settings in UserSettingsDTO."""
        user = get_or_create_user(db=db_session, telegram_user_id=404040)
        db_session.commit()

        # Call with user instance
        settings_from_user = get_user_settings(user)
        assert isinstance(settings_from_user, UserSettingsDTO)
        assert settings_from_user.user_id == user.id
        assert settings_from_user.telegram_user_id == 404040
        assert settings_from_user.timezone == "Asia/Kolkata"
        assert settings_from_user.reminders_enabled is True
        assert settings_from_user.daily_summary_enabled is True
        assert settings_from_user.daily_summary_time == "09:00"
        assert settings_from_user.last_summary_date is None

        # Call with (db, user)
        settings_from_db = get_user_settings(db_session, user)
        assert settings_from_db == settings_from_user

    def test_get_user_settings_invalid_argument_raises(self, db_session: Session) -> None:
        """Calling get_user_settings without a valid User raises ValueError."""
        with pytest.raises(ValueError, match="A valid User instance must be provided"):
            get_user_settings(None)

    def test_get_user_settings_by_telegram_id_existing(self, db_session: Session) -> None:
        """Returns UserSettingsDTO for known telegram_user_id."""
        user = get_or_create_user(db=db_session, telegram_user_id=505050)
        db_session.commit()

        settings = get_user_settings_by_telegram_id(db=db_session, telegram_user_id=505050)
        assert settings is not None
        assert settings.telegram_user_id == 505050
        assert settings.daily_summary_time == "09:00"

    def test_get_user_settings_by_telegram_id_unknown(self, db_session: Session) -> None:
        """Returns None for unknown telegram_user_id."""
        settings = get_user_settings_by_telegram_id(db=db_session, telegram_user_id=999000)
        assert settings is None


# ---------------------------------------------------------------------------
# Phase 7: update_reminders_enabled
# ---------------------------------------------------------------------------

class TestUpdateRemindersEnabled:
    def test_toggle_reminders(self, db_session: Session) -> None:
        """Enabling and disabling reminders updates the record."""
        user = get_or_create_user(db=db_session, telegram_user_id=606060)
        db_session.commit()

        # Disable
        updated = update_reminders_enabled(db=db_session, user=user, enabled=False)
        db_session.commit()
        assert updated.reminders_enabled is False

        # Re-enable
        updated = update_reminders_enabled(db=db_session, user=user, enabled=True)
        db_session.commit()
        assert updated.reminders_enabled is True

    def test_invalid_type_raises(self, db_session: Session) -> None:
        """Passing a non-boolean raises ValueError."""
        user = get_or_create_user(db=db_session, telegram_user_id=606061)
        db_session.commit()

        with pytest.raises(ValueError, match="must be a boolean"):
            update_reminders_enabled(db=db_session, user=user, enabled="true")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Phase 7: update_daily_summary_enabled
# ---------------------------------------------------------------------------

class TestUpdateDailySummaryEnabled:
    def test_toggle_daily_summary(self, db_session: Session) -> None:
        """Enabling and disabling daily summary updates the record."""
        user = get_or_create_user(db=db_session, telegram_user_id=707070)
        db_session.commit()

        # Disable
        updated = update_daily_summary_enabled(db=db_session, user=user, enabled=False)
        db_session.commit()
        assert updated.daily_summary_enabled is False

        # Re-enable
        updated = update_daily_summary_enabled(db=db_session, user=user, enabled=True)
        db_session.commit()
        assert updated.daily_summary_enabled is True

    def test_invalid_type_raises(self, db_session: Session) -> None:
        """Passing a non-boolean raises ValueError."""
        user = get_or_create_user(db=db_session, telegram_user_id=707071)
        db_session.commit()

        with pytest.raises(ValueError, match="must be a boolean"):
            update_daily_summary_enabled(db=db_session, user=user, enabled=1)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Phase 7: update_daily_summary_time
# ---------------------------------------------------------------------------

class TestUpdateDailySummaryTime:
    @pytest.mark.parametrize("valid_time", ["00:00", "07:30", "09:00", "14:15", "23:59"])
    def test_valid_summary_time_saved(self, db_session: Session, valid_time: str) -> None:
        """Valid 24-hour HH:MM strings are accepted and persisted."""
        user = get_or_create_user(db=db_session, telegram_user_id=808080)
        db_session.commit()

        updated = update_daily_summary_time(db=db_session, user=user, time_str=valid_time)
        db_session.commit()

        assert updated.daily_summary_time == valid_time

    @pytest.mark.parametrize(
        "invalid_time",
        [
            "25:00",     # Invalid hour (> 23)
            "24:00",     # 24:00 is invalid in standard 24h
            "12:60",     # Invalid minute (> 59)
            "9:00",      # Missing leading zero
            "09:0",      # Incomplete minute
            "",          # Empty string
            "   ",       # Whitespace only
            " 09:00 ",   # Leading/trailing whitespace
            "09:00:00",  # Includes seconds
            "abc",       # Non-numeric
            "12-30",     # Wrong separator
            None,        # None
        ],
    )
    def test_invalid_summary_time_raises(self, db_session: Session, invalid_time) -> None:
        """Invalid 24-hour HH:MM values raise ValueError and are not saved."""
        user = get_or_create_user(db=db_session, telegram_user_id=808081)
        db_session.commit()

        with pytest.raises(ValueError, match="Invalid summary time"):
            update_daily_summary_time(db=db_session, user=user, time_str=invalid_time)


# ---------------------------------------------------------------------------
# Phase 7: update_last_summary_date
# ---------------------------------------------------------------------------

class TestUpdateLastSummaryDate:
    def test_update_with_string_and_clear(self, db_session: Session) -> None:
        """Can update with valid YYYY-MM-DD string and clear back to None."""
        user = get_or_create_user(db=db_session, telegram_user_id=909090)
        db_session.commit()

        assert user.last_summary_date is None

        # Update with string
        updated = update_last_summary_date(db=db_session, user=user, summary_date="2026-10-11")
        db_session.commit()
        assert updated.last_summary_date == "2026-10-11"

        # Clear to None
        cleared = update_last_summary_date(db=db_session, user=user, summary_date=None)
        db_session.commit()
        assert cleared.last_summary_date is None

    def test_update_with_date_object(self, db_session: Session) -> None:
        """Can update with a datetime.date object."""
        user = get_or_create_user(db=db_session, telegram_user_id=909091)
        db_session.commit()

        d = date(2026, 10, 15)
        updated = update_last_summary_date(db=db_session, user=user, summary_date=d)
        db_session.commit()
        assert updated.last_summary_date == "2026-10-15"

    @pytest.mark.parametrize(
        "invalid_date",
        [
            "11-10-2026",  # DD-MM-YYYY format
            "2026/10/11",  # Slashes
            "2026-02-30",  # Invalid calendar date
            "2026-13-01",  # Invalid month
            "not-a-date",  # Random string
            "",            # Empty string
            12345,         # Integer type
        ],
    )
    def test_invalid_summary_date_raises(self, db_session: Session, invalid_date) -> None:
        """Invalid date strings or types raise ValueError."""
        user = get_or_create_user(db=db_session, telegram_user_id=909092)
        db_session.commit()

        with pytest.raises(ValueError, match="Invalid summary date"):
            update_last_summary_date(db=db_session, user=user, summary_date=invalid_date)

