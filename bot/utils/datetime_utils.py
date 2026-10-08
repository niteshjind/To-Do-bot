"""
utils/datetime_utils.py — Date/time parsing and timezone conversion helpers.

Application datetime invariant:
  • User inputs a local time  →  convert to UTC for storage.
  • UTC retrieved from DB    →  convert to local time for display.

Supported user input formats:
  • Date : DD/MM/YYYY  (e.g. 07/10/2026)
  • Time : HH:MM       (24-hour, e.g. 09:30)
"""

import calendar
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


# ---------------------------------------------------------------------------
# Phase 6: Snooze and Recurrence Calculations
# ---------------------------------------------------------------------------

def calculate_snooze_datetime(
    current_utc: datetime,
    snooze_type: str,
    tz_string: str,
    original_due_utc: Optional[datetime] = None,
) -> datetime:
    """
    Calculate the new UTC datetime when a task is snoozed.

    Options:
      - "10m": current_utc + 10 minutes
      - "30m": current_utc + 30 minutes
      - "1h":  current_utc + 1 hour
      - "tomorrow": next calendar day in user's timezone, preserving original local time.

    Args:
        current_utc: Current UTC timestamp (timezone-aware).
        snooze_type: One of {"10m", "30m", "1h", "tomorrow"}.
        tz_string: IANA timezone string for the user.
        original_due_utc: Previous due time in UTC (used to preserve local time for "tomorrow").

    Returns:
        Timezone-aware datetime in UTC.

    Raises:
        ValueError: If datetimes are naive or snooze_type is unsupported.
    """
    if current_utc.tzinfo is None:
        raise ValueError("current_utc must be a timezone-aware datetime.")

    if snooze_type == "10m":
        return current_utc + timedelta(minutes=10)
    elif snooze_type == "30m":
        return current_utc + timedelta(minutes=30)
    elif snooze_type == "1h":
        return current_utc + timedelta(hours=1)
    elif snooze_type == "tomorrow":
        local_tz = pytz.timezone(tz_string)
        current_local = current_utc.astimezone(local_tz)
        tomorrow_date = current_local.date() + timedelta(days=1)

        # Preserve previous scheduled local time if available, otherwise current local time
        if original_due_utc is not None and original_due_utc.tzinfo is not None:
            target_time = original_due_utc.astimezone(local_tz).time()
        else:
            target_time = current_local.time()

        return combine_to_utc(tomorrow_date, target_time, tz_string)
    else:
        raise ValueError(f"Unsupported snooze_type: {snooze_type!r}")


def calculate_next_occurrence(
    base_dt_utc: datetime,
    recurrence: str,
    tz_string: str,
    after_utc: Optional[datetime] = None,
) -> datetime:
    """
    Calculate the next occurrence datetime for a recurring task.

    Supports:
      - "daily": +1 day in user's local calendar
      - "weekly": +7 days in user's local calendar
      - "monthly": +1 month in user's local calendar (with month-end boundary safety)

    If `after_utc` is provided (e.g. current UTC time), the calculation advances
    as many intervals as needed until the returned datetime is strictly after `after_utc`.

    Args:
        base_dt_utc: Current due datetime in UTC.
        recurrence: Recurrence rule ("daily", "weekly", "monthly").
        tz_string: IANA timezone name.
        after_utc: Optional threshold UTC datetime that the result must be strictly after.

    Returns:
        Timezone-aware datetime in UTC for the next occurrence.

    Raises:
        ValueError: If base_dt_utc is naive or recurrence is unsupported.
    """
    if base_dt_utc.tzinfo is None:
        raise ValueError("base_dt_utc must be a timezone-aware datetime.")

    rec_lower = recurrence.lower()
    if rec_lower not in {"daily", "weekly", "monthly"}:
        raise ValueError(f"Unsupported recurrence rule: {recurrence!r}")

    local_tz = pytz.timezone(tz_string)
    local_dt = base_dt_utc.astimezone(local_tz)
    local_time = local_dt.time()
    cur_date = local_dt.date()

    def _step(d: date) -> date:
        if rec_lower == "daily":
            return d + timedelta(days=1)
        elif rec_lower == "weekly":
            return d + timedelta(days=7)
        elif rec_lower == "monthly":
            year = d.year
            month = d.month + 1
            if month > 12:
                month = 1
                year += 1
            max_day = calendar.monthrange(year, month)[1]
            day = min(d.day, max_day)
            return date(year, month, day)
        return d

    next_date = _step(cur_date)
    next_utc = combine_to_utc(next_date, local_time, tz_string)

    if after_utc is not None:
        if after_utc.tzinfo is None:
            raise ValueError("after_utc must be a timezone-aware datetime.")
        while next_utc <= after_utc:
            next_date = _step(next_date)
            next_utc = combine_to_utc(next_date, local_time, tz_string)

    return next_utc

