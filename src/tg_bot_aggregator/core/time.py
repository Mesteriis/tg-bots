from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)

__all__ = ["utc_now"]
