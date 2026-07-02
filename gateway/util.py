"""Small shared helpers (datetime -> ISO-UTC, id minting)."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone


def iso(dt: datetime | None) -> str | None:
    """ISO-8601 with explicit UTC offset (clients parse offset or naive)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def short_id(prefix: str, n: int = 6) -> str:
    return f"{prefix}-{secrets.token_hex(n)[:n].upper()}"
