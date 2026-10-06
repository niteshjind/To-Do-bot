"""
tests/conftest.py — Shared pytest fixtures.

The key fixture is `db_session`: provides an isolated in-memory SQLite
database for each test function. Tests never touch the real todo_bot.db.
"""

import os

# Ensure tests run safely without requiring a real .env file
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "mock_token_for_tests_12345")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from bot.database.models import Base


@pytest.fixture(scope="function")
def db_session() -> Session:
    """
    Provide a fresh in-memory SQLite database session for each test.

    - Uses SQLite :memory: so no files are created or left behind.
    - All tables are created from the ORM models before each test.
    - The session is closed (and the in-memory DB destroyed) after each test.

    Usage in tests:
        def test_something(db_session):
            user = User(telegram_user_id=123)
            db_session.add(user)
            db_session.commit()
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
