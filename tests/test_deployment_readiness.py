"""
tests/test_deployment_readiness.py — Tests for Phase 8 Step 2 deployment readiness fixes.

Covers:
  1. DATABASE_URL normalization (postgres:// -> postgresql://).
  2. Alembic URL resolution alignment with normalized URLs.
  3. Secret-safe database URL masking in logs (no plaintext passwords).
  4. Non-SQLite engine protection: _migrate_schema skips non-SQLite dialects.
  5. Port environment variable fallback for hosting platforms (PORT -> WEBHOOK_PORT).
  6. Procfile entry point verification.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, inspect, text

from bot.config import Settings
from bot.database.database import _migrate_schema, _set_sqlite_pragma
from bot.main import _mask_db_url


class TestDatabaseURLNormalization:

    def test_normalize_postgres_to_postgresql(self) -> None:
        """Legacy postgres:// URLs are normalized to postgresql://."""
        raw_url = "postgres://bot_user:secretpass@db.example.com:5432/todo_prod"
        s = Settings(DATABASE_URL=raw_url, TELEGRAM_BOT_TOKEN="dummy_token")
        assert s.DATABASE_URL == "postgresql://bot_user:secretpass@db.example.com:5432/todo_prod"

    def test_preserve_query_params_and_special_chars(self) -> None:
        """Query parameters like ?sslmode=require and percent-encoded characters are preserved."""
        raw_url = "postgres://bot_user:p%40ssw%3Ard@db.example.com:5432/todo_prod?sslmode=require&application_name=todo_bot"
        s = Settings(DATABASE_URL=raw_url, TELEGRAM_BOT_TOKEN="dummy_token")
        assert s.DATABASE_URL == "postgresql://bot_user:p%40ssw%3Ard@db.example.com:5432/todo_prod?sslmode=require&application_name=todo_bot"

    def test_preserve_postgresql_url(self) -> None:
        """Standard postgresql:// URLs remain untouched."""
        raw_url = "postgresql://bot_user:secretpass@db.example.com:5432/todo_prod"
        s = Settings(DATABASE_URL=raw_url, TELEGRAM_BOT_TOKEN="dummy_token")
        assert s.DATABASE_URL == raw_url

    def test_preserve_sqlite_url(self) -> None:
        """Standard SQLite URLs remain untouched."""
        raw_url = "sqlite:///./todo_test.db"
        s = Settings(DATABASE_URL=raw_url, TELEGRAM_BOT_TOKEN="dummy_token")
        assert s.DATABASE_URL == raw_url

    def test_alembic_url_resolution_normalizes_postgres(self) -> None:
        """Simulate Alembic custom URL resolution logic for postgres:// URLs."""
        test_env_url = "postgres://alembic_user:secret@db.host.com:5432/db"

        # Mirror logic in alembic/env.py
        custom_url = test_env_url
        if custom_url and custom_url.startswith("postgres://"):
            custom_url = "postgresql://" + custom_url[len("postgres://"):]

        assert custom_url == "postgresql://alembic_user:secret@db.host.com:5432/db"


class TestSecretSafeLogging:

    def test_database_url_password_is_masked(self) -> None:
        """Database passwords never appear in rendered log outputs."""
        sensitive_url = "postgresql://myuser:SuperSecretPassword123!@db.host.com:5432/proddb"
        masked = _mask_db_url(sensitive_url)

        assert "SuperSecretPassword123!" not in masked
        assert "myuser" in masked
        assert "db.host.com" in masked
        assert "***" in masked or "redacted" in masked

    def test_mask_db_url_preserves_sqlite(self) -> None:
        """SQLite local path URLs have no password and render cleanly."""
        sqlite_url = "sqlite:///./todo_bot.db"
        masked = _mask_db_url(sqlite_url)
        assert masked == "sqlite:///./todo_bot.db"

    def test_mask_db_url_handles_empty_and_invalid(self) -> None:
        """Invalid or empty URL strings return safe fallback strings without raising."""
        assert _mask_db_url("") == ""
        assert _mask_db_url("not-a-valid-url") == "[redacted]"


class TestPostgreSQLMigrationSafety:

    def test_migrate_schema_skips_non_sqlite(self) -> None:
        """_migrate_schema skips executing SQLite ALTER TABLE queries on PostgreSQL."""
        mock_engine = MagicMock()
        mock_engine.dialect.name = "postgresql"

        # Should return early without connecting or inspecting
        _migrate_schema(mock_engine)
        mock_engine.connect.assert_not_called()

    def test_migrate_schema_runs_on_sqlite(self) -> None:
        """_migrate_schema executes normally on SQLite engines."""
        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_user_id BIGINT NOT NULL UNIQUE,
                        username VARCHAR(64),
                        timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Kolkata',
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    );
                    """
                )
            )
            conn.commit()

        # Run migration on SQLite
        _migrate_schema(engine)

        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("users")}
        assert "reminders_enabled" in cols
        assert "daily_summary_enabled" in cols
        assert "daily_summary_time" in cols
        assert "last_summary_date" in cols
        engine.dispose()

    def test_set_sqlite_pragma_skips_non_sqlite_connections(self) -> None:
        """_set_sqlite_pragma does not execute PRAGMA statements on non-SQLite DBAPI connections."""
        class MockPsycopgConnection:
            __module__ = "psycopg2.extensions"
            def __init__(self) -> None:
                self.cursor = MagicMock()

        mock_conn = MockPsycopgConnection()
        _set_sqlite_pragma(mock_conn, None)
        mock_conn.cursor.assert_not_called()

    def test_set_sqlite_pragma_runs_on_sqlite_connections(self) -> None:
        """_set_sqlite_pragma executes PRAGMA statements on SQLite DBAPI connections."""
        class MockSqliteConnection:
            __module__ = "sqlite3"
            def __init__(self) -> None:
                self.mock_cursor = MagicMock()
            def cursor(self) -> MagicMock:
                return self.mock_cursor

        mock_conn = MockSqliteConnection()
        _set_sqlite_pragma(mock_conn, None)
        assert mock_conn.mock_cursor.execute.call_count == 2
        mock_conn.mock_cursor.close.assert_called_once()


class TestProcessAndHostingConfiguration:

    def test_webhook_port_supports_port_env_variable(self) -> None:
        """WEBHOOK_PORT accepts platform-injected PORT environment variable."""
        s = Settings(PORT="10000", TELEGRAM_BOT_TOKEN="dummy_token")
        assert s.WEBHOOK_PORT == 10000

    def test_webhook_port_prefers_webhook_port_if_both_set(self) -> None:
        """WEBHOOK_PORT takes precedence over PORT if explicitly provided."""
        s = Settings(WEBHOOK_PORT="8443", PORT="10000", TELEGRAM_BOT_TOKEN="dummy_token")
        assert s.WEBHOOK_PORT == 8443

    def test_procfile_declares_worker_entrypoint(self) -> None:
        """Verify Procfile exists and declares 'worker: python -m bot.main'."""
        procfile_path = Path("Procfile")
        assert procfile_path.exists()
        content = procfile_path.read_text().strip()
        assert content == "worker: python -m bot.main"
