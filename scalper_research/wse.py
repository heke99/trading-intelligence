"""Local WSELOB order evidence and conditional, causal sampled visible quotes.

The depositor's notebook describes the fields and F/Y/A/M/D operations. This
independent implementation does not identify executions, queue priority or the
venue's continuous matching phase. A non-Y operation completing retransmission
is an explicit research assumption, never an exchange confirmation.
"""
from __future__ import annotations

import csv
import hashlib
import heapq
import json
import os
import re
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_intelligence.common import DataError, json_bytes, load_json
from .market import MAX_BYTES, MAX_ROWS, _archive, _atomic_write, _metadata, _now, _read_limited

FORMAT = "wselob_orders_v1"
MAX_INPUT_BYTES = 192 * 1024 * 1024
MAX_DAY_EVENTS = 500_000
MAX_TOTAL_EVENTS = 2_000_000
MAX_NATIVE_BYTES = 1024 * 1024 * 1024
MAX_LIVE_ORDERS = 100_000
CHUNK_ROWS = 4096
SYMBOLS = {"KGHM": 10783, "PKNORLEN": 11319, "PKOBP": 11314,
           "PZU": 10735, "PEKAO": 11322}
FIELDS = ("time", "priority_date", "order_date", "symbol_idx", "price", "agg_volume",
          "volume", "order_id", "num_orders", "side", "order_type", "action_type", "price_level")
_INTEGER_FIELDS = set(FIELDS) - {"order_type", "action_type"}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
FLAGS = ["SOURCE_NOT_BROKER_VERIFIED", "FULL_HISTORY_NOT_VERIFIED",
         "BOOTSTRAP_COMPLETION_ASSUMED", "CONTINUOUS_MATCHING_PHASE_UNVERIFIED",
         "DELETE_OR_MODIFY_NOT_EXECUTION_LABELS", "NATIVE_MESSAGE_CLOCK_NOT_RECEIVE_CLOCK",
         "SOURCE_ROW_ORDER_NOT_VERIFIED_EXCHANGE_SEQUENCE", "EQUAL_NS_PRIORITY_UNVERIFIED",
         "DERIVED_SAMPLED_VISIBLE_BIDASK_NOT_EXECUTABLE_LIQUIDITY"]


def _text(value, code):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise DataError(code)
    return value


def _specification(raw: bytes) -> tuple[dict, dict]:
    spec = load_json(raw)
    allowed = {"schema_version", "format", "expected_sha256", "symbol", "symbol_idx", "days",
               "sample_period_ms", "max_event_gap_ms", "source_clock_evidence",
               "retransmission_completion_policy", "source", "session_start_minute_warsaw",
               "session_end_minute_warsaw"}
    required = allowed - {"session_start_minute_warsaw", "session_end_minute_warsaw"}
    if not isinstance(spec, dict) or not required <= set(spec) <= allowed:
        raise DataError("WSE_SPEC_SCHEMA")
    if type(spec["schema_version"]) is not int or spec["schema_version"] != 1 or spec["format"] != FORMAT:
        raise DataError("WSE_SPEC_VERSION_OR_FORMAT")
    if not isinstance(spec["expected_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", spec["expected_sha256"]):
        raise DataError("WSE_EXPECTED_SHA256_REQUIRED")
    if (not isinstance(spec["symbol"], str) or spec["symbol"] not in SYMBOLS
            or type(spec["symbol_idx"]) is not int or spec["symbol_idx"] != SYMBOLS[spec["symbol"]]):
        raise DataError("WSE_SYMBOL_CONTRACT")
    days = spec["days"]
    if (not isinstance(days, list) or not 1 <= len(days) <= 10
            or any(not isinstance(day, str) or not re.fullmatch(r"2017[0-9]{4}", day) for day in days)
            or days != sorted(set(days))):
        raise DataError("WSE_DAYS_CONTRACT")
    try:
        for day in days:
            datetime.strptime(day, "%Y%m%d")
    except ValueError:
        raise DataError("WSE_DAYS_CONTRACT") from None
    period, gap = spec["sample_period_ms"], spec["max_event_gap_ms"]
    if (type(period) is not int or not 1 <= period <= 60_000
            or type(gap) is not int or not period <= gap <= 86_400_000):
        raise DataError("WSE_SAMPLING_CONTRACT")
    _text(spec["source_clock_evidence"], "WSE_NATIVE_CLOCK_EVIDENCE_REQUIRED")
    if spec["retransmission_completion_policy"] != "first_non_retransmission_event_assumption":
        raise DataError("WSE_BOOTSTRAP_POLICY_REQUIRED")
    lower, upper = spec.get("session_start_minute_warsaw", 600), spec.get("session_end_minute_warsaw", 960)
    if type(lower) is not int or type(upper) is not int or not 0 <= lower < upper <= 1440:
        raise DataError("WSE_SESSION_CONTRACT")
    spec = dict(spec, session_start_minute_warsaw=lower, session_end_minute_warsaw=upper)
    source = _metadata(json_bytes(spec["source"]))
    if source["symbol"] != spec["symbol"] or source["price_currency"] != "PLN":
        raise DataError("WSE_SOURCE_INSTRUMENT_CONFLICT")
    return spec, source


def _file_sha256(path: Path) -> tuple[str, int]:
    digest, count = hashlib.sha256(), 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                count += len(chunk)
                if count > MAX_INPUT_BYTES:
                    raise DataError("WSE_INPUT_SIZE_LIMIT")
                digest.update(chunk)
    except OSError:
        raise DataError("WSE_INPUT_READ_FAILED") from None
    return digest.hexdigest(), count


def _archive_file(path: Path, raw_dir: Path) -> tuple[str, Path, int]:
    """Copy, rather than link the caller's mutable inode, and hash incrementally."""
    descriptor, temporary = tempfile.mkstemp(prefix=".copying-", dir=raw_dir)
    digest, count = hashlib.sha256(), 0
    try:
        with os.fdopen(descriptor, "wb") as target, path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                count += len(chunk)
                if count > MAX_INPUT_BYTES:
                    raise DataError("WSE_INPUT_SIZE_LIMIT")
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        checksum = digest.hexdigest()
        archive = raw_dir / f"{checksum}.h5"
        try:
            os.link(temporary, archive)
        except FileExistsError:
            if archive.is_symlink() or _file_sha256(archive) != (checksum, count):
                raise DataError("WSE_ARCHIVE_CONFLICT") from None
        archive.chmod(0o400)
        return checksum, archive, count
    except OSError:
        raise DataError("WSE_INPUT_ARCHIVE_FAILED") from None
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _iter_hdf_events(path: Path, day: str):
    """Only direct numeric/fixed-ASCII compound tables; no object/pickle loading."""
    try:
        import h5py
    except ImportError:
        raise DataError("WSE_OPTIONAL_H5PY_REQUIRED") from None
    try:
        with h5py.File(path, "r") as source:
            key = "d" + day
            if not isinstance(source.get(key, getlink=True), h5py.HardLink):
                raise DataError("WSE_DAY_GROUP_REQUIRED")
            group = source[key]
            if not isinstance(group, h5py.Group) or not isinstance(group.get("table", getlink=True), h5py.HardLink):
                raise DataError("WSE_DIRECT_TABLE_REQUIRED")
            table = group["table"]
            if (not isinstance(table, h5py.Dataset) or table.ndim != 1 or table.is_virtual
                    or table.external or not table.dtype.names
                    or set(table.dtype.names) not in (set(FIELDS), set(FIELDS) | {"index"})
                    or table.dtype.itemsize > 512 or len(table) > MAX_DAY_EVENTS):
                raise DataError("WSE_HDF_TABLE_SCHEMA_OR_LIMIT")
            for name in table.dtype.names:
                dtype = table.dtype.fields[name][0]
                if dtype.subdtype is not None or dtype.fields is not None:
                    raise DataError("WSE_HDF_FIELD_SCHEMA")
                if name == "action_type":
                    valid = dtype.kind == "S" and dtype.itemsize == 1
                elif name == "order_type":
                    valid = ((dtype.kind in "iu" and dtype.itemsize <= 8)
                             or (dtype.kind == "S" and 1 <= dtype.itemsize <= 3))
                else:
                    valid = dtype.kind in "iu" and dtype.itemsize <= 8
                if not valid:
                    raise DataError("WSE_HDF_FIELD_SCHEMA")
            for start in range(0, len(table), CHUNK_ROWS):
                for row in table[start:start + CHUNK_ROWS]:
                    values = {name: row[name].item() for name in table.dtype.names}
                    for name in ("action_type", "order_type"):
                        if isinstance(values[name], bytes):
                            try:
                                values[name] = values[name].decode("ascii")
                            except UnicodeError:
                                raise DataError("WSE_HDF_FIELD_ASCII") from None
                    yield values
    except DataError:
        raise
    except (OSError, ValueError, TypeError):
        raise DataError("WSE_HDF_READ_FAILED") from None


class _Book:
    def __init__(self):
        self.orders, self.levels, self.heaps = {}, {1: {}, 2: {}}, {1: [], 2: []}
        self.healthy, self.transmitting, self.unpriced = False, False, 0
        self.reason = "NO_RESET"

    def invalidate(self, reason):
        self.healthy, self.reason = False, reason

    def _adjust(self, order, sign):
        side, price, volume, _kind = order
        if price <= 0:
            self.unpriced += sign
            return
        quantity = self.levels[side].get(price, 0) + sign * volume
        if quantity < 0:
            raise DataError("WSE_NEGATIVE_RECONSTRUCTED_DEPTH")
        if quantity:
            self.levels[side][price] = quantity
            heapq.heappush(self.heaps[side], -price if side == 1 else price)
        else:
            self.levels[side].pop(price, None)
        if len(self.heaps[side]) > 2 * len(self.levels[side]) + 1024:
            self.heaps[side] = [-level if side == 1 else level for level in self.levels[side]]
            heapq.heapify(self.heaps[side])

    def apply(self, row) -> bool:
        """Return true when the current bucket must be excluded at any boundary."""
        action = row["action_type"]
        if action == "F":
            self.__init__()
            self.healthy, self.transmitting, self.reason = True, True, "RESET_RETRANSMISSION"
            return True
        if not self.healthy:
            return True
        if action not in ("A", "Y", "M", "D"):
            self.invalidate("UNSUPPORTED_ACTION")
            return True
        key = (row["order_date"], row["order_id"])
        if any(value < 0 for value in key):
            self.invalidate("ORDER_IDENTITY_MISSING")
            return True
        previous = self.orders.get(key)
        if ((action in ("M", "D") and previous is None)
                or (action == "A" and previous is not None)):
            self.invalidate("UNKNOWN_ORDER_OR_DUPLICATE_ADD")
            return True
        if action == "D":
            self._adjust(previous, -1)
            del self.orders[key]
            self.transmitting = False
            return False
        side = previous[0] if row["side"] == -1 and previous else row["side"]
        side = 2 if side == 5 else side
        volume = previous[2] if row["volume"] == -1 and previous else row["volume"]
        kind = previous[3] if str(row["order_type"]) == "-1" and previous else str(row["order_type"])
        if row["price"] == -1 and previous:
            price = previous[1]
        elif 0 <= row["price_level"] <= 12 and row["price"] >= 0:
            price = Decimal(row["price"]).scaleb(-row["price_level"])
        else:
            self.invalidate("PRICE_FIELDS_UNSUPPORTED")
            return True
        if (side not in (1, 2) or volume < 0 or kind != "2"
                or (previous and side != previous[0])):
            self.invalidate("SIDE_VOLUME_OR_ORDER_TYPE_UNSUPPORTED")
            return True
        if previous:
            self._adjust(previous, -1)
        order = (side, price, volume, kind)
        self.orders[key] = order
        self._adjust(order, 1)
        if len(self.orders) > MAX_LIVE_ORDERS:
            raise DataError("WSE_LIVE_ORDER_LIMIT")
        self.transmitting = action == "Y"
        return self.transmitting or price <= 0

    def snapshot(self):
        if not self.healthy or self.transmitting or self.unpriced:
            return None
        values = []
        for side in (1, 2):
            heap = self.heaps[side]
            while heap and (-heap[0] if side == 1 else heap[0]) not in self.levels[side]:
                heapq.heappop(heap)
            if not heap:
                return None
            values.append(-heap[0] if side == 1 else heap[0])
        bid, ask = values
        return (bid, ask) if 0 < bid < ask else None


def _row(row, day, expected_symbol):
    if not isinstance(row, dict) or not set(FIELDS) <= set(row) <= set(FIELDS) | {"index"}:
        raise DataError("WSE_EVENT_FIELDS")
    if any(type(row[name]) is not int or not -(2 ** 63) <= row[name] < 2 ** 63
           for name in _INTEGER_FIELDS | ({"index"} if "index" in row else set())):
        raise DataError("WSE_EVENT_INTEGER_FIELDS")
    if type(row["order_type"]) not in (int, str) or not isinstance(row["action_type"], str):
        raise DataError("WSE_EVENT_TEXT_FIELDS")
    if row["symbol_idx"] != expected_symbol:
        raise DataError("WSE_EVENT_SYMBOL_MISMATCH")
    timestamp = row["time"]
    if timestamp <= 0:
        raise DataError("WSE_EVENT_TIMESTAMP_INVALID")
    local = (_EPOCH + timedelta(microseconds=timestamp // 1000)).astimezone(ZoneInfo("Europe/Warsaw"))
    if local.strftime("%Y%m%d") != day:
        raise DataError("WSE_EVENT_DAY_MISMATCH")
    return local


def _project(path: Path, spec: dict, run_dir: Path, source_sha: str) -> dict:
    csv_path, native_path = run_dir / "quotes.csv", run_dir / "native_events.jsonl"
    evidence_path = run_dir / "quote_evidence.jsonl"
    statistics = Counter()
    csv_bytes, native_bytes, segment, previous_quote = 0, 0, 0, None
    period_ns = spec["sample_period_ms"] * 1_000_000
    with (csv_path.open("w", newline="", encoding="utf-8") as output,
          native_path.open("w", encoding="utf-8") as native,
          evidence_path.open("w", encoding="utf-8") as evidence,
          localcontext() as context):
        context.prec, context.Emax, context.Emin = 1024, 999_999_999, -999_999_999
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["time_msc", "bid", "ask"])
        csv_bytes += len("time_msc,bid,ask\n")
        for day in spec["days"]:
            book, bucket, dirty, previous_ns, previous_row = _Book(), None, False, None, None
            day_count = 0
            segment += 1
            for source_row, event in enumerate(_iter_hdf_events(path, day)):
                local = _row(event, day, spec["symbol_idx"])
                ns = event["time"]
                if previous_ns is not None and ns < previous_ns:
                    raise DataError("WSE_NATIVE_CLOCK_REVERSED")
                if source_row == 0 and event["action_type"] != "F":
                    raise DataError("WSE_INITIAL_RESET_REQUIRED")
                day_count += 1
                statistics["native_event_count"] += 1
                if day_count > MAX_DAY_EVENTS or statistics["native_event_count"] > MAX_TOTAL_EVENTS:
                    raise DataError("WSE_NATIVE_EVENT_LIMIT")
                statistics["equal_ns_rows"] += previous_ns == ns
                event_bucket = ns // period_ns
                gap = previous_ns is not None and ns - previous_ns > spec["max_event_gap_ms"] * 1_000_000
                if bucket is not None and event_bucket != bucket:
                    # This event proves that the old bucket ended. It is not yet
                    # applied, so emitted book events are strictly before clock.
                    snap = book.snapshot()
                    end_ns = (bucket + 1) * period_ns
                    end_local = (_EPOCH + timedelta(microseconds=end_ns // 1000)).astimezone(ZoneInfo("Europe/Warsaw"))
                    minute = end_local.hour * 60 + end_local.minute
                    if (snap is not None and not dirty
                            and spec["session_start_minute_warsaw"] <= minute < spec["session_end_minute_warsaw"]):
                        timestamp = end_ns // 1_000_000
                        bid, ask = map(lambda value: format(value, "f"), snap)
                        line_bytes = len(f"{timestamp},{bid},{ask}\n".encode("utf-8"))
                        if statistics["quote_count"] >= MAX_ROWS or csv_bytes + line_bytes > MAX_BYTES:
                            raise DataError("WSE_PROJECTED_QUOTE_LIMIT")
                        if previous_quote is not None and timestamp <= previous_quote:
                            raise DataError("WSE_PROJECTED_CLOCK_ORDER")
                        writer.writerow([timestamp, bid, ask])
                        evidence.write(json.dumps({"time_msc": timestamp, "boundary_time_ns": end_ns,
                            "latest_event_time_ns": previous_ns, "latest_source_row": previous_row,
                            "day": day, "segment_id": segment, "bid": bid, "ask": ask,
                            "source_sha256": source_sha, "sampling_period_ms": spec["sample_period_ms"],
                            "clock_rule": "all_incorporated_events_strictly_before_boundary",
                            "fill_evidence": False}, sort_keys=True) + "\n")
                        csv_bytes += line_bytes
                        previous_quote = timestamp
                        statistics["quote_count"] += 1
                    else:
                        statistics["excluded_observed_buckets"] += 1
                    if dirty or snap is None:
                        segment += 1
                    dirty = False
                if gap:
                    # The later event cannot retroactively alter a preceding
                    # causal boundary. Its gap invalidates this new bucket.
                    book.invalidate("EVENT_CLOCK_GAP")
                    dirty = True
                    statistics["event_clock_gaps"] += 1
                bucket = event_bucket
                was_healthy = book.healthy
                dirty = book.apply(event) or dirty
                if not book.healthy and was_healthy:
                    statistics["invalidations"] += 1
                if book.snapshot() is None:
                    dirty = True
                record = {"schema_version": 1, "record_kind": "wse_native_order_event", "day": day,
                          "source_row": source_row, "time_ns": ns, "source_sha256": source_sha,
                          "native_fields": event, "book_healthy": book.healthy,
                          "bootstrap_completion_assumed": not book.transmitting,
                          "book_invalid_reason": book.reason if not book.healthy else None,
                          "expert_trade": False, "execution_label": False}
                line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
                native_bytes += len(line.encode("utf-8"))
                if native_bytes > MAX_NATIVE_BYTES:
                    raise DataError("WSE_NATIVE_EVIDENCE_SIZE_LIMIT")
                native.write(line)
                previous_ns, previous_row = ns, source_row
            if not day_count:
                raise DataError("WSE_DAY_EMPTY")
            statistics["final_incomplete_buckets_excluded"] += 1
        if not statistics["quote_count"]:
            raise DataError("WSE_NO_SUPPORTED_CAUSAL_QUOTES")
        for handle in (output, native, evidence):
            handle.flush()
            os.fsync(handle.fileno())
    for file in (csv_path, native_path, evidence_path):
        file.chmod(0o600)
    return {**statistics, "output_csv": str(csv_path), "native_events_path": str(native_path),
            "quote_evidence_path": str(evidence_path), "projected_csv_bytes": csv_bytes,
            "native_evidence_bytes": native_bytes}


def import_wse(file: Path, spec_path: Path, out: Path) -> dict:
    """Archive local input, validate every selected day, and publish one receipt."""
    out = Path(out)
    run_dir = out / "wse-runs" / uuid.uuid4().hex
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": 1, "record_kind": "wse_local_history_import", "started_at_utc": _now(),
                "status": "failed", "errors": [], "output_csv": None, "output_metadata": None,
                "native_events_path": None, "quote_evidence_path": None,
                "source_sha256": None, "raw_hdf_path": None, "raw_spec_path": None,
                "spec_sha256": None, "manifest_path": str(run_dir / "manifest.json"),
                "quality_flags": list(FLAGS), "training_ready": False, "full_history_verified": False,
                "broker_verified": False, "expert_trade_history": False, "continuous_matching_verified": False}
    manifest.update(model_trained=False, trading_enabled=False, forward_verified=False)
    try:
        spec_raw = _read_limited(Path(spec_path))
        spec_sha, raw_spec = _archive(spec_raw, raw_dir, "wse-spec.json")
        manifest.update(spec_sha256=spec_sha, raw_spec_path=str(raw_spec))
        source_sha, archived, source_bytes = _archive_file(Path(file), raw_dir)
        manifest.update(source_sha256=source_sha, raw_hdf_path=str(archived), source_bytes=source_bytes)
        spec, metadata = _specification(spec_raw)
        if source_sha != spec["expected_sha256"]:
            raise DataError("WSE_SOURCE_SHA256_MISMATCH")
        result = _project(archived, spec, run_dir, source_sha)
        metadata = dict(metadata, source_hdf_sha256=source_sha, source_spec_sha256=spec_sha,
            source_native_timestamp_basis="utc_epoch_nanoseconds", source_clock_evidence=spec["source_clock_evidence"],
            source_days=spec["days"], transformations="Visible limit-order reconstruction and completed nonempty bucket-end sampling",
            sampling_period_ms=spec["sample_period_ms"], wse_required_max_quote_gap_ms=spec["sample_period_ms"],
            sampling_rule="Incorporate only events strictly before labeled bucket-end boundary; no final incomplete bucket",
            bootstrap_completion_policy=spec["retransmission_completion_policy"],
            matching_phase_verified=False, fills_or_queue_priority_identified=False,
            source_order_not_verified_exchange_sequence=True, quality_flags=list(FLAGS),
            training_ready=False, full_history_verified=False, broker_verified=False,
            model_trained=False, trading_enabled=False, expert_trade_history=False,
            real_market_model_trained=False, forward_verified=False, broker_orders_sent=False)
        _metadata(json_bytes(metadata))
        metadata_path = run_dir / "quotes.metadata.json"
        _atomic_write(metadata_path, json_bytes(metadata))
        manifest.update(result, output_metadata=str(metadata_path),
                        data_origin=metadata["data_origin"], days=spec["days"], symbol=spec["symbol"],
                        sample_period_ms=spec["sample_period_ms"])
        for key in ("output_csv", "native_events_path", "quote_evidence_path", "output_metadata"):
            manifest[key + "_sha256"] = _sha_unbounded(Path(manifest[key]))
        manifest["status"] = "completed"
    except DataError as error:
        manifest["errors"] = [str(error)]
    except OSError:
        manifest["errors"] = ["WSE_OUTPUT_IO_FAILED"]
    except KeyboardInterrupt:
        manifest["errors"] = ["INTERRUPTED"]
    if manifest["status"] != "completed":
        # Keep any interrupted native evidence labeled partial, never expose a
        # half-written quote dataset as a successful market input.
        for name in ("quotes.csv", "native_events.jsonl", "quote_evidence.jsonl", "quotes.metadata.json"):
            candidate = run_dir / name
            if candidate.exists():
                partial = candidate.with_name("partial_" + name)
                candidate.rename(partial)
                manifest.setdefault("partial_outputs", []).append(str(partial))
        manifest.update(output_csv=None, output_metadata=None, native_events_path=None, quote_evidence_path=None)
    manifest["finished_at_utc"] = _now()
    _atomic_write(run_dir / "manifest.json", json_bytes(manifest))
    return manifest


def _sha_unbounded(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
