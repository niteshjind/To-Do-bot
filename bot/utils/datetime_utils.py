"""
utils/datetime_utils.py — Date/time parsing and timezone conversion helpers.

Application datetime invariant:
  • User inputs a local time  →  convert to UTC for storage.
  • UTC retrieved from DB    →  convert to local time for display.

Supported user input formats:
  • Date : DD/MM/YYYY  (e.g. 07/10/2026)
  • Time : HH:MM       (24-hour, e.g. 09:30)
"""

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

import pytz

# ---------------------------------------------------------------------------
# Format constants & regex patterns
# ---------------------------------------------------------------------------

DATE_INPUT_FORMAT = "%d/%m/%Y"          # User input
TIME_INPUT_FORMAT = "%H:%M"             # User input
DISPLAY_FORMAT = "%d %b %Y at %H:%M"   # "07 Oct 2026 at 09:30"
DATE_DISPLAY_FORMAT = "%d %b %Y"        # "07 Oct 2026"

DATE_REGEX = re.compile(r"^\d{2}/\d{2}/\d{4}$")
TIME_REGEX = re.compile(r"^\d{2}:\d{2}$")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_date(text: str) -> Optional[date]:
    """
    Parse a user-submitted date string in DD/MM/YYYY format.

    Returns:
        A :class:`datetime.date` object, or ``None`` if parsing fails.
    """
    cleaned = text.strip()
    if not DATE_REGEX.match(cleaned):
        return None
    try:
        return datetime.strptime(cleaned, DATE_INPUT_FORMAT).date()
    except ValueError:
        return None


def parse_time(text: str) -> Optional[time]:
    """
    Parse a user-submitted time string in HH:MM (24-hour) format.

    Returns:
        A :class:`datetime.time` object, or ``None`` if parsing fails.
    """
    cleaned = text.strip()
    if not TIME_REGEX.match(cleaned):
        return None
    try:
        return datetime.strptime(cleaned, TIME_INPUT_FORMAT).time()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def combine_to_utc(task_date: date, task_time: time, tz_string: str) -> datetime:
    """
    Combine a local date + time into a UTC-aware datetime ready for DB storage.

    Uses :func:`pytz.localize` (not ``replace``) to correctly handle DST
    transitions.

    Args:
        task_date: Date in the user's local timezone.
        task_time: Time in the user's local timezone.
        tz_string: IANA timezone string (e.g. ``"Asia/Kolkata"``).

    Returns:
        A timezone-aware :class:`datetime.datetime` in UTC.

    Raises:
        pytz.exceptions.UnknownTimeZoneError: If ``tz_string`` is not valid.
        pytz.exceptions.AmbiguousTimeError: If the local time is ambiguous
            during a DST transition (rare; raised with ``is_dst=None``).
    """
    local_tz = pytz.timezone(tz_string)
    naive_dt = datetime.combine(task_date, task_time)
    local_dt = local_tz.localize(naive_dt, is_dst=None)
    return local_dt.astimezone(timezone.utc)


def format_dt_local(dt_utc: datetime, tz_string: str) -> str:
    """
    Format a UTC-aware datetime as a human-readable string in the user's timezone.

    Example output: ``"07 Oct 2026 at 09:30"``

    Args:
        dt_utc: UTC-aware datetime (as stored in DB).
        tz_string: IANA timezone string for display.

    Returns:
        Formatted string in the user's local time.
    """
    local_tz = pytz.timezone(tz_string)
    local_dt = dt_utc.astimezone(local_tz)
    return local_dt.strftime(DISPLAY_FORMAT)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def is_in_past(dt_utc: datetime) -> bool:
    """
    Return ``True`` if the given UTC-aware datetime is strictly in the past.

    A datetime equal to "now" is considered valid (not in the past) to avoid
    edge cases where the clock ticks between validation and the success message.
    """
    return dt_utc < datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# UX helpers
# ---------------------------------------------------------------------------

def example_date_string(tz_string: str) -> str:
    """
    Return tomorrow's date as a ``DD/MM/YYYY`` string in the given timezone.

    Used in user-facing prompts to show a concrete, always-valid example.
    """
    local_tz = pytz.timezone(tz_string)
    tomorrow = datetime.now(local_tz).date() + timedelta(days=1)
    return tomorrow.strftime(DATE_INPUT_FORMAT)


def current_time_display(tz_string: str) -> str:
    """
    Return the current local time as ``"HH:MM (DD Mon)"`` in the given timezone.

    Shown in 'time is in the past' error messages so the user knows what
    the bot thinks the current time is.
    """
    local_tz = pytz.timezone(tz_string)
    now_local = datetime.now(local_tz)
    return now_local.strftime("%H:%M (%d %b)")


# ---------------------------------------------------------------------------
# Listing & Boundary helpers
# ---------------------------------------------------------------------------

def get_day_boundaries_utc(
    tz_string: str, target_date: Optional[date] = None
) -> tuple[datetime, datetime]:
    """
    Return the (start_utc, end_utc) datetime bounds for a calendar day in the user's timezone.

    If target_date is None, defaults to 'today' in the user's timezone.
    start_utc corresponds to 00:00:00.000000 local time.
    end_utc corresponds to 23:59:59.999999 local time.
    """
    local_tz = pytz.timezone(tz_string)
    if target_date is None:
        target_date = datetime.now(local_tz).date()

    start_local = datetime.combine(target_date, time.min)
    end_local = datetime.combine(target_date, time.max)

    start_utc = local_tz.localize(start_local, is_dst=None).astimezone(timezone.utc)
    end_utc = local_tz.localize(end_local, is_dst=None).astimezone(timezone.utc)

    return start_utc, end_utc


def format_time_only(dt_utc: datetime, tz_string: str) -> str:
    """Return local time formatted as 'HH:MM' (24-hour)."""
    local_tz = pytz.timezone(tz_string)
    return dt_utc.astimezone(local_tz).strftime("%H:%M")


def format_date_only(dt_utc: datetime, tz_string: str) -> str:
    """Return local date formatted as 'DD Mon YYYY' (e.g. '07 Oct 2026')."""
    local_tz = pytz.timezone(tz_string)
    return dt_utc.astimezone(local_tz).strftime("%d %b %Y")


def format_date_heading(dt_utc: datetime, tz_string: str) -> str:
    """
    Format a date heading relative to 'today' in the user's timezone.
    Examples:
      - "Today, 07 Oct"
      - "Tomorrow, 08 Oct"
      - "Thu, 09 Oct"
    """
    local_tz = pytz.timezone(tz_string)
    local_dt = dt_utc.astimezone(local_tz)
    local_date = local_dt.date()
    today = datetime.now(local_tz).date()

    if local_date == today:
        return f"Today, {local_dt.strftime('%d %b')}"
    elif local_date == today + timedelta(days=1):
        return f"Tomorrow, {local_dt.strftime('%d %b')}"
    else:
        return local_dt.strftime("%a, %d %b")


def get_local_date_and_time(dt_utc: datetime, tz_string: str) -> tuple[date, time]:
    """
    Extract local date and time components from a UTC datetime.

    Used when partially editing a task (e.g. editing date while preserving
    time, or vice versa).
    """
    local_tz = pytz.timezone(tz_string)
    local_dt = dt_utc.astimezone(local_tz)
    return local_dt.date(), local_dt.time()
