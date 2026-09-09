"""The monthly period boundaries the quota counts against."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from assistant_core.quota import current_period_start, next_period_start


def test_the_period_starts_on_the_first_of_the_month() -> None:
    assert current_period_start(datetime(2026, 9, 9, 13, 45, tzinfo=UTC)) == date(
        2026, 9, 1
    )


def test_the_period_is_read_in_utc_not_the_local_zone() -> None:
    """A local instant that is already the next UTC month counts there."""
    late = datetime(2026, 9, 30, 20, 30, tzinfo=ZoneInfo("America/New_York"))

    assert current_period_start(late) == date(2026, 10, 1)


def test_the_next_period_is_midnight_on_the_first() -> None:
    assert next_period_start(datetime(2026, 9, 9, 13, 45, tzinfo=UTC)) == datetime(
        2026, 10, 1, tzinfo=UTC
    )


def test_december_rolls_into_january_of_the_next_year() -> None:
    assert next_period_start(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == datetime(
        2027, 1, 1, tzinfo=UTC
    )
