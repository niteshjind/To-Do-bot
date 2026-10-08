"""
tests/test_datetime_utils.py — Unit tests for bot/utils/datetime_utils.py.

Tests cover:
  • parse_date()      — valid format, invalid formats, edge cases
  • parse_time()      — valid format, invalid formats, edge cases
  • combine_to_utc()  — UTC conversion correctness for Asia/Kolkata and UTC
  • format_dt_local() — display string output
  • is_in_past()      — future, past, boundary
  • example_date_string() — returns a valid parseable date string
  • current_time_display() — returns a non-empty string
"""

from datetime import date, datetime, time, timezone, timedelta

import pytest
import pytz

from bot.utils.datetime_utils import (
    calculate_next_occurrence,
    calculate_snooze_datetime,
    combine_to_utc,
    current_time_display,
    example_date_string,
    format_date_heading,
    format_date_only,
    format_dt_local,
    format_time_only,
    get_day_boundaries_utc,
    get_local_date_and_time,
    is_in_past,
    parse_date,
    parse_time,
)


# ===========================================================================
# parse_date
# ===========================================================================

class TestParseDate:
    def test_valid_date(self) -> None:
        result = parse_date("07/10/2026")
        assert result == date(2026, 10, 7)

    def test_leading_zeros_required(self) -> None:
        """Day and month must have exactly 2 digits."""
        assert parse_date("7/10/2026") is None   # single-digit day
        assert parse_date("07/1/2026") is None   # single-digit month

    def test_wrong_separator(self) -> None:
        assert parse_date("07-10-2026") is None
        assert parse_date("07.10.2026") is None

    def test_wrong_order(self) -> None:
        """YYYY/MM/DD (ISO order) should NOT parse — we require DD/MM/YYYY."""
        assert parse_date("2026/10/07") is None

    def test_empty_string(self) -> None:
        assert parse_date("") is None

    def test_random_text(self) -> None:
        assert parse_date("tomorrow") is None
        assert parse_date("next Monday") is None

    def test_strips_whitespace(self) -> None:
        """Trailing/leading spaces should be stripped."""
        result = parse_date("  07/10/2026  ")
        assert result == date(2026, 10, 7)

    def test_invalid_day(self) -> None:
        """Day 32 does not exist."""
        assert parse_date("32/10/2026") is None

    def test_invalid_month(self) -> None:
        """Month 13 does not exist."""
        assert parse_date("07/13/2026") is None

    def test_leap_year_valid(self) -> None:
        """29 Feb on a leap year is valid."""
        result = parse_date("29/02/2024")
        assert result == date(2024, 2, 29)

    def test_leap_year_invalid(self) -> None:
        """29 Feb on a non-leap year is invalid."""
        assert parse_date("29/02/2025") is None

    def test_first_of_january(self) -> None:
        result = parse_date("01/01/2025")
        assert result == date(2025, 1, 1)


# ===========================================================================
# parse_time
# ===========================================================================

class TestParseTime:
    def test_valid_morning(self) -> None:
        result = parse_time("09:30")
        assert result == time(9, 30)

    def test_valid_midnight(self) -> None:
        result = parse_time("00:00")
        assert result == time(0, 0)

    def test_valid_end_of_day(self) -> None:
        result = parse_time("23:59")
        assert result == time(23, 59)

    def test_invalid_hour(self) -> None:
        assert parse_time("24:00") is None
        assert parse_time("25:30") is None

    def test_invalid_minute(self) -> None:
        assert parse_time("09:60") is None

    def test_12_hour_format_rejected(self) -> None:
        """AM/PM format should not parse."""
        assert parse_time("09:30 AM") is None
        assert parse_time("9:30pm") is None

    def test_wrong_separator(self) -> None:
        assert parse_time("09.30") is None
        assert parse_time("09-30") is None

    def test_empty_string(self) -> None:
        assert parse_time("") is None

    def test_strips_whitespace(self) -> None:
        result = parse_time("  14:00  ")
        assert result == time(14, 0)

    def test_single_digit_hour_rejected(self) -> None:
        """HH:MM requires two-digit hour."""
        assert parse_time("9:30") is None


# ===========================================================================
# combine_to_utc
# ===========================================================================

class TestCombineToUtc:
    def test_kolkata_to_utc_offset(self) -> None:
        """
        Asia/Kolkata is UTC+5:30.
        09:30 IST → 04:00 UTC.
        """
        d = date(2026, 10, 7)
        t = time(9, 30)
        result = combine_to_utc(d, t, "Asia/Kolkata")

        assert result.tzinfo is not None, "Result must be timezone-aware"
        assert result.year == 2026
        assert result.month == 10
        assert result.day == 7
        assert result.hour == 4
        assert result.minute == 0

    def test_utc_timezone_no_offset(self) -> None:
        """UTC has no offset; local time == UTC time."""
        d = date(2026, 10, 7)
        t = time(12, 0)
        result = combine_to_utc(d, t, "UTC")

        assert result.hour == 12
        assert result.minute == 0

    def test_result_is_utc_aware(self) -> None:
        """The returned datetime must be UTC-aware (tzinfo == UTC)."""
        d = date(2026, 10, 7)
        t = time(9, 0)
        result = combine_to_utc(d, t, "Asia/Kolkata")

        # Confirm it equals the same moment expressed in utc
        expected_utc = datetime(2026, 10, 7, 3, 30, tzinfo=timezone.utc)
        assert result == expected_utc

    def test_invalid_timezone_raises(self) -> None:
        with pytest.raises(Exception):  # pytz.UnknownTimeZoneError
            combine_to_utc(date(2026, 10, 7), time(9, 0), "Mars/Olympus")

    def test_new_york_negative_offset(self) -> None:
        """America/New_York is UTC-4 (EDT) in October."""
        d = date(2026, 10, 7)
        t = time(12, 0)  # noon EDT
        result = combine_to_utc(d, t, "America/New_York")
        # EDT = UTC-4 → noon EDT = 16:00 UTC
        assert result.hour == 16


# ===========================================================================
# format_dt_local
# ===========================================================================

class TestFormatDtLocal:
    def test_formats_as_expected(self) -> None:
        """
        A known UTC datetime should format correctly in Asia/Kolkata.
        UTC 04:00 = IST 09:30.
        """
        dt_utc = datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc)
        result = format_dt_local(dt_utc, "Asia/Kolkata")
        assert result == "07 Oct 2026 at 09:30"

    def test_utc_timezone_unchanged(self) -> None:
        dt_utc = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
        result = format_dt_local(dt_utc, "UTC")
        assert result == "07 Oct 2026 at 12:00"

    def test_returns_string(self) -> None:
        dt_utc = datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc)
        result = format_dt_local(dt_utc, "Asia/Kolkata")
        assert isinstance(result, str)
        assert len(result) > 0


# ===========================================================================
# is_in_past
# ===========================================================================

class TestIsInPast:
    def test_future_datetime_not_past(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        assert is_in_past(future) is False

    def test_past_datetime_is_past(self) -> None:
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        assert is_in_past(past) is True

    def test_far_future_not_past(self) -> None:
        far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        assert is_in_past(far_future) is False

    def test_far_past_is_past(self) -> None:
        far_past = datetime(2000, 1, 1, tzinfo=timezone.utc)
        assert is_in_past(far_past) is True


# ===========================================================================
# example_date_string
# ===========================================================================

class TestExampleDateString:
    def test_returns_valid_parseable_date(self) -> None:
        """The returned string must be parseable by parse_date()."""
        result = example_date_string("Asia/Kolkata")
        parsed = parse_date(result)
        assert parsed is not None, f"example_date_string returned unparseable value: {result!r}"

    def test_is_in_future(self) -> None:
        """Tomorrow's date must not be in the past."""
        from datetime import date as date_cls
        result = example_date_string("Asia/Kolkata")
        parsed = parse_date(result)
        tz = pytz.timezone("Asia/Kolkata")
        today = datetime.now(tz).date()
        assert parsed > today


# ===========================================================================
# current_time_display
# ===========================================================================

class TestCurrentTimeDisplay:
    def test_returns_non_empty_string(self) -> None:
        result = current_time_display("Asia/Kolkata")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_colon(self) -> None:
        """HH:MM format must have a colon."""
        result = current_time_display("UTC")
        assert ":" in result


# ===========================================================================
# Phase 3: get_day_boundaries_utc
# ===========================================================================

class TestGetDayBoundariesUtc:
    def test_kolkata_boundary_offsets(self) -> None:
        """
        In Asia/Kolkata (UTC+5:30):
        07/10/2026 00:00:00.000000 IST == 06/10/2026 18:30:00 UTC.
        07/10/2026 23:59:59.999999 IST == 07/10/2026 18:29:59.999999 UTC.
        """
        d = date(2026, 10, 7)
        start_utc, end_utc = get_day_boundaries_utc("Asia/Kolkata", d)

        assert start_utc.tzinfo is not None
        assert end_utc.tzinfo is not None
        assert start_utc == datetime(2026, 10, 6, 18, 30, tzinfo=timezone.utc)
        assert end_utc.year == 2026
        assert end_utc.month == 10
        assert end_utc.day == 7
        assert end_utc.hour == 18
        assert end_utc.minute == 29

    def test_utc_boundary(self) -> None:
        d = date(2026, 10, 7)
        start_utc, end_utc = get_day_boundaries_utc("UTC", d)
        assert start_utc == datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)
        assert end_utc.date() == d

    def test_default_target_date_is_today(self) -> None:
        start_utc, end_utc = get_day_boundaries_utc("Asia/Kolkata")
        tz = pytz.timezone("Asia/Kolkata")
        today = datetime.now(tz).date()
        assert start_utc.astimezone(tz).date() == today
        assert end_utc.astimezone(tz).date() == today


# ===========================================================================
# Phase 3: format_time_only & format_date_only & format_date_heading
# ===========================================================================

class TestListingFormatting:
    def test_format_time_only(self) -> None:
        # UTC 04:30 == IST 10:00
        dt = datetime(2026, 10, 7, 4, 30, tzinfo=timezone.utc)
        assert format_time_only(dt, "Asia/Kolkata") == "10:00"

    def test_format_date_only(self) -> None:
        dt = datetime(2026, 10, 7, 4, 30, tzinfo=timezone.utc)
        assert format_date_only(dt, "Asia/Kolkata") == "07 Oct 2026"

    def test_format_date_heading_today(self) -> None:
        tz = pytz.timezone("Asia/Kolkata")
        now_local = datetime.now(tz)
        now_utc = now_local.astimezone(timezone.utc)
        heading = format_date_heading(now_utc, "Asia/Kolkata")
        assert heading.startswith("Today, ")

    def test_format_date_heading_tomorrow(self) -> None:
        tz = pytz.timezone("Asia/Kolkata")
        tomorrow_local = datetime.now(tz) + timedelta(days=1)
        tomorrow_utc = tomorrow_local.astimezone(timezone.utc)
        heading = format_date_heading(tomorrow_utc, "Asia/Kolkata")
        assert heading.startswith("Tomorrow, ")

    def test_format_date_heading_future(self) -> None:
        future_utc = datetime(2035, 12, 25, 12, 0, tzinfo=timezone.utc)
        heading = format_date_heading(future_utc, "Asia/Kolkata")
        assert "25 Dec" in heading


# ===========================================================================
# Phase 4: get_local_date_and_time
# ===========================================================================

class TestGetLocalDateAndTime:
    def test_extracts_correct_local_components(self) -> None:
        # UTC 04:30 == IST 10:00 on 07/10/2026
        dt = datetime(2026, 10, 7, 4, 30, tzinfo=timezone.utc)
        local_d, local_t = get_local_date_and_time(dt, "Asia/Kolkata")
        assert local_d == date(2026, 10, 7)
        assert local_t == time(10, 0)

    def test_cross_day_boundary(self) -> None:
        # UTC 19:30 on 06/10/2026 == IST 01:00 on 07/10/2026
        dt = datetime(2026, 10, 6, 19, 30, tzinfo=timezone.utc)
        local_d, local_t = get_local_date_and_time(dt, "Asia/Kolkata")
        assert local_d == date(2026, 10, 7)
        assert local_t == time(1, 0)


# ===========================================================================
# Phase 6: calculate_snooze_datetime
# ===========================================================================

class TestCalculateSnoozeDatetime:
    def test_snooze_10m(self) -> None:
        now_utc = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
        res = calculate_snooze_datetime(now_utc, "10m", "Asia/Kolkata")
        assert res == datetime(2026, 10, 7, 10, 10, tzinfo=timezone.utc)

    def test_snooze_30m(self) -> None:
        now_utc = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
        res = calculate_snooze_datetime(now_utc, "30m", "Asia/Kolkata")
        assert res == datetime(2026, 10, 7, 10, 30, tzinfo=timezone.utc)

    def test_snooze_1h(self) -> None:
        now_utc = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
        res = calculate_snooze_datetime(now_utc, "1h", "Asia/Kolkata")
        assert res == datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc)

    def test_snooze_tomorrow_preserves_local_time(self) -> None:
        # Original due: 07 Oct 2026 15:00 IST == 09:30 UTC
        orig_due_utc = datetime(2026, 10, 7, 9, 30, tzinfo=timezone.utc)
        # Snoozed at: 07 Oct 2026 15:05 IST == 09:35 UTC
        now_utc = datetime(2026, 10, 7, 9, 35, tzinfo=timezone.utc)

        res = calculate_snooze_datetime(
            now_utc, "tomorrow", "Asia/Kolkata", original_due_utc=orig_due_utc
        )
        # Expected: 08 Oct 2026 15:00 IST == 09:30 UTC
        assert res == datetime(2026, 10, 8, 9, 30, tzinfo=timezone.utc)

    def test_snooze_tomorrow_without_original_due(self) -> None:
        # If original_due is None, it uses now_utc's local time tomorrow
        now_utc = datetime(2026, 10, 7, 9, 30, tzinfo=timezone.utc)
        res = calculate_snooze_datetime(now_utc, "tomorrow", "Asia/Kolkata")
        assert res == datetime(2026, 10, 8, 9, 30, tzinfo=timezone.utc)

    def test_snooze_naive_datetime_raises(self) -> None:
        naive_now = datetime(2026, 10, 7, 10, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            calculate_snooze_datetime(naive_now, "10m", "Asia/Kolkata")

    def test_snooze_invalid_type_raises(self) -> None:
        now_utc = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="Unsupported snooze_type"):
            calculate_snooze_datetime(now_utc, "invalid", "Asia/Kolkata")


# ===========================================================================
# Phase 6: calculate_next_occurrence
# ===========================================================================

class TestCalculateNextOccurrence:
    def test_daily_recurrence(self) -> None:
        # Base: 07 Oct 2026 10:00 IST == 04:30 UTC
        base_utc = datetime(2026, 10, 7, 4, 30, tzinfo=timezone.utc)
        next_utc = calculate_next_occurrence(base_utc, "daily", "Asia/Kolkata")
        # Next: 08 Oct 2026 10:00 IST == 04:30 UTC
        assert next_utc == datetime(2026, 10, 8, 4, 30, tzinfo=timezone.utc)

    def test_weekly_recurrence(self) -> None:
        # Base: 07 Oct 2026 10:00 IST == 04:30 UTC
        base_utc = datetime(2026, 10, 7, 4, 30, tzinfo=timezone.utc)
        next_utc = calculate_next_occurrence(base_utc, "weekly", "Asia/Kolkata")
        # Next: 14 Oct 2026 10:00 IST == 04:30 UTC
        assert next_utc == datetime(2026, 10, 14, 4, 30, tzinfo=timezone.utc)

    def test_monthly_recurrence(self) -> None:
        # Base: 15 Oct 2026 10:00 IST == 04:30 UTC
        base_utc = datetime(2026, 10, 15, 4, 30, tzinfo=timezone.utc)
        next_utc = calculate_next_occurrence(base_utc, "monthly", "Asia/Kolkata")
        # Next: 15 Nov 2026 10:00 IST == 04:30 UTC
        assert next_utc == datetime(2026, 11, 15, 4, 30, tzinfo=timezone.utc)

    def test_monthly_recurrence_month_end_clamping(self) -> None:
        # Base: 31 Jan 2026 10:00 IST == 04:30 UTC
        # Feb 2026 only has 28 days -> clamped to 28 Feb
        base_utc = datetime(2026, 1, 31, 4, 30, tzinfo=timezone.utc)
        next_utc = calculate_next_occurrence(base_utc, "monthly", "Asia/Kolkata")
        assert next_utc == datetime(2026, 2, 28, 4, 30, tzinfo=timezone.utc)

    def test_monthly_recurrence_leap_year(self) -> None:
        # 2028 is a leap year (Feb has 29 days)
        base_utc = datetime(2028, 1, 31, 4, 30, tzinfo=timezone.utc)
        next_utc = calculate_next_occurrence(base_utc, "monthly", "Asia/Kolkata")
        assert next_utc == datetime(2028, 2, 29, 4, 30, tzinfo=timezone.utc)

    def test_advances_past_after_utc_threshold(self) -> None:
        # Task was due 5 days ago, recurring daily
        base_utc = datetime(2026, 10, 1, 4, 30, tzinfo=timezone.utc)
        # Completed today: 06 Oct 2026 05:00 UTC
        now_utc = datetime(2026, 10, 6, 5, 0, tzinfo=timezone.utc)
        next_utc = calculate_next_occurrence(
            base_utc, "daily", "Asia/Kolkata", after_utc=now_utc
        )
        # Next occurrence should be strictly after now_utc: 07 Oct 2026 04:30 UTC
        assert next_utc > now_utc
        assert next_utc == datetime(2026, 10, 7, 4, 30, tzinfo=timezone.utc)

    def test_naive_base_raises(self) -> None:
        naive = datetime(2026, 10, 7, 10, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            calculate_next_occurrence(naive, "daily", "Asia/Kolkata")

    def test_unsupported_recurrence_raises(self) -> None:
        base_utc = datetime(2026, 10, 7, 4, 30, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="Unsupported recurrence rule"):
            calculate_next_occurrence(base_utc, "yearly", "Asia/Kolkata")

