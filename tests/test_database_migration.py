"""
tests/test_database_migration.py — Tests for Phase 7 Step 1 database and User model schema extensions.

Covers:
  • Idempotent schema migration on existing SQLite databases missing Phase 7 columns
  • Preservation of existing user data during migration
  • Server and client defaults for existing and new rows
  • Repeated migration calls (idempotence)
  • Correct behavior of nullable last_summary_date
"""

from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from alembic.config import Config
from alembic import command

from bot.database.database import _migrate_schema, init_db
from bot.database.models import Base, User


@pytest.fixture
def legacy_sqlite_engine():
    """
    Creates an isolated in-memory SQLite database simulating a Phase 1–6 schema
    (i.e. users table without Phase 7 preferences columns).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id BIGINT NOT NULL UNIQUE,
                    username VARCHAR(64),
                    first_name VARCHAR(128),
                    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Kolkata',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                );
                """
            )
        )
        # Seed existing user record
        now_str = datetime.now(timezone.utc).isoformat()
        conn.execute(
            text(
                """
                INSERT INTO users (id, telegram_user_id, username, first_name, timezone, created_at, updated_at)
                VALUES (1, 987654321, 'legacy_alice', 'Alice', 'Asia/Kolkata', :now, :now);
                """
            ),
            {"now": now_str},
        )
        conn.commit()

    yield engine
    engine.dispose()


def test_schema_migration_adds_missing_columns(legacy_sqlite_engine):
    """
    Verifies that _migrate_schema safely inspects the table and adds all 4 Phase 7 columns.
    """
    inspector_before = inspect(legacy_sqlite_engine)
    cols_before = {col["name"] for col in inspector_before.get_columns("users")}
    assert "reminders_enabled" not in cols_before
    assert "daily_summary_enabled" not in cols_before
    assert "daily_summary_time" not in cols_before
    assert "last_summary_date" not in cols_before

    # Run schema migration
    _migrate_schema(legacy_sqlite_engine)

    inspector_after = inspect(legacy_sqlite_engine)
    cols_after = {col["name"] for col in inspector_after.get_columns("users")}
    assert "reminders_enabled" in cols_after
    assert "daily_summary_enabled" in cols_after
    assert "daily_summary_time" in cols_after
    assert "last_summary_date" in cols_after


def test_existing_user_data_preserved_and_receives_defaults(legacy_sqlite_engine):
    """
    Verifies that existing users retain their original profile values
    and receive safe default preferences.
    """
    _migrate_schema(legacy_sqlite_engine)

    Session = sessionmaker(bind=legacy_sqlite_engine)
    with Session() as session:
        user = session.query(User).filter_by(telegram_user_id=987654321).first()
        assert user is not None
        assert user.id == 1
        assert user.username == "legacy_alice"
        assert user.first_name == "Alice"
        assert user.timezone == "Asia/Kolkata"

        # Defaults applied
        assert user.reminders_enabled is True
        assert user.daily_summary_enabled is True
        assert user.daily_summary_time == "09:00"
        assert user.last_summary_date is None


def test_repeated_initialization_is_idempotent(legacy_sqlite_engine):
    """
    Calling init_db multiple times on the same database succeeds without errors or duplicates.
    """
    # First call
    init_db(bind_engine=legacy_sqlite_engine)
    # Second call
    init_db(bind_engine=legacy_sqlite_engine)
    # Third call
    init_db(bind_engine=legacy_sqlite_engine)

    Session = sessionmaker(bind=legacy_sqlite_engine)
    with Session() as session:
        count = session.query(User).count()
        assert count == 1
        user = session.query(User).first()
        assert user.reminders_enabled is True
        assert user.daily_summary_time == "09:00"


def test_nullable_last_summary_date_behavior(db_session):
    """
    Tests that last_summary_date starts as None, can be updated with a date string,
    and can be cleared back to None.
    """
    user = User(
        telegram_user_id=555123,
        username="summary_tester",
    )
    db_session.add(user)
    db_session.commit()

    # Default is None
    assert user.last_summary_date is None

    # Update with summary date
    user.last_summary_date = "2026-10-11"
    db_session.commit()

    fetched = db_session.query(User).filter_by(telegram_user_id=555123).first()
    assert fetched.last_summary_date == "2026-10-11"

    # Reset to None
    fetched.last_summary_date = None
    db_session.commit()

    cleared = db_session.query(User).filter_by(telegram_user_id=555123).first()
    assert cleared.last_summary_date is None


def test_new_user_receives_expected_default_preferences(db_session):
    """
    Verifies that a freshly created user receives all default preference values.
    """
    user = User(telegram_user_id=444999)
    db_session.add(user)
    db_session.commit()

    assert user.reminders_enabled is True
    assert user.daily_summary_enabled is True
    assert user.daily_summary_time == "09:00"
    assert user.last_summary_date is None
    assert user.timezone == "Asia/Kolkata"


def test_alembic_fresh_upgrade_head(tmp_path):
    """
    Tests that a fresh database can be fully migrated to 'head' via Alembic,
    creating users and tasks tables with all Phase 7 settings columns.
    """
    db_file = tmp_path / "alembic_fresh.db"
    db_url = f"sqlite:///{db_file}"

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    insp = inspect(engine)
    tables = insp.get_table_names()
    assert "users" in tables
    assert "tasks" in tables
    assert "alembic_version" in tables

    cols = {c["name"] for c in insp.get_columns("users")}
    assert "reminders_enabled" in cols
    assert "daily_summary_enabled" in cols
    assert "daily_summary_time" in cols
    assert "last_summary_date" in cols
    engine.dispose()


def test_alembic_downgrade_and_reupgrade(tmp_path):
    """
    Tests that downgrading to 'base' drops tables cleanly and re-upgrading to 'head' recreates them.
    """
    db_file = tmp_path / "alembic_downgrade.db"
    db_url = f"sqlite:///{db_file}"

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(db_url)
    insp = inspect(engine)
    tables = insp.get_table_names()
    assert "users" not in tables
    assert "tasks" not in tables

    command.upgrade(cfg, "head")
    insp_reup = inspect(engine)
    assert "users" in insp_reup.get_table_names()
    assert "tasks" in insp_reup.get_table_names()
    engine.dispose()


def test_alembic_upgrade_legacy_database(tmp_path):
    """
    Tests that a legacy database stamped at 001_initial upgrades cleanly to 002_phase7
    and retains existing records and sets defaults.
    """
    db_file = tmp_path / "alembic_legacy.db"
    db_url = f"sqlite:///{db_file}"

    engine = create_engine(db_url)
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id BIGINT NOT NULL UNIQUE,
                    username VARCHAR(64),
                    first_name VARCHAR(128),
                    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Kolkata',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                );
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO users (id, telegram_user_id, username, first_name, timezone, created_at, updated_at)
                VALUES (1, 888777, 'legacy_bob', 'Bob', 'Asia/Kolkata', '2026-10-10 12:00:00', '2026-10-10 12:00:00');
                """
            )
        )
        conn.commit()
    engine.dispose()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.stamp(cfg, "001_initial")
    command.upgrade(cfg, "head")

    engine_post = create_engine(db_url)
    insp = inspect(engine_post)
    cols = {c["name"] for c in insp.get_columns("users")}
    assert "reminders_enabled" in cols
    assert "daily_summary_enabled" in cols
    assert "daily_summary_time" in cols
    assert "last_summary_date" in cols

    with engine_post.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, telegram_user_id, username, reminders_enabled, daily_summary_time, last_summary_date FROM users WHERE id = 1"
            )
        ).first()
        assert row[0] == 1
        assert row[1] == 888777
        assert row[2] == "legacy_bob"
        assert row[3] == 1
        assert row[4] == "09:00"
        assert row[5] is None
    engine_post.dispose()

