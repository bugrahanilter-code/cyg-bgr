"""Time helpers.

The whole platform stores naive UTC datetimes. Mixing naive and aware
datetimes is a classic source of subtle bugs, so there is exactly one way to
get "now" and exactly one way to convert to and from exchange millisecond
timestamps.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta


def utcnow() -> datetime:
    """Current UTC time as a naive datetime."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_ms(moment: datetime) -> int:
    """Convert a naive UTC datetime to exchange milliseconds."""
    return int(moment.replace(tzinfo=UTC).timestamp() * 1000)


def from_ms(milliseconds: int | float) -> datetime:
    """Convert exchange milliseconds to a naive UTC datetime."""
    return datetime.fromtimestamp(float(milliseconds) / 1000.0, tz=UTC).replace(tzinfo=None)


def day_start(moment: datetime | None = None) -> datetime:
    """Start of the UTC day containing the given moment."""
    moment = moment or utcnow()
    return datetime(moment.year, moment.month, moment.day)


def today_utc() -> date:
    """Current UTC calendar date."""
    return utcnow().date()


def seconds_since(moment: datetime | None) -> float | None:
    """Seconds elapsed since the given moment, or None."""
    if moment is None:
        return None
    return (utcnow() - moment).total_seconds()


def parse_iso_date(value: str) -> datetime:
    """Parse an ISO date or datetime string into a naive UTC datetime."""
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def add_minutes(moment: datetime, minutes: float) -> datetime:
    """Return moment shifted forward by the given number of minutes."""
    return moment + timedelta(minutes=minutes)
