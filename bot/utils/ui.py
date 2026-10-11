"""
utils/ui.py — Reusable UI facade for Telegram keyboards, templates, and view formatters.

Centralizes presentation components for /settings, /summary, and other Phase 7 UI views.
All formatting logic is pure Python with zero database or network dependencies.
"""

from bot.utils.keyboards import (
    COMMON_SUMMARY_TIMES,
    COMMON_TIMEZONES,
    CB_SETTINGS_BACK,
    CB_SETTINGS_CHANGE_TIME,
    CB_SETTINGS_CHANGE_TZ,
    CB_SETTINGS_REFRESH,
    CB_SETTINGS_TOGGLE_REMINDERS,
    CB_SETTINGS_TOGGLE_SUMMARY,
    CB_SUMMARY_REFRESH,
    CB_TIME_CUSTOM,
    CB_TIME_SET_PREFIX,
    CB_TZ_CUSTOM,
    CB_TZ_SET_PREFIX,
    settings_keyboard,
    summary_keyboard,
    summary_time_keyboard,
    timezone_keyboard,
)
from bot.utils.messages import (
    SUMMARY_TIME_SELECTION_PROMPT,
    TIMEZONE_SELECTION_PROMPT,
    format_daily_summary_message,
    format_settings_message,
)

__all__ = [
    "COMMON_SUMMARY_TIMES",
    "COMMON_TIMEZONES",
    "CB_SETTINGS_BACK",
    "CB_SETTINGS_CHANGE_TIME",
    "CB_SETTINGS_CHANGE_TZ",
    "CB_SETTINGS_REFRESH",
    "CB_SETTINGS_TOGGLE_REMINDERS",
    "CB_SETTINGS_TOGGLE_SUMMARY",
    "CB_SUMMARY_REFRESH",
    "CB_TIME_CUSTOM",
    "CB_TIME_SET_PREFIX",
    "CB_TZ_CUSTOM",
    "CB_TZ_SET_PREFIX",
    "settings_keyboard",
    "summary_keyboard",
    "summary_time_keyboard",
    "timezone_keyboard",
    "SUMMARY_TIME_SELECTION_PROMPT",
    "TIMEZONE_SELECTION_PROMPT",
    "format_daily_summary_message",
    "format_settings_message",
]
