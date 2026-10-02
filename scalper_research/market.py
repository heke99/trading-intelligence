"""Offline bid/ask quote import with explicit clock evidence and immutable inputs.

This research namespace never authenticates, sends orders, or trains a model.
Source rows are preserved in their original order, including duplicate clocks.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from trading_intelligence.common import DataError, json_bytes, load_json

MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 500_000
MAX_EPOCH_MILLISECONDS = 253_402_300_799_999
SCHEMA_VERSION = 1
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z", re.ASCII)
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z", re.ASCII)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_RECONSTRUCTION_CAVEATS = frozenset({
    "BOOTSTRAP_COMPLETION_ASSUMED", "CONTINUOUS_MATCHING_PHASE_UNVERIFIED",
    "DELETE_OR_MODIFY_NOT_EXECUTION_LABELS", "NATIVE_MESSAGE_CLOCK_NOT_RECEIVE_CLOCK",
    "SOURCE_ROW_ORDER_NOT_VERIFIED_EXCHANGE_SEQUENCE", "EQUAL_NS_PRIORITY_UNVERIFIED",
    "DERIVED_SAMPLED_VISIBLE_BIDASK_NOT_EXECUTABLE_LIQUIDITY",
    "SOURCE_EQUAL_MILLISECOND_ORDER_UNVERIFIED", "NATIVE_TIMESTAMP_NOT_RECEIVE_CLOCK",
    "DERIVED_BUCKET_END_QUOTE_NOT_NATIVE_TICK", "NO_EMPTY_BUCKET_FORWARD_FILL",
    "EVENT_TIME_TIMER_ASSUMED",
})
_GAP_CEILINGS = {"wse_required_max_quote_gap_ms": 60000,
                 "projection_required_max_quote_gap_ms": 1000}


@dataclass(frozen=True)
class Quote:
    time_msc: int
    bid: Decimal
    ask: Decimal
    source_row: int


@dataclass(frozen=True)
class QuoteDataset:
    quotes: list[Quote]
    metadata: dict
    raw_sha256: str
    metadata_sha256: str
    quality_flags: list[str]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_limited(path: Path) -> bytes:
    try:
        with Path(path).open("rb") as source:
            raw = source.read(MAX_BYTES + 1)
    except OSError:
        raise DataError("INPUT_READ_FAILED") from None
    if len(raw) > MAX_BYTES:
        raise DataError("INPUT_TOO_LARGE")
    return raw


def _required_text(metadata: dict, field: str, *, maximum: int = 4096) -> str:
    value = metadata.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise DataError("MARKET_METADATA_SCHEMA")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise DataError("MARKET_METADATA_SCHEMA")
    return value


def _metadata(raw: bytes) -> dict:
    metadata = load_json(raw)
    if not isinstance(metadata, dict):
        raise DataError("MARKET_METADATA_SCHEMA")
    if type(metadata.get("schema_version")) is not int or metadata["schema_version"] != 1:
        raise DataError("MARKET_METADATA_VERSION")
    source_id = _required_text(metadata, "source_id", maximum=128)
    if not _SAFE_ID.fullmatch(source_id) or source_id in (".", ".."):
        raise DataError("MARKET_SOURCE_ID_INVALID")
    for field in ("symbol", "price_currency"):
        value = _required_text(metadata, field, maximum=64)
        if value != value.strip() or any(character.isspace() for character in value):
            raise DataError("MARKET_METADATA_SCHEMA")
    if metadata.get("timestamp_basis") != "utc_epoch_milliseconds":
        raise DataError("MARKET_CLOCK_BASIS_REQUIRED")
    _required_text(metadata, "timezone_evidence")
    if metadata.get("data_origin") not in ("synthetic_fixture", "user_supplied_unverified"):
        raise DataError("MARKET_DATA_ORIGIN_INVALID")
    rights = metadata.get("usage_rights")
    if rights not in ("synthetic_only", "not_verified", "user_asserted_permitted"):
        raise DataError("MARKET_USAGE_RIGHTS_INVALID")
    if rights == "synthetic_only" and metadata["data_origin"] != "synthetic_fixture":
        raise DataError("MARKET_USAGE_RIGHTS_ORIGIN_CONFLICT")
    if rights == "user_asserted_permitted":
        _required_text(metadata, "rights_evidence")
    if "source_export_status" in metadata and metadata["source_export_status"] != "completed":
        raise DataError("MARKET_SOURCE_EXPORT_INCOMPLETE")
    for field in ("broker_verified", "training_ready", "full_history_verified"):
        if field in metadata and metadata[field] is not False:
            raise DataError("MARKET_UNSUPPORTED_VERIFICATION_CLAIM")
    for field, bound in _GAP_CEILINGS.items():
        if field in metadata:
            value = metadata[field]
            if type(value) is not int or not 1 <= value <= bound:
                raise DataError("MARKET_RECONSTRUCTION_GAP_POLICY_INVALID")
    return metadata


def validate_quote_execution(metadata: dict, config: object) -> None:
    """Apply every reconstruction ceiling so omitted buckets reset state.

    WSE snapshots and completed tick buckets deliberately omit invalid periods.
    Their explicit gap ceilings constrain replay, learning, stress and paper
    simulation. They do not establish executable liquidity or data approval.
    """
    ceilings = []
    for field, bound in _GAP_CEILINGS.items():
        if field in metadata:
            value = metadata[field]
            if type(value) is not int or not 1 <= value <= bound:
                raise DataError("MARKET_RECONSTRUCTION_GAP_POLICY_INVALID")
            ceilings.append(value)
    if ceilings:
        configured = getattr(config, "max_quote_gap_ms", None)
        if type(configured) is not int or not 1 <= configured <= min(ceilings):
            raise DataError("RECONSTRUCTED_QUOTE_GAP_POLICY_MISMATCH")


def _time_msc(value: str) -> int:
    if not value or len(value) > 15 or not value.isascii() or not value.isdigit():
        raise DataError("MARKET_TIMESTAMP_INVALID")
    parsed = int(value)
    if not 0 < parsed <= MAX_EPOCH_MILLISECONDS:
        raise DataError("MARKET_TIMESTAMP_INVALID")
    return parsed


def _price(value: str) -> Decimal:
    if not value or len(value) > 100 or not _NUMBER.fullmatch(value):
        raise DataError("MARKET_PRICE_INVALID")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise DataError("MARKET_PRICE_INVALID") from None
    if not number.is_finite() or number <= 0 or abs(number.adjusted()) > 100:
        raise DataError("MARKET_PRICE_INVALID")
    return number


def _load_bytes(csv_raw: bytes, metadata_raw: bytes) -> QuoteDataset:
    metadata = _metadata(metadata_raw)
    try:
        decoded = csv_raw.decode("utf-8-sig")
    except UnicodeError:
        raise DataError("MARKET_CSV_ENCODING") from None
    reader = csv.reader(io.StringIO(decoded, newline=""), delimiter=",", strict=True)
    try:
        headers = next(reader)
    except StopIteration:
        raise DataError("MARKET_CSV_EMPTY") from None
    except csv.Error:
        raise DataError("MARKET_CSV_INVALID") from None
    required = {"time_msc", "bid", "ask"}
    if (len(headers) != len(set(headers))
            or set(headers) not in (required, required | {"symbol"})):
        raise DataError("MARKET_CSV_HEADER_SCHEMA")
    positions = {name: index for index, name in enumerate(headers)}
    quotes: list[Quote] = []
    duplicate_timestamps = False
    try:
        while True:
            physical_row = reader.line_num + 1
            try:
                values = next(reader)
            except StopIteration:
                break
            if len(quotes) >= MAX_ROWS:
                raise DataError("MARKET_ROW_LIMIT")
            if len(values) != len(headers):
                raise DataError("MARKET_CSV_ROW_SCHEMA")
            if "symbol" in positions and values[positions["symbol"]] != metadata["symbol"]:
                raise DataError("MARKET_SYMBOL_MISMATCH")
            timestamp = _time_msc(values[positions["time_msc"]])
            bid, ask = _price(values[positions["bid"]]), _price(values[positions["ask"]])
            if ask < bid:
                raise DataError("MARKET_CROSSED_QUOTE")
            if quotes and timestamp < quotes[-1].time_msc:
                raise DataError("MARKET_CLOCK_NOT_NONDECREASING")
            if quotes and timestamp == quotes[-1].time_msc:
                duplicate_timestamps = True
            quotes.append(Quote(timestamp, bid, ask, physical_row))
    except csv.Error:
        raise DataError("MARKET_CSV_INVALID") from None
    if not quotes:
        raise DataError("MARKET_NO_QUOTES")
    flags = ["SOURCE_NOT_BROKER_VERIFIED", "FULL_HISTORY_NOT_VERIFIED"]
    if metadata["data_origin"] == "synthetic_fixture":
        flags.append("SYNTHETIC_FIXTURE_NOT_MARKET_HISTORY")
    if metadata["usage_rights"] == "not_verified":
        flags.append("USAGE_RIGHTS_NOT_VERIFIED")
    if duplicate_timestamps:
        flags.append("EQUAL_TIMESTAMP_ORDER_UNVERIFIED")
    if any(field in metadata for field in _GAP_CEILINGS):
        source_flags = metadata.get("quality_flags", [])
        if not isinstance(source_flags, list) or len(source_flags) > 32 or any(
                not isinstance(flag, str) for flag in source_flags):
            raise DataError("MARKET_RECONSTRUCTION_FLAGS_INVALID")
        for flag in source_flags:
            if flag in _RECONSTRUCTION_CAVEATS and flag not in flags:
                flags.append(flag)
    return QuoteDataset(quotes, metadata, _sha256(csv_raw), _sha256(metadata_raw), flags)


def load_quotes(csv_path: Path, metadata_path: Path) -> QuoteDataset:
    """Validate a complete local CSV; never sort, round, or discard its rows."""
    return _load_bytes(_read_limited(csv_path), _read_limited(metadata_path))


def _utc_time(timestamp: int) -> str:
    return (_EPOCH + timedelta(milliseconds=timestamp)).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, raw: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _archive(raw: bytes, raw_dir: Path, suffix: str) -> tuple[str, Path]:
    digest = _sha256(raw)
    target = raw_dir / f"{digest}.{suffix}"
    descriptor, temporary = tempfile.mkstemp(prefix=".archiving-", dir=raw_dir)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or _sha256(_read_limited(target)) != digest:
                raise DataError("MARKET_RAW_ARCHIVE_CONFLICT") from None
        target.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return digest, target


def _atomic_quotes(path: Path, quotes: list[Quote]) -> str:
    """Stream bounded input rows instead of retaining a second expanded dataset."""
    digest = hashlib.sha256()
    descriptor, temporary = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            for quote in quotes:
                raw = (json.dumps({
                    "schema_version": SCHEMA_VERSION,
                    "record_kind": "market_quote",
                    "time_msc": quote.time_msc,
                    "bid": str(quote.bid),
                    "ask": str(quote.ask),
                    "source_row": quote.source_row,
                }, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                    allow_nan=False) + "\n").encode("utf-8")
                output.write(raw)
                digest.update(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return digest.hexdigest()


def import_quotes(csv_path: Path, metadata_path: Path, out: Path) -> dict:
    """Archive inputs before validation; preserve a manifest on validation failure.

    Each invocation creates a new audit run; identical input bytes reuse immutable
    raw archives. Completed imports alone contain a normalized quotes.jsonl file.
    """
    out = Path(out)
    raw_dir = out / "raw" / "market"
    run_id = uuid.uuid4().hex
    run_dir = out / "market-runs" / run_id
    for directory in (out, out / "raw", raw_dir, out / "market-runs", run_dir):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "running",
        "record_kind": "market_quote",
        "started_at_utc": _now(),
        "completed_at_utc": None,
        "training_ready": False,
        "full_history_verified": False,
        "broker_verified": False,
        "trading_enabled": False,
        "source_count": 0,
        "quote_count": 0,
        "duplicate_timestamp_rows": 0,
        "max_gap_ms": None,
        "first_time_msc": None,
        "last_time_msc": None,
        "first_time_utc": None,
        "last_time_utc": None,
        "source_id": None,
        "symbol": None,
        "data_origin": None,
        "usage_rights": None,
        "csv_raw_sha256": None,
        "metadata_raw_sha256": None,
        "raw_csv_path": None,
        "raw_metadata_path": None,
        "normalized_quotes_path": None,
        "quality_flags": [],
        "errors": [],
        "manifest_path": str(run_dir / "manifest.json"),
    }
    _atomic_write(run_dir / "manifest.json", json_bytes(manifest))
    try:
        csv_raw = _read_limited(Path(csv_path))
        digest, archived_csv = _archive(csv_raw, raw_dir, "csv")
        manifest.update(csv_raw_sha256=digest, raw_csv_path=str(archived_csv))
        metadata_raw = _read_limited(Path(metadata_path))
        metadata_digest, archived_metadata = _archive(metadata_raw, raw_dir, "json")
        manifest.update(metadata_raw_sha256=metadata_digest,
                        raw_metadata_path=str(archived_metadata))
        dataset = _load_bytes(csv_raw, metadata_raw)
        gaps = [later.time_msc - earlier.time_msc
                for earlier, later in zip(dataset.quotes, dataset.quotes[1:])]
        normalized_path = run_dir / "quotes.jsonl"
        normalized_digest = _atomic_quotes(normalized_path, dataset.quotes)
        manifest.update(
            status="completed", source_count=1, quote_count=len(dataset.quotes),
            duplicate_timestamp_rows=sum(gap == 0 for gap in gaps),
            max_gap_ms=max(gaps, default=0),
            first_time_msc=dataset.quotes[0].time_msc,
            last_time_msc=dataset.quotes[-1].time_msc,
            first_time_utc=_utc_time(dataset.quotes[0].time_msc),
            last_time_utc=_utc_time(dataset.quotes[-1].time_msc),
            source_id=dataset.metadata["source_id"], symbol=dataset.metadata["symbol"],
            price_currency=dataset.metadata["price_currency"],
            timestamp_basis=dataset.metadata["timestamp_basis"],
            timezone_evidence=dataset.metadata["timezone_evidence"],
            data_origin=dataset.metadata["data_origin"],
            usage_rights=dataset.metadata["usage_rights"],
            rights_evidence=dataset.metadata.get("rights_evidence"),
            metadata=dataset.metadata,
            normalized_quotes_path=str(normalized_path),
            normalized_quotes_sha256=normalized_digest,
            quality_flags=dataset.quality_flags,
        )
    except DataError as error:
        manifest.update(status="failed", errors=[str(error)])
    except OSError:
        manifest.update(status="failed", errors=["MARKET_OUTPUT_WRITE_FAILED"])
    manifest["completed_at_utc"] = _now()
    _atomic_write(run_dir / "manifest.json", json_bytes(manifest))
    return manifest
