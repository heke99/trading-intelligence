"""Convert an explicitly specified local BI5 file; never acquire market data.

Legacy hourly files and current daily files share a binary record shape, but
have different clock bases. Neither the filename nor the instrument determines
the clock base or the price divisor here. The caller supplies their evidence.
"""
from __future__ import annotations

import csv
import hashlib
import json
import lzma
import math
import os
import struct
import tempfile
import uuid
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from trading_intelligence.common import DataError, json_bytes, load_json
from . import __version__
from .market import MAX_EPOCH_MILLISECONDS, _archive, _atomic_write, _metadata, _now, _utc_time

MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 10 * 1024 * 1024
MAX_RECORDS = 500_000
LZMA_MEMORY_LIMIT = 64 * 1024 * 1024
FORMAT = "dukascopy_bi5_20byte_be"
_PERIODS = {"utc_hour": 3_600_000, "utc_day": 86_400_000}
_RECORD = struct.Struct(">IIIff")


def _read_input(path: Path) -> bytes:
    try:
        with Path(path).open("rb") as source:
            raw = source.read(MAX_INPUT_BYTES + 1)
    except OSError:
        raise DataError("BI5_INPUT_READ_FAILED") from None
    if len(raw) > MAX_INPUT_BYTES:
        raise DataError("BI5_INPUT_TOO_LARGE")
    return raw


def _specification(raw: bytes) -> tuple[dict, dict]:
    specification = load_json(raw)
    if not isinstance(specification, dict):
        raise DataError("BI5_SPECIFICATION_SCHEMA")
    if (type(specification.get("schema_version")) is not int
            or specification["schema_version"] != 1):
        raise DataError("BI5_SPECIFICATION_VERSION")
    if specification.get("format") != FORMAT:
        raise DataError("BI5_FORMAT_REQUIRED")
    time_base = specification.get("time_base")
    if not isinstance(time_base, str) or time_base not in _PERIODS:
        raise DataError("BI5_TIME_BASE_REQUIRED")
    base_time = specification.get("base_time_msc")
    if (type(base_time) is not int or not 0 <= base_time <= MAX_EPOCH_MILLISECONDS
            or base_time % _PERIODS[time_base] != 0):
        raise DataError("BI5_UTC_BASE_BOUNDARY_INVALID")
    divisor = specification.get("price_divisor")
    if type(divisor) is not int or divisor not in {10 ** power for power in range(10)}:
        raise DataError("BI5_PRICE_DIVISOR_INVALID")
    scale_evidence = specification.get("price_scale_evidence")
    if (not isinstance(scale_evidence, str) or not scale_evidence.strip()
            or len(scale_evidence) > 4096
            or any(ord(character) < 32 and character not in "\n\t" for character in scale_evidence)):
        raise DataError("BI5_PRICE_SCALE_EVIDENCE_REQUIRED")
    source_metadata = specification.get("source_metadata")
    if not isinstance(source_metadata, dict):
        raise DataError("BI5_SOURCE_METADATA_REQUIRED")
    # Reuse the quote contract, including its conservative origin and rights
    # vocabulary. Export availability is never interpreted as a usage licence.
    metadata = _metadata(json_bytes(source_metadata))
    return specification, metadata


def _decompress(raw: bytes) -> bytes:
    if not raw:
        raise DataError("BI5_COMPRESSED_EMPTY")
    try:
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_AUTO, memlimit=LZMA_MEMORY_LIMIT)
        decoded = decoder.decompress(raw, max_length=MAX_DECOMPRESSED_BYTES + 1)
    except lzma.LZMAError:
        raise DataError("BI5_LZMA_INVALID_OR_MEMORY_LIMIT") from None
    if len(decoded) > MAX_DECOMPRESSED_BYTES:
        raise DataError("BI5_DECOMPRESSED_SIZE_LIMIT")
    if not decoder.eof:
        raise DataError("BI5_LZMA_TRUNCATED")
    if decoder.unused_data:
        raise DataError("BI5_COMPRESSED_TRAILING_DATA")
    if not decoded:
        raise DataError("BI5_NO_QUOTES")
    if len(decoded) % _RECORD.size:
        raise DataError("BI5_RECORD_SIZE_INVALID")
    if len(decoded) // _RECORD.size > MAX_RECORDS:
        raise DataError("BI5_RECORD_LIMIT")
    return decoded


def _row_outputs(decoded: bytes, specification: dict, run_dir: Path, raw_sha256: str) -> dict:
    """Validate every row before publishing either complete derived output."""
    csv_descriptor, csv_temporary = tempfile.mkstemp(prefix=".quotes-", dir=run_dir)
    evidence_descriptor, evidence_temporary = tempfile.mkstemp(prefix=".evidence-", dir=run_dir)
    csv_path, evidence_path = run_dir / "quotes.csv", run_dir / "row_evidence.jsonl"
    base_time = specification["base_time_msc"]
    period = _PERIODS[specification["time_base"]]
    previous_offset = None
    first_time = last_time = None
    equal_clock_rows = max_gap = 0
    evidence_digest = hashlib.sha256()
    try:
        with (os.fdopen(csv_descriptor, "w", encoding="utf-8", newline="") as csv_output,
              os.fdopen(evidence_descriptor, "w", encoding="utf-8", newline="") as evidence_output,
              localcontext() as context):
            context.prec = 1024
            context.Emax, context.Emin = 999_999_999, -999_999_999
            writer = csv.writer(csv_output, lineterminator="\n")
            writer.writerow(["time_msc", "bid", "ask"])
            divisor = Decimal(specification["price_divisor"])
            for index in range(len(decoded) // _RECORD.size):
                start = index * _RECORD.size
                chunk = decoded[start:start + _RECORD.size]
                offset, ask_integer, bid_integer, ask_volume, bid_volume = _RECORD.unpack(chunk)
                if offset >= period:
                    raise DataError("BI5_OFFSET_OUTSIDE_TIME_BASE")
                timestamp = base_time + offset
                if not 0 < timestamp <= MAX_EPOCH_MILLISECONDS:
                    raise DataError("BI5_TIMESTAMP_INVALID")
                if previous_offset is not None:
                    if offset < previous_offset:
                        raise DataError("BI5_CLOCK_NOT_NONDECREASING")
                    equal_clock_rows += offset == previous_offset
                    max_gap = max(max_gap, offset - previous_offset)
                if ask_integer == 0 or bid_integer == 0:
                    raise DataError("BI5_PRICE_NONPOSITIVE")
                if ask_integer < bid_integer:
                    raise DataError("BI5_CROSSED_QUOTE")
                if any(not math.isfinite(volume) or volume < 0 for volume in (ask_volume, bid_volume)):
                    raise DataError("BI5_VOLUME_INVALID")
                bid = format(Decimal(bid_integer) / divisor, "f")
                ask = format(Decimal(ask_integer) / divisor, "f")
                writer.writerow([timestamp, bid, ask])
                row = {
                    "schema_version": 1,
                    "record_kind": "bi5_market_quote_evidence",
                    "source_record_index": index + 1,
                    "decompressed_byte_offset": start,
                    "source_bi5_sha256": raw_sha256,
                    "offset_milliseconds": offset,
                    "time_base": specification["time_base"],
                    "time_msc": timestamp,
                    "ask_integer": ask_integer,
                    "bid_integer": bid_integer,
                    "price_divisor": specification["price_divisor"],
                    "ask": ask,
                    "bid": bid,
                    "ask_volume_float32": repr(ask_volume),
                    "bid_volume_float32": repr(bid_volume),
                    "ask_volume_float32_bytes_hex": chunk[12:16].hex(),
                    "bid_volume_float32_bytes_hex": chunk[16:20].hex(),
                    "volume_interpretation": "source_float32_not_executable_liquidity",
                    "broker_verified": False,
                    "training_ready": False,
                }
                evidence_line = json.dumps(row, sort_keys=True, separators=(",", ":"),
                                           allow_nan=False) + "\n"
                evidence_output.write(evidence_line)
                evidence_digest.update(evidence_line.encode("utf-8"))
                first_time = timestamp if first_time is None else first_time
                last_time, previous_offset = timestamp, offset
            for output in (csv_output, evidence_output):
                output.flush()
                os.fsync(output.fileno())
        os.replace(csv_temporary, csv_path)
        os.replace(evidence_temporary, evidence_path)
        csv_path.chmod(0o600)
        evidence_path.chmod(0o600)
    finally:
        for temporary in (csv_temporary, evidence_temporary):
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {
        "quote_count": len(decoded) // _RECORD.size,
        "duplicate_timestamp_rows": equal_clock_rows,
        "max_gap_ms": max_gap,
        "first_time_msc": first_time,
        "last_time_msc": last_time,
        "first_time_utc": _utc_time(first_time),
        "last_time_utc": _utc_time(last_time),
        "output_csv": str(csv_path),
        "row_evidence_path": str(evidence_path),
        "row_evidence_sha256": evidence_digest.hexdigest(),
        "output_csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
    }


def convert_bi5(file: Path, spec_path: Path, out: Path) -> dict:
    """Archive local bytes and specification, then convert one explicit time bucket.

    The final manifest always states whether conversion completed. A failed run
    preserves successfully archived inputs but does not expose partial quotes as
    a complete dataset. No network requests or broker connections are possible.
    """
    out = Path(out)
    raw_dir = out / "raw" / "bi5"
    run_id = uuid.uuid4().hex
    run_dir = out / "bi5-runs" / run_id
    for directory in (out, out / "raw", raw_dir, out / "bi5-runs", run_dir):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    manifest: dict[str, Any] = {
        "schema_version": 1, "software_version": __version__, "adapter_version": 1,
        "run_id": run_id, "status": "running", "started_at_utc": _now(),
        "completed_at_utc": None, "record_kind": "local_bi5_conversion",
        "manifest_path": str(run_dir / "manifest.json"),
        "source_bi5_sha256": None, "source_spec_sha256": None,
        "raw_bi5_path": None, "raw_spec_path": None,
        "output_csv": None, "output_metadata": None, "row_evidence_path": None,
        "quote_count": 0, "errors": [], "quality_flags": [],
        "training_ready": False, "full_history_verified": False,
        "broker_verified": False, "trading_enabled": False, "model_trained": False,
        "training_rights": "not_verified",
    }
    _atomic_write(run_dir / "manifest.json", json_bytes(manifest))
    try:
        compressed = _read_input(file)
        digest, archived_file = _archive(compressed, raw_dir, "bi5")
        manifest.update(source_bi5_sha256=digest, raw_bi5_path=str(archived_file))
        specification_raw = _read_input(spec_path)
        spec_digest, archived_spec = _archive(specification_raw, raw_dir, "json")
        manifest.update(source_spec_sha256=spec_digest, raw_spec_path=str(archived_spec))
        specification, source_metadata = _specification(specification_raw)
        manifest.update(
            format=FORMAT, time_base=specification["time_base"],
            base_time_msc=specification["base_time_msc"],
            price_divisor=specification["price_divisor"],
            price_scale_evidence=specification["price_scale_evidence"],
            source_id=source_metadata["source_id"], symbol=source_metadata["symbol"],
            data_origin=source_metadata["data_origin"], usage_rights=source_metadata["usage_rights"],
        )
        decoded = _decompress(compressed)
        derived = _row_outputs(decoded, specification, run_dir, digest)
        metadata = {
            **source_metadata,
            "broker_verified": False, "training_ready": False, "full_history_verified": False,
            "model_trained": False, "trading_enabled": False,
            "training_rights": "not_verified",
            "bi5_conversion": {
                "adapter_version": 1, "format": FORMAT,
                "time_base": specification["time_base"],
                "base_time_msc": specification["base_time_msc"],
                "price_divisor": specification["price_divisor"],
                "price_scale_evidence": specification["price_scale_evidence"],
                "source_bi5_sha256": digest, "source_spec_sha256": spec_digest,
                "quote_order": "preserved_binary_record_order_including_equal_clocks",
                "volume_interpretation": "source_float32_not_executable_liquidity",
                "original_retrieved_at_utc": None,
                "retrieval_time_basis": "not_inferred_from_local_conversion_clock",
            },
        }
        metadata_path = run_dir / "metadata.json"
        _atomic_write(metadata_path, json_bytes(metadata))
        flags = ["SOURCE_NOT_BROKER_VERIFIED", "FULL_HISTORY_NOT_VERIFIED",
                 "BI5_LAYOUT_AND_PRICE_SCALE_USER_SUPPLIED", "VOLUME_NOT_EXECUTABLE_LIQUIDITY"]
        if source_metadata["data_origin"] == "synthetic_fixture":
            flags.append("SYNTHETIC_FIXTURE_NOT_MARKET_HISTORY")
        if source_metadata["usage_rights"] == "not_verified":
            flags.append("USAGE_RIGHTS_NOT_VERIFIED")
        if derived["duplicate_timestamp_rows"]:
            flags.append("EQUAL_TIMESTAMP_ORDER_UNVERIFIED")
        manifest.update(**derived, output_metadata=str(metadata_path), status="completed",
                        output_metadata_sha256=hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
                        quality_flags=flags)
    except DataError as error:
        manifest.update(status="failed", errors=[str(error)])
    except OSError:
        manifest.update(status="failed", errors=["BI5_LOCAL_IO_ERROR"])
    finally:
        manifest["completed_at_utc"] = _now()
        _atomic_write(run_dir / "manifest.json", json_bytes(manifest))
    return manifest
