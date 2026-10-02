"""Bounded local tick sharding; original bytes and equal-clock groups survive.

This is an intake/integrity layer, not a multi-shard trainer. There is no network,
calendar inference, gap filling, expert imitation, or broker order interface.
"""
from __future__ import annotations

import csv
import hashlib
import os
import re
import tempfile
import uuid
from pathlib import Path

from trading_intelligence.common import DataError, json_bytes, load_json
from .market import (MAX_BYTES, MAX_ROWS, _atomic_write, _metadata, _now,
                     _price, _time_msc, _utc_time, load_quotes)

MAX_SOURCE_BYTES = 1024 * 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024
MAX_LINE_BYTES = 4096
MAX_SHARDS = 4096
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
HEADER = b"time_msc,bid,ask\n"
DAY_MS = 86_400_000
_NAME = re.compile(r"[0-9]{6}\.csv\Z", re.ASCII)
_HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_FALSE = {"training_ready": False, "full_history_verified": False,
          "broker_verified": False, "trading_enabled": False,
          "training_performed": False, "rights_verified": False,
          "model_trained": False, "real_market_model_trained": False,
          "expert_trade_history": False, "forward_verified": False}


def _hash_file(path: Path, limit: int) -> tuple[str, int]:
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as source:
        while raw := source.read(min(1024 * 1024, limit - count + 1)):
            count += len(raw)
            if count > limit:
                raise DataError("CORPUS_SOURCE_TOO_LARGE")
            digest.update(raw)
    return digest.hexdigest(), count


def _archive_file(source: Path, directory: Path, suffix: str, limit: int) -> tuple[Path, str, int]:
    """Copy once, bounded memory; validate the copy, never reopen caller inputs."""
    descriptor, temporary = tempfile.mkstemp(prefix=".archiving-", dir=directory)
    digest, count = hashlib.sha256(), 0
    try:
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as stream:
            while raw := stream.read(min(1024 * 1024, limit - count + 1)):
                count += len(raw)
                if count > limit:
                    raise DataError("CORPUS_SOURCE_TOO_LARGE")
                target.write(raw)
                digest.update(raw)
            target.flush()
            os.fsync(target.fileno())
        final = directory / (digest.hexdigest() + "." + suffix)
        try:
            os.link(temporary, final)
        except FileExistsError:
            if final.is_symlink() or _hash_file(final, limit) != (digest.hexdigest(), count):
                raise DataError("CORPUS_ARCHIVE_CONFLICT") from None
        final.chmod(0o400)
        return final, digest.hexdigest(), count
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _line(stream, *, first: bool = False) -> list[str] | None:
    raw = stream.readline(MAX_LINE_BYTES + 1)
    if not raw:
        return None
    if len(raw) > MAX_LINE_BYTES:
        raise DataError("CORPUS_LINE_TOO_LARGE")
    try:
        text = raw.decode("utf-8-sig" if first else "utf-8")
        # Physical-line format is intentional: no multiline or blank records.
        return next(csv.reader([text], strict=True))
    except (UnicodeError, csv.Error, StopIteration):
        raise DataError("CORPUS_CSV_INVALID") from None


def _rows(path: Path, metadata: dict, *, histdata: bool):
    with path.open("rb") as stream:
        line_number = 0
        positions = None
        if not histdata:
            header = _line(stream, first=True)
            line_number = 1
            required = {"time_msc", "bid", "ask"}
            if (not header or len(set(header)) != len(header)
                    or set(header) not in (required, required | {"symbol"})):
                raise DataError("MARKET_CSV_HEADER_SCHEMA")
            positions = {name: header.index(name) for name in header}
        while True:
            values = _line(stream, first=(line_number == 0))
            if values is None:
                break
            line_number += 1
            if histdata:
                from .histdata import _clock, _native_number
                if len(values) != 4:
                    raise DataError("HISTDATA_CSV_ROW_SCHEMA")
                timestamp = _time_msc(str(_clock(values[0])))
                bid, ask = values[1:3]
                _native_number(bid, price=True)
                _native_number(ask, price=True)
                _native_number(values[3], price=False)
            else:
                if len(values) != len(positions):
                    raise DataError("MARKET_CSV_ROW_SCHEMA")
                if "symbol" in positions and values[positions["symbol"]] != metadata["symbol"]:
                    raise DataError("MARKET_SYMBOL_MISMATCH")
                timestamp = _time_msc(values[positions["time_msc"]])
                bid, ask = values[positions["bid"]], values[positions["ask"]]
            if _price(ask) < _price(bid):
                raise DataError("MARKET_CROSSED_QUOTE")
            yield timestamp, (f"{timestamp},{bid},{ask}\n").encode("ascii"), line_number


def shard_ticks(file: Path, evidence_path: Path, out: Path, *,
                source_format: str = "utc_bidask_csv_v1", max_shard_rows: int = MAX_ROWS,
                max_shard_bytes: int = MAX_BYTES, gap_report_ms: int = 60_000) -> dict:
    """Archive a <=1 GiB local CSV and produce independently importable shards.

    Split at UTC midnight or capacity, exclusively BETWEEN equal-ms groups.
    Oversized groups fail instead of being truncated, sorted or timestamp-shifted.
    All source row/price order is retained. No shard is published on input failure.
    """
    if (source_format not in ("utc_bidask_csv_v1", "histdata_generic_ascii_tick_v1")
            or type(max_shard_rows) is not int or not 1 <= max_shard_rows <= MAX_ROWS
            or type(max_shard_bytes) is not int or not 64 <= max_shard_bytes <= MAX_BYTES
            or type(gap_report_ms) is not int or not 1 <= gap_report_ms <= DAY_MS):
        raise DataError("CORPUS_POLICY_INVALID")
    out = Path(out).resolve()
    run_id = uuid.uuid4().hex
    run = out / "tick-corpus-runs" / run_id
    archive = out / "raw" / "tick-corpus"
    staging = run / ".staging"
    for directory in (run, archive, staging):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    manifest_path = run / "manifest.json"
    manifest = {"schema_version": 1, "record_kind": "tick_corpus", "run_id": run_id,
                "status": "running", "started_at_utc": _now(), "completed_at_utc": None,
                "manifest_path": str(manifest_path), "source_format": source_format,
                "shards": [], "errors": [], "network_used": False, **_FALSE,
                "multishard_training_implemented": False, "cross_shard_state_preserved": False,
                "calendar_coverage_verified": False, "gap_filling_performed": False,
                "expert_trade_history": False, "max_shard_rows": max_shard_rows,
                "max_shard_bytes": max_shard_bytes, "gap_report_ms": gap_report_ms}
    _atomic_write(manifest_path, json_bytes(manifest))
    try:
        original, digest, byte_count = _archive_file(Path(file), archive, "csv", MAX_SOURCE_BYTES)
        manifest.update(raw_csv_path=str(original), raw_csv_sha256=digest, source_bytes=byte_count)
        evidence, evidence_hash, _ = _archive_file(Path(evidence_path), archive, "json", MAX_METADATA_BYTES)
        manifest.update(raw_evidence_path=str(evidence), raw_evidence_sha256=evidence_hash)
        if source_format == "histdata_generic_ascii_tick_v1":
            from .histdata import _spec
            _, metadata = _spec(evidence.read_bytes(), digest)
        else:
            metadata = _metadata(evidence.read_bytes())
        # Reject unencodable provenance inside this run's failure receipt.
        json_bytes(metadata)
        manifest.update(source_id=metadata["source_id"], symbol=metadata["symbol"],
                        price_currency=metadata["price_currency"], data_origin=metadata["data_origin"],
                        usage_rights=metadata["usage_rights"])
        chunk, group = bytearray(HEADER), bytearray()
        shards = []
        chunk_rows = group_rows = total = duplicates = max_gap = gap_count = 0
        previous = first = group_time = chunk_first = chunk_last = None
        group_start_row = group_end_row = chunk_start_row = chunk_end_row = None
        samples = []

        def publish_chunk():
            nonlocal chunk, chunk_rows, chunk_first, chunk_last, chunk_start_row, chunk_end_row
            if not chunk_rows:
                return
            if len(shards) >= MAX_SHARDS:
                raise DataError("CORPUS_SHARD_LIMIT")
            name = f"{len(shards):06d}.csv"
            shard_metadata = dict(metadata)
            shard_metadata.update(corpus_source_sha256=digest,
                                  corpus_source_first_physical_row=chunk_start_row,
                                  corpus_source_last_physical_row=chunk_end_row,
                                  corpus_source_row_rule="original physical row = shard physical row - 2 + corpus_source_first_physical_row",
                                  cross_shard_state_preserved=False, **_FALSE)
            # HistData's single-file physical-row rule is not valid for later shards.
            if "derived_csv_source_row_rule" in shard_metadata:
                shard_metadata["derived_csv_source_row_rule"] = shard_metadata["corpus_source_row_rule"]
            metadata_bytes = json_bytes(shard_metadata)
            _atomic_write(staging / name, bytes(chunk))
            _atomic_write(staging / (name + ".metadata.json"), metadata_bytes)
            shards.append({"file": name, "metadata_file": name + ".metadata.json",
                           "sha256": hashlib.sha256(chunk).hexdigest(),
                           "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
                           "bytes": len(chunk), "rows": chunk_rows,
                           "first_time_msc": chunk_first, "last_time_msc": chunk_last,
                           "utc_day": _utc_time(chunk_first)[:10],
                           "source_first_physical_row": chunk_start_row,
                           "source_last_physical_row": chunk_end_row})
            chunk, chunk_rows = bytearray(HEADER), 0

        def consume_group():
            nonlocal chunk_rows, chunk_first, chunk_last, chunk_start_row, chunk_end_row
            if not group_rows:
                return
            if chunk_rows and (chunk_rows + group_rows > max_shard_rows
                               or len(chunk) + len(group) > max_shard_bytes
                               or chunk_first // DAY_MS != group_time // DAY_MS):
                publish_chunk()
            if not chunk_rows:
                chunk_first, chunk_start_row = group_time, group_start_row
            chunk.extend(group)
            chunk_rows += group_rows
            chunk_last, chunk_end_row = group_time, group_end_row

        for timestamp, raw, physical_row in _rows(original, metadata,
                histdata=source_format == "histdata_generic_ascii_tick_v1"):
            if previous is not None:
                gap = timestamp - previous
                if gap < 0:
                    raise DataError("MARKET_CLOCK_NOT_NONDECREASING")
                duplicates += gap == 0
                max_gap = max(max_gap, gap)
                if gap > gap_report_ms:
                    gap_count += 1
                    if len(samples) < 50:
                        samples.append({"previous_time_msc": previous, "next_time_msc": timestamp,
                                        "gap_ms": gap, "next_source_physical_row": physical_row})
            if group_time != timestamp:
                consume_group()
                group, group_rows, group_time, group_start_row = bytearray(), 0, timestamp, physical_row
            group.extend(raw)
            group_rows += 1
            group_end_row = physical_row
            if group_rows > max_shard_rows or len(group) + len(HEADER) > max_shard_bytes:
                raise DataError("CORPUS_EQUAL_CLOCK_GROUP_TOO_LARGE")
            first = timestamp if first is None else first
            previous, total = timestamp, total + 1
        if not total:
            raise DataError("MARKET_NO_QUOTES")
        consume_group()
        publish_chunk()
        # Detect archive mutation during parsing before publishing ANY dataset.
        if _hash_file(original, MAX_SOURCE_BYTES) != (digest, byte_count):
            raise DataError("CORPUS_ARCHIVE_CHANGED")
        if _hash_file(evidence, MAX_METADATA_BYTES)[0] != evidence_hash:
            raise DataError("CORPUS_ARCHIVE_CHANGED")
        dataset = run / "dataset"
        staging.rename(dataset)
        manifest.update(status="completed", dataset_directory=str(dataset), shards=shards,
                        quote_count=total, duplicate_timestamp_rows=duplicates,
                        first_time_msc=first, last_time_msc=previous,
                        first_time_utc=_utc_time(first), last_time_utc=_utc_time(previous),
                        observed_max_gap_ms=max_gap, observed_gap_count_over_threshold=gap_count,
                        observed_gap_samples=samples, shard_count=len(shards),
                        observed_utc_days=sorted({s["utc_day"] for s in shards}),
                        gaps_classified_as_missing_data=False,
                        boundary_policy="UTC day/capacity; equal timestamp groups never split",
                        training_boundary_policy="NOT_IMPLEMENTED; independent tick-run resets per shard; not a corpus-trained model")
    except DataError as error:
        manifest.update(status="failed", errors=[str(error)])
    except UnicodeError:
        manifest.update(status="failed", errors=["CORPUS_METADATA_ENCODING"])
    except OSError:
        manifest.update(status="failed", errors=["CORPUS_LOCAL_IO_ERROR"])
    except KeyboardInterrupt:
        manifest.update(status="failed", errors=["INTERRUPTED"])
    manifest["completed_at_utc"] = _now()
    _atomic_write(manifest_path, json_bytes(manifest))
    return manifest


def verify_tick_corpus(manifest_path: Path) -> dict:
    """Recheck every shard's bytes, quotes, metadata, row ranges and strict edges.

    Integrity against a LOCAL unsigned manifest is not authenticity, training
    permission or calendar completeness. Does not read arbitrary manifest paths.
    """
    manifest_path = Path(manifest_path).resolve()
    with manifest_path.open("rb") as source:
        raw = source.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise DataError("CORPUS_MANIFEST_TOO_LARGE")
    manifest = load_json(raw)
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1 or manifest.get("record_kind") != "tick_corpus"
            or manifest.get("status") != "completed"
            or any(manifest.get(k) is not False for k in _FALSE)
            or any(manifest.get(k) is not False for k in (
                "multishard_training_implemented", "cross_shard_state_preserved",
                "calendar_coverage_verified", "gap_filling_performed"))
            or manifest.get("source_format") not in ("utc_bidask_csv_v1", "histdata_generic_ascii_tick_v1")
            or any(not isinstance(manifest.get(k), str) or not _HASH.fullmatch(manifest[k])
                   for k in ("raw_csv_sha256", "raw_evidence_sha256"))
            or type(manifest.get("max_shard_rows")) is not int
            or not 1 <= manifest["max_shard_rows"] <= MAX_ROWS
            or type(manifest.get("max_shard_bytes")) is not int
            or not 64 <= manifest["max_shard_bytes"] <= MAX_BYTES):
        raise DataError("CORPUS_MANIFEST_INVALID")
    if any(type(manifest.get(k)) is not int for k in (
            "quote_count", "duplicate_timestamp_rows", "shard_count",
            "first_time_msc", "last_time_msc")):
        raise DataError("CORPUS_MANIFEST_INVALID")
    shards = manifest.get("shards")
    if not isinstance(shards, list) or not 1 <= len(shards) <= MAX_SHARDS:
        raise DataError("CORPUS_MANIFEST_INVALID")
    dataset_dir = manifest_path.parent / "dataset"
    if dataset_dir.is_symlink():
        raise DataError("CORPUS_UNSAFE_PATH")
    count = duplicates = 0
    previous_time = previous_row = None
    for index, shard in enumerate(shards):
        name = f"{index:06d}.csv"
        if (not isinstance(shard, dict) or not _NAME.fullmatch(str(shard.get("file", "")))
                or shard["file"] != name or shard.get("metadata_file") != name + ".metadata.json"):
            raise DataError("CORPUS_UNSAFE_PATH")
        if any(type(shard.get(k)) is not int for k in (
                "rows", "bytes", "first_time_msc", "last_time_msc",
                "source_first_physical_row", "source_last_physical_row")):
            raise DataError("CORPUS_SHARD_EVIDENCE_MISMATCH")
        csv_path, metadata_path = dataset_dir / name, dataset_dir / (name + ".metadata.json")
        if csv_path.is_symlink() or metadata_path.is_symlink():
            raise DataError("CORPUS_UNSAFE_PATH")
        dataset = load_quotes(csv_path, metadata_path)
        if (dataset.raw_sha256 != shard.get("sha256")
                or dataset.metadata_sha256 != shard.get("metadata_sha256")):
            raise DataError("CORPUS_SHARD_HASH_MISMATCH")
        quotes, meta = dataset.quotes, dataset.metadata
        start, end = shard.get("source_first_physical_row"), shard.get("source_last_physical_row")
        expected_start = (1 if manifest.get("source_format") == "histdata_generic_ascii_tick_v1" else 2) if previous_row is None else previous_row + 1
        if (type(start) is not int or type(end) is not int or start != expected_start
                or end - start + 1 != len(quotes) or shard.get("rows") != len(quotes)
                or shard.get("bytes") != csv_path.stat().st_size
                or len(quotes) > manifest["max_shard_rows"]
                or shard["bytes"] > manifest["max_shard_bytes"]
                or shard.get("first_time_msc") != quotes[0].time_msc
                or shard.get("last_time_msc") != quotes[-1].time_msc
                or quotes[0].time_msc // DAY_MS != quotes[-1].time_msc // DAY_MS
                or shard.get("utc_day") != _utc_time(quotes[0].time_msc)[:10]
                or meta.get("corpus_source_first_physical_row") != start
                or meta.get("corpus_source_last_physical_row") != end
                or meta.get("corpus_source_sha256") != manifest.get("raw_csv_sha256")
                or meta.get("cross_shard_state_preserved") is not False
                or any(meta.get(k) is not False for k in _FALSE)
                or any(meta.get(k) != manifest.get(k) for k in ("source_id", "symbol", "price_currency", "data_origin", "usage_rights"))):
            raise DataError("CORPUS_SHARD_EVIDENCE_MISMATCH")
        if previous_time is not None and quotes[0].time_msc <= previous_time:
            raise DataError("CORPUS_BOUNDARY_OVERLAP")
        count += len(quotes)
        duplicates += sum(a.time_msc == b.time_msc for a, b in zip(quotes, quotes[1:]))
        previous_time, previous_row = quotes[-1].time_msc, end
        if index == 0 and manifest.get("first_time_msc") != quotes[0].time_msc:
            raise DataError("CORPUS_TOTAL_MISMATCH")
    if (manifest.get("quote_count") != count or manifest.get("last_time_msc") != previous_time
            or manifest.get("duplicate_timestamp_rows") != duplicates or manifest.get("shard_count") != len(shards)):
        raise DataError("CORPUS_TOTAL_MISMATCH")
    return {"status": "completed", "integrity_verified_against_local_unsigned_manifest": True,
            "manifest_sha256": hashlib.sha256(raw).hexdigest(), "shard_count": len(shards),
            "quote_count": count, "duplicate_timestamp_rows": duplicates,
            "source_authenticity_verified": False, "raw_source_rechecked": False,
            "calendar_coverage_verified": False, "network_used": False, **_FALSE}
