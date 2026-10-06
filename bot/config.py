"""
config.py — Central configuration loader.

All environment variables are declared here with types and defaults.
Import `settings` anywhere in the project; never read os.environ directly.

Usage:
    from bot.config import settings
    token = settings.TELEGRAM_BOT_TOKEN
"""

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # -------------------------------------------------------------------------
    # Required (validated at runtime in main.py)
    # -------------------------------------------------------------------------
    TELEGRAM_BOT_TOKEN: str = ""

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    DATABASE_URL: str = "sqlite:///./todo_bot.db"

    # -------------------------------------------------------------------------
    # Bot mode — controls polling vs webhook at startup
    # -------------------------------------------------------------------------
    BOT_MODE: Literal["polling", "webhook"] = "polling"

    # Webhook settings (only used when BOT_MODE="webhook")
    WEBHOOK_URL: str = ""
    WEBHOOK_PORT: int = 8443
    WEBHOOK_SECRET_TOKEN: str = ""

    # -------------------------------------------------------------------------
    # Timezone
    # -------------------------------------------------------------------------
    TIMEZONE: str = "Asia/Kolkata"

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    LOG_LEVEL: str = "INFO"

    # -------------------------------------------------------------------------
    # Scheduler & Windows
    # -------------------------------------------------------------------------
    # How often (seconds) the reminder-polling job runs
    REMINDER_POLL_INTERVAL_SECONDS: int = 60

    # How many days ahead /upcoming looks by default
    UPCOMING_DAYS_WINDOW: int = 7

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}, got '{v}'")
        return upper

    @field_validator("BOT_MODE")
    @classmethod
    def validate_webhook_url(cls, v: str) -> str:
        # Additional cross-field checks happen in main.py where we have full settings
        return v


# Module-level singleton — import this everywhere
settings = Settings()
