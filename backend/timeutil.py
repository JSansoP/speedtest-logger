from datetime import UTC, datetime


def to_utc_iso(value: datetime | None) -> str | None:
    """Serializes a naive UTC datetime as ISO 8601 with an explicit offset."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat() + "+00:00"
    return value.astimezone(UTC).isoformat()


def parse_utc(value: str) -> datetime:
    """Parses an ISO 8601 string into a naive UTC datetime."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed
