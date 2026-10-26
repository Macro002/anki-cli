"""Small helpers shared by the services and protocol layers."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

import orjson

from .errors import ApiError

MAX_ID = 9223372036854775807
_ID = re.compile(r"[1-9][0-9]{0,18}")


def timestamp(seconds: float | None = None) -> str:
    """RFC 3339 UTC with millisecond precision, e.g. 2026-10-10T12:00:00.000Z."""
    value = time.time() if seconds is None else seconds
    return (datetime.fromtimestamp(value, timezone.utc)
            .isoformat(timespec="milliseconds").replace("+00:00", "Z"))


def entity_id(value: Any) -> int:
    """Parse a v1 entity ID: a positive signed 64-bit integer as a decimal string."""
    if not isinstance(value, str) or not _ID.fullmatch(value) or int(value) > MAX_ID:
        raise ApiError("invalidParams", "Expected a positive signed 64-bit decimal ID.")
    return int(value)


def interval(value: int) -> dict:
    """Anki stores learning intervals as negative seconds and review intervals as days."""
    return {"value": abs(int(value)), "unit": "seconds" if value < 0 else "days"}


def signed(value: dict) -> int:
    return -value["value"] if value["unit"] == "seconds" else value["value"]


def dumps(value: Any) -> bytes:
    return orjson.dumps(value, option=orjson.OPT_NON_STR_KEYS)


def loads(data: bytes | str) -> Any:
    return orjson.loads(data)


def summary(value: Any) -> dict:
    return {"id": str(value["id"]), "name": value["name"]}
