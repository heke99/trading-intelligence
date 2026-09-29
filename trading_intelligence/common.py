"""Strict parsing helpers; error messages never include input data or secrets."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 200_000


class DataError(ValueError):
    """A safe, stable error code suitable for logs and manifests."""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise DataError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _bad_constant(_: str) -> None:
    raise DataError("JSON_NONFINITE_NUMBER")


def load_json(raw: bytes) -> Any:
    if len(raw) > MAX_BYTES:
        raise DataError("INPUT_TOO_LARGE")
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs,
                          parse_float=Decimal, parse_constant=_bad_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError, InvalidOperation):
        raise DataError("INVALID_JSON") from None


def json_bytes(value: Any) -> bytes:
    def default(x: Any) -> str:
        if isinstance(x, Decimal) and x.is_finite():
            return str(x)
        raise TypeError("Unsupported value")
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False, default=default) + "\n").encode("utf-8")


def field(obj: dict, key: str, default: Any = None) -> Any:
    """Support documented PascalCase/camelCase; reject case collisions."""
    if not isinstance(obj, dict):
        raise DataError("OBJECT_SCHEMA")
    matches = [k for k in obj if k.casefold() == key.casefold()]
    if len(matches) > 1:
        raise DataError("AMBIGUOUS_FIELD")
    return obj[matches[0]] if matches else default


def positive_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise DataError("INVALID_ID")
    text = str(value)
    if not text.isascii() or not text.isdigit() or len(text) > 19:
        raise DataError("INVALID_ID")
    parsed = int(text)
    if not 0 < parsed <= 2**63 - 1:
        raise DataError("INVALID_ID")
    return parsed


def decimal_text(value: Any, *, required: bool = False, positive: bool = False,
                 nonnegative: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise DataError("MISSING_NUMBER")
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise DataError("INVALID_NUMBER")
    text = str(value).strip()
    if len(text) > 100:
        raise DataError("NUMBER_TOO_LONG")
    try:
        d = Decimal(text)
    except InvalidOperation:
        raise DataError("INVALID_NUMBER") from None
    if not d.is_finite() or abs(d.adjusted()) > 100:
        raise DataError("NONFINITE_OR_EXTREME_NUMBER")
    if positive and d <= 0 or nonnegative and d < 0:
        raise DataError("INVALID_QUANTITY")
    return str(d)


def read_limited(path) -> bytes:
    with path.open("rb") as f:
        raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise DataError("INPUT_TOO_LARGE")
    return raw
