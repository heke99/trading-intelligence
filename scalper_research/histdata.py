"""Local-only HistData Generic ASCII ticks with exact fixed EST clock conversion.

No archives are downloaded, ZIPs extracted, prices rescaled, volumes synthesized,
timestamps made unique, or trading/training assertions established by this module.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading_intelligence.common import DataError, json_bytes, load_json
from .market import _archive, _atomic_write, _metadata, _now, _price, _utc_time, load_quotes

MAX_BYTES = 32 * 1024 * 1024
MAX_SPEC_BYTES = 64 * 1024
MAX_ROWS = 500_000
MAX_NATIVE_BYTES = 256 * 1024 * 1024
FORMAT = "histdata_generic_ascii_tick_v1"
SYMBOLS = frozenset({"EURUSD", "GBPJPY", "EURJPY", "XAUUSD", "NSXUSD"})
CLOCK_EVIDENCE_URL = "https://www.histdata.com/f-a-q/"
FORMAT_EVIDENCE_URL = "https://www.histdata.com/f-a-q/data-files-detailed-specification/"
_DATE = re.compile(r"[0-9]{8} [0-9]{9}\Z", re.ASCII)
_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]+)?\Z", re.ASCII)
_HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_EST = timezone(timedelta(hours=-5))
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_FALSE_CLAIMS = (
    "broker_verified", "training_ready", "full_history_verified",
    "model_trained", "real_market_model_trained", "trading_enabled",
    "expert_trade_history", "forward_verified", "broker_orders_sent",
    "automated_download_permitted", "rights_verified",
)
_FLAGS = (
    "SOURCE_NOT_BROKER_VERIFIED", "FULL_HISTORY_NOT_VERIFIED",
    "VENDOR_INDICATIVE_QUOTES_NOT_EXECUTION_OR_EXPERT_TRADES",
    "SOURCE_ROW_ORDER_NOT_VERIFIED_EXCHANGE_SEQUENCE",
    "NATIVE_VOLUME_NOT_VERIFIED_TRADING_VOLUME",
)


def _read(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError:
        raise DataError("INPUT_READ_FAILED") from None
    if len(raw) > limit:
        raise DataError("INPUT_TOO_LARGE")
    return raw


def _clock(text: str) -> int:
    """Interpret exactly three native fractional digits; never apply DST."""
    if not _DATE.fullmatch(text):
        raise DataError("HISTDATA_TIMESTAMP_INVALID")
    try:
        local = datetime.strptime(text, "%Y%m%d %H%M%S%f").replace(tzinfo=_EST)
        utc = local.astimezone(timezone.utc)
        elapsed = utc - _EPOCH
        milliseconds = (
            elapsed.days * 86_400_000 + elapsed.seconds * 1_000
            + elapsed.microseconds // 1_000
        )
    except (ValueError, OverflowError):
        raise DataError("HISTDATA_TIMESTAMP_INVALID") from None
    if milliseconds <= 0:
        raise DataError("HISTDATA_TIMESTAMP_INVALID")
    return milliseconds



def _source_text(value: Any, error: str) -> str:
    if (
        not isinstance(value, str) or not value.strip() or len(value) > 4096
        or any(ord(character) < 32 and character not in "\n\t" for character in value)
    ):
        raise DataError(error)
    return value


def _spec(raw: bytes, source_hash: str) -> tuple[dict, dict]:
    spec = load_json(raw)
    if not isinstance(spec, dict):
        raise DataError("HISTDATA_SPEC_SCHEMA")
    if type(spec.get("schema_version")) is not int or spec["schema_version"] != 1:
        raise DataError("HISTDATA_SPEC_VERSION")
    if spec.get("format") != FORMAT:
        raise DataError("HISTDATA_FORMAT_REQUIRED")
    expected = spec.get("source_file_sha256")
    if not isinstance(expected, str) or not _HASH.fullmatch(expected):
        raise DataError("HISTDATA_SOURCE_HASH_REQUIRED")
    if expected != source_hash:
        raise DataError("HISTDATA_SOURCE_HASH_MISMATCH")
    if not isinstance(spec.get("symbol"), str) or spec["symbol"] not in SYMBOLS:
        raise DataError("HISTDATA_SYMBOL_UNSUPPORTED")
    if spec.get("native_timestamp_basis") != "fixed_est_milliseconds":
        raise DataError("HISTDATA_CLOCK_BASIS_REQUIRED")
    offset = spec.get("native_timezone_utc_offset_minutes")
    if type(offset) is not int or offset != -300:
        raise DataError("HISTDATA_FIXED_EST_REQUIRED")
    evidence = _source_text(
        spec.get("source_clock_evidence"), "HISTDATA_CLOCK_EVIDENCE_REQUIRED"
    )
    source = spec.get("source")
    if not isinstance(source, dict) or source.get("symbol") != spec["symbol"]:
        raise DataError("HISTDATA_SOURCE_SCHEMA")
    expected_currency = "JPY" if spec["symbol"] in {"GBPJPY", "EURJPY"} else "USD"
    if source.get("price_currency") != expected_currency:
        raise DataError("HISTDATA_PRICE_CURRENCY_MISMATCH")
    if source.get("timestamp_basis") != "utc_epoch_milliseconds":
        raise DataError("HISTDATA_OUTPUT_CLOCK_BASIS_REQUIRED")
    # Only understood provenance fields cross into the derived dataset.
    # Any original unsupported assertions remain exclusively in the raw spec.
    metadata = {
        key: source[key] for key in (
            "schema_version", "source_id", "symbol", "price_currency",
            "timestamp_basis", "timezone_evidence", "data_origin", "usage_rights",
            "rights_evidence",
        ) if key in source
    }
    # Preserve explicit user assertions for each intended use. These are not
    # independently verified rights and never imply a ready or trained model.
    if "training_usage_rights" in source:
        training = source["training_usage_rights"]
        if training not in ("synthetic_only", "not_verified", "user_asserted_permitted"):
            raise DataError("HISTDATA_TRAINING_RIGHTS_INVALID")
        if training == "synthetic_only" and source.get("data_origin") != "synthetic_fixture":
            raise DataError("HISTDATA_TRAINING_RIGHTS_ORIGIN_CONFLICT")
        if training == "user_asserted_permitted":
            _source_text(
                source.get("training_rights_evidence"),
                "HISTDATA_TRAINING_RIGHTS_EVIDENCE_REQUIRED",
            )
        metadata["training_usage_rights"] = training
    if "training_rights_evidence" in source:
        metadata["training_rights_evidence"] = _source_text(
            source["training_rights_evidence"], "HISTDATA_TRAINING_RIGHTS_EVIDENCE_REQUIRED"
        )
    for field in (
        "attribution", "source_url", "source_record_url", "source_download_url",
        "license", "license_url", "license_evidence",
    ):
        if field in source:
            metadata[field] = _source_text(
                source[field], "HISTDATA_SOURCE_PROVENANCE_INVALID"
            )
    metadata.update({field: False for field in _FALSE_CLAIMS})
    metadata.update(
        timezone_evidence=(
            "HistData publisher FAQ: fixed EST (UTC-05:00) without daylight "
            "saving; all native YYYYMMDD HHMMSSmmm values converted by +5 hours. "
            + CLOCK_EVIDENCE_URL
        ),
        source_clock_evidence=evidence,
        native_timestamp_basis="fixed_est_milliseconds",
        native_timezone_utc_offset_minutes=-300,
        native_timestamp_precision="milliseconds",
        native_row_order_preserved=True,
        derived_csv_source_row_rule="original source_row = derived CSV physical line - 1",
        native_same_timestamp_rows_preserved=True,
        source_format=FORMAT,
        source_format_evidence=FORMAT_EVIDENCE_URL,
        source_clock_evidence_url=CLOCK_EVIDENCE_URL,
        source_file_sha256=source_hash,
        source_export_status="completed",
        quote_kind="vendor_indicative_bidask",
        price_conversion="literal_decimal_bidask_without_rescaling",
        volume_feature_present=False,
        orderflow_feature_present=False,
        executable_liquidity_verified=False,
        quality_flags=list(_FLAGS),
    )
    return spec, _metadata(json_bytes(metadata))


def _native_number(text: str, *, price: bool) -> Decimal:
    if len(text) > 100 or not _DECIMAL.fullmatch(text):
        raise DataError("HISTDATA_NUMBER_INVALID")
    if price:
        return _price(text)
    value = Decimal(text)
    if not value.is_finite() or value < 0 or abs(value.adjusted()) > 100:
        raise DataError("HISTDATA_VOLUME_FIELD_INVALID")
    return value


def _convert(raw: bytes, staging: Path, metadata: dict) -> dict:
    if raw.startswith(b"PK"):
        raise DataError("HISTDATA_CSV_REQUIRED")
    try:
        text = raw.decode("ascii")
    except UnicodeError:
        raise DataError("HISTDATA_CSV_ENCODING") from None
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=",", strict=True)
    csv_path = staging / "quotes.csv"
    evidence_path = staging / "native_ticks.jsonl"
    metadata_path = staging / "quotes.metadata.json"
    quote_digest, native_digest = hashlib.sha256(), hashlib.sha256()
    quote_bytes = native_bytes = count = duplicate_count = max_gap = 0
    first = previous = None
    nonzero_volume_rows = 0
    with csv_path.open("wb") as quotes, evidence_path.open("wb") as native:
        header = b"time_msc,bid,ask\n"
        quotes.write(header)
        quote_digest.update(header)
        quote_bytes += len(header)
        try:
            while True:
                physical_row = reader.line_num + 1
                try:
                    fields = next(reader)
                except StopIteration:
                    break
                if count >= MAX_ROWS:
                    raise DataError("HISTDATA_ROW_LIMIT")
                if len(fields) != 4 or reader.line_num != physical_row:
                    raise DataError("HISTDATA_CSV_ROW_SCHEMA")
                date_text, bid_text, ask_text, volume_text = fields
                clock = _clock(date_text)
                bid = _native_number(bid_text, price=True)
                ask = _native_number(ask_text, price=True)
                volume = _native_number(volume_text, price=False)
                if ask < bid:
                    raise DataError("MARKET_CROSSED_QUOTE")
                if previous is not None:
                    if clock < previous:
                        raise DataError("MARKET_CLOCK_NOT_NONDECREASING")
                    gap = clock - previous
                    duplicate_count += gap == 0
                    max_gap = max(max_gap, gap)
                quote_raw = f"{clock},{bid_text},{ask_text}\n".encode("ascii")
                quote_bytes += len(quote_raw)
                if quote_bytes > MAX_BYTES:
                    raise DataError("HISTDATA_DERIVED_CSV_TOO_LARGE")
                quotes.write(quote_raw)
                quote_digest.update(quote_raw)
                # Strings retain publisher spelling, including trailing zeros.
                record = {
                    "schema_version": 1,
                    "record_kind": "native_histdata_bidask_tick",
                    "source_file_sha256": metadata["source_file_sha256"],
                    "symbol": metadata["symbol"],
                    "source_row": physical_row,
                    "native_time_text": date_text,
                    "native_timestamp_basis": "fixed_est_milliseconds",
                    "time_msc": clock,
                    "raw_bid": bid_text,
                    "raw_ask": ask_text,
                    "raw_volume": volume_text,
                    "volume_feature_present": False,
                }
                native_raw = (json.dumps(
                    record, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False
                ) + "\n").encode("ascii")
                native_bytes += len(native_raw)
                if native_bytes > MAX_NATIVE_BYTES:
                    raise DataError("HISTDATA_NATIVE_EVIDENCE_TOO_LARGE")
                native.write(native_raw)
                native_digest.update(native_raw)
                nonzero_volume_rows += volume != 0
                first = clock if first is None else first
                previous = clock
                count += 1
        except csv.Error:
            raise DataError("HISTDATA_CSV_INVALID") from None
        for stream in (quotes, native):
            stream.flush()
            os.fsync(stream.fileno())
    if count == 0:
        raise DataError("MARKET_NO_QUOTES")
    flags = list(_FLAGS)
    if duplicate_count:
        flags.append("EQUAL_TIMESTAMP_ORDER_UNVERIFIED")
    if nonzero_volume_rows:
        flags.append("NONZERO_NATIVE_VOLUME_UNVERIFIED_NOT_USED")
    metadata["quality_flags"] = flags
    _atomic_write(metadata_path, json_bytes(metadata))
    # Reuse the normal quote validator after conversion. Neither a converter
    # success nor a matching hash validates source completeness or usage rights.
    dataset = load_quotes(csv_path, metadata_path)
    flags = list(dict.fromkeys(dataset.quality_flags + flags))
    for path in (csv_path, evidence_path, metadata_path):
        path.chmod(0o400)
    return {
        "quote_count": count,
        "duplicate_timestamp_rows": duplicate_count,
        "max_gap_ms": max_gap,
        "first_time_msc": first,
        "last_time_msc": previous,
        "first_time_utc": _utc_time(first),
        "last_time_utc": _utc_time(previous),
        "quotes_csv_sha256": quote_digest.hexdigest(),
        "quotes_metadata_sha256": dataset.metadata_sha256,
        "native_ticks_sha256": native_digest.hexdigest(),
        "nonzero_native_volume_rows": nonzero_volume_rows,
        "quality_flags": flags,
    }


def import_histdata(file: Path, spec_path: Path, out: Path) -> dict:
    """Archive local inputs and publish only a completely validated dataset."""
    out = Path(out)
    raw_dir = out / "raw" / "histdata"
    run_id = uuid.uuid4().hex
    run_dir = out / "histdata-runs" / run_id
    try:
        for directory in (out, out / "raw", raw_dir, out / "histdata-runs", run_dir):
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)
    except OSError:
        raise DataError("HISTDATA_OUTPUT_WRITE_FAILED") from None
    manifest: dict[str, Any] = {
        "schema_version": 1, "run_id": run_id, "status": "running",
        "record_kind": "histdata_local_csv_conversion",
        "started_at_utc": _now(), "completed_at_utc": None,
        "network_requests": 0, "downloaded_bytes": 0,
        "source_count": 0, "quote_count": 0,
        "source_file_sha256": None, "spec_sha256": None,
        "source_hash_matches_spec": False,
        "raw_csv_path": None, "raw_spec_path": None,
        "quotes_csv_path": None, "quotes_metadata_path": None,
        "native_ticks_path": None, "quality_flags": [], "errors": [],
        "manifest_path": str(run_dir / "manifest.json"),
        **{field: False for field in _FALSE_CLAIMS},
    }
    manifest_path = run_dir / "manifest.json"
    _atomic_write(manifest_path, json_bytes(manifest))
    staging = None
    try:
        raw = _read(Path(file), MAX_BYTES)
        digest, archived_csv = _archive(raw, raw_dir, "csv")
        archived_csv.chmod(0o400)
        manifest.update(source_file_sha256=digest, raw_csv_path=str(archived_csv))
        spec_raw = _read(Path(spec_path), MAX_SPEC_BYTES)
        spec_digest, archived_spec = _archive(spec_raw, raw_dir, "histdata-spec.json")
        archived_spec.chmod(0o400)
        manifest.update(spec_sha256=spec_digest, raw_spec_path=str(archived_spec))
        spec, metadata = _spec(spec_raw, digest)
        manifest["source_hash_matches_spec"] = True
        staging = Path(tempfile.mkdtemp(prefix=".histdata-", dir=run_dir))
        converted = _convert(raw, staging, metadata)
        published = run_dir / "dataset"
        os.replace(staging, published)
        staging = None
        manifest.update(
            status="completed", source_count=1,
            source_id=metadata["source_id"], symbol=spec["symbol"],
            price_currency=metadata["price_currency"],
            data_origin=metadata["data_origin"], usage_rights=metadata["usage_rights"],
            rights_evidence=metadata.get("rights_evidence"),
            native_timestamp_basis="fixed_est_milliseconds",
            native_timezone_utc_offset_minutes=-300,
            native_timestamp_precision="milliseconds",
            timestamp_basis="utc_epoch_milliseconds",
            source_clock_evidence=spec["source_clock_evidence"],
            metadata=metadata,
            quotes_csv_path=str(published / "quotes.csv"),
            quotes_metadata_path=str(published / "quotes.metadata.json"),
            native_ticks_path=str(published / "native_ticks.jsonl"),
            **converted,
        )
    except DataError as error:
        manifest.update(status="failed", errors=[str(error)])
    except KeyboardInterrupt:
        manifest.update(status="failed", errors=["INTERRUPTED"])
    except OSError:
        manifest.update(status="failed", errors=["HISTDATA_OUTPUT_WRITE_FAILED"])
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
    manifest["completed_at_utc"] = _now()
    _atomic_write(manifest_path, json_bytes(manifest))
    return manifest
