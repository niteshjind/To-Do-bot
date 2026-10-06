"""
database/database.py — Engine, session factory, and session helpers.

Design decisions:
  • Database-agnostic: SQLite for dev, PostgreSQL for prod.
    The only SQLite-specific config is `check_same_thread=False`
    (required because APScheduler runs on a background thread).
    This arg is silently ignored by PostgreSQL.

  • `get_db()` is a context manager that auto-commits on success
    and rolls back on any exception — consistent transactional scope.

  • `init_db()` uses SQLAlchemy create_all() for development.
    In production, use `alembic upgrade head` instead.

Usage:
    from bot.database.database import get_db

    with get_db() as db:
        user = db.query(User).filter_by(telegram_user_id=123).first()
"""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from bot.config import settings
from bot.database.models import Base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQLite-specific performance tweak: enable WAL mode so reader threads
# (APScheduler) don't block the writer thread (bot handlers).
# This pragma is harmless to call and is simply ignored for PostgreSQL.
# ---------------------------------------------------------------------------

@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
    """Enable WAL journal mode for SQLite connections."""
    # Guard: only apply to SQLite
    if "sqlite" in settings.DATABASE_URL:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_connect_args: dict = {}
if "sqlite" in settings.DATABASE_URL:
    # Needed because SQLite connections are not thread-safe by default,
    # but APScheduler runs its jobs on a separate thread.
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    # Echo SQL statements only in DEBUG mode — avoids noisy logs in prod.
    echo=(settings.LOG_LEVEL == "DEBUG"),
    # Keep a small connection pool; fine for single-user SQLite.
    pool_pre_ping=True,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Create all tables that don't already exist.

    Use this for local development / first run.
    For production, prefer: `alembic upgrade head`
    """
    logger.info("Running init_db(): creating tables if not present...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified/created.")


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """
    Provide a scoped database session with automatic commit/rollback.

    Example:
        with get_db() as db:
            db.add(some_model_instance)
            # auto-committed on exit

    Raises the original exception after rolling back — never swallows errors.
    """
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
