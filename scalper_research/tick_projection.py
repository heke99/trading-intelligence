"""Bounded local tick projection with unchanged raw clocks and row evidence.

Derived observations use completed bucket-end clocks. Selecting the last
physical source row is an explicit observation-order assumption, never a claim
of exchange sequencing, executable liquidity, receive time or expert trades.
No acquisition, fitting, authentication or broker interface is provided.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from trading_intelligence.common import DataError, json_bytes, now_utc, sha256
from .market import MAX_BYTES, MAX_ROWS, _metadata, _read_limited, load_quotes
from .pipeline import _archive, _atomic

MAX_EVIDENCE_BYTES = 256*1024*1024
_GAP_CAPS = ("wse_required_max_quote_gap_ms", "projection_required_max_quote_gap_ms")
_FLAGS = ["SOURCE_EQUAL_MILLISECOND_ORDER_UNVERIFIED", "SOURCE_ROW_ORDER_NOT_VERIFIED_EXCHANGE_SEQUENCE",
          "NATIVE_TIMESTAMP_NOT_RECEIVE_CLOCK", "DERIVED_BUCKET_END_QUOTE_NOT_NATIVE_TICK", "NO_EMPTY_BUCKET_FORWARD_FILL",
          "EVENT_TIME_TIMER_ASSUMED"]
_INHERITABLE = frozenset({"BOOTSTRAP_COMPLETION_ASSUMED", "CONTINUOUS_MATCHING_PHASE_UNVERIFIED",
                         "DELETE_OR_MODIFY_NOT_EXECUTION_LABELS", "NATIVE_MESSAGE_CLOCK_NOT_RECEIVE_CLOCK",
                         "SOURCE_ROW_ORDER_NOT_VERIFIED_EXCHANGE_SEQUENCE", "EQUAL_NS_PRIORITY_UNVERIFIED",
                         "DERIVED_SAMPLED_VISIBLE_BIDASK_NOT_EXECUTABLE_LIQUIDITY", *_FLAGS})
_FALSE_FLAGS = {"training_ready": False, "full_history_verified": False, "broker_verified": False,
                "model_trained": False, "model_fitted": False, "model_trained_on_real_market": False,
                "trading_enabled": False, "broker_connected": False, "broker_demo_verified": False,
                "market_history_verified": False, "forward_verified": False}


def _parameters(metadata: dict, sample_period_ms: int, max_native_gap_ms: int) -> dict:
    if type(sample_period_ms) is not int or not 1 <= sample_period_ms <= 1000:
        raise DataError("TICK_PROJECTION_PERIOD_RANGE")
    if type(max_native_gap_ms) is not int or not 1 <= max_native_gap_ms <= 3600000:
        raise DataError("TICK_PROJECTION_NATIVE_GAP_RANGE")
    caps = {}
    for key in _GAP_CAPS:
        if key not in metadata:
            continue
        value = metadata[key]
        if type(value) is not int or not 1 <= value <= 60000:
            raise DataError("TICK_PROJECTION_SOURCE_GAP_POLICY_INVALID")
        caps[key] = value
    if caps and max_native_gap_ms > min(caps.values()):
        raise DataError("TICK_PROJECTION_NATIVE_GAP_WOULD_BROADEN_SOURCE_POLICY")
    previous_projection = metadata.get("tick_projection")
    if previous_projection is not None:
        if (not isinstance(previous_projection, dict)
                or type(previous_projection.get("schema_version")) is not int
                or previous_projection["schema_version"] != 1
                or type(previous_projection.get("sample_period_ms")) is not int
                or not 1 <= previous_projection["sample_period_ms"] <= 1000
                or previous_projection.get("native_input_timestamp_basis") != "utc_epoch_milliseconds"):
            raise DataError("TICK_PROJECTION_PARENT_SCHEMA_INVALID")
    return caps


def _source_flags(metadata: dict, dataset_flags: list[str]) -> list[str]:
    combined = list(dataset_flags)
    for key, maximum in (("quality_flags", 32), ("source_tick_quality_flags", 96)):
        flags = metadata.get(key, [])
        if (not isinstance(flags, list) or len(flags) > maximum
                or any(not isinstance(flag, str) or not flag or len(flag) > 128
                       or any(ord(character) < 32 for character in flag) for flag in flags)):
            raise DataError("TICK_PROJECTION_SOURCE_FLAGS_INVALID")
        combined.extend(flags)
    result = list(dict.fromkeys(combined))
    if len(result) > 96:
        raise DataError("TICK_PROJECTION_SOURCE_FLAGS_INVALID")
    return result


def _line(document: dict) -> bytes:
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False)+"\n").encode("utf-8")


def project_ticks(csv_path: Path, metadata_path: Path, out: Path, *,
                  sample_period_ms: int, max_native_gap_ms: int) -> dict:
    """Project accepted source rows onto strictly causal completed buckets.

    A later native clock proves the earlier bucket complete but contributes no
    price to that bucket. Empty buckets are never manufactured. A native gap
    invalidates the entire bucket containing the later row, and starts a new
    segment; it cannot retroactively invalidate an earlier completed bucket.
    The last observed bucket remains incomplete and is always excluded.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    (out/"raw").mkdir(exist_ok=True, mode=0o700)
    run_id = uuid4().hex
    directory = out/"tick-projection-runs"/run_id
    directory.mkdir(parents=True, mode=0o700)
    manifest_path = directory/"manifest.json"
    manifest = {"schema_version": 1, "adapter_version": 1, "run_id": run_id,
                "record_kind": "local_causal_tick_projection", "status": "in_progress",
                "started_at_utc": now_utc(), "finished_at_utc": None,
                "manifest_path": str(manifest_path), "raw_files": [], "errors": [],
                "input_quote_count": 0, "raw_rows_written": 0, "quote_count": 0,
                "duplicate_native_timestamp_rows": 0, "observed_bucket_count": 0,
                "empty_bucket_count_not_filled": 0, "dirty_bucket_count": 0,
                "native_gap_count": 0, "incomplete_final_bucket_count": 0,
                "output_csv": None, "output_metadata": None, "raw_rows_path": None,
                "bucket_evidence_path": None, "source_csv_sha256": None, "source_metadata_sha256": None,
                "source_quality_flags": [], "quality_flags": [], "network_used": False,
                "training_performed": False, "simulation_only": True,
                "timer_assumption": "virtual event-time bucket timer; measured receive or feed availability is not verified",
                "maximum_witness_delay_ms": None, **_FALSE_FLAGS}
    _atomic(manifest_path, json_bytes(manifest))
    names = {"output_csv": "quotes.csv", "raw_rows_path": "raw_rows.jsonl",
             "bucket_evidence_path": "bucket_evidence.jsonl", "output_metadata": "metadata.json"}
    partial = {kind: directory/("partial_"+name) for kind, name in names.items()}
    try:
        archived = {}
        for kind, path, suffix in (("native_csv", Path(csv_path), "csv"),
                                   ("native_metadata", Path(metadata_path), "metadata.json")):
            raw = _read_limited(path)
            relative = _archive(out, raw, suffix)
            archived[kind] = out/relative
            archived[kind].chmod(0o400)
            manifest["raw_files"].append({"kind": kind, "path": str(out/relative), "sha256": sha256(raw), "bytes": len(raw)})
            _atomic(manifest_path, json_bytes(manifest))
        dataset = load_quotes(archived["native_csv"], archived["native_metadata"])
        if (dataset.raw_sha256 != manifest["raw_files"][0]["sha256"]
                or dataset.metadata_sha256 != manifest["raw_files"][1]["sha256"]):
            raise DataError("TICK_PROJECTION_RAW_HASH_MISMATCH")
        metadata = dataset.metadata
        caps = _parameters(metadata, sample_period_ms, max_native_gap_ms)
        source_flags = _source_flags(metadata, dataset.quality_flags)
        flags = list(dict.fromkeys([*(_FLAGS if "EQUAL_TIMESTAMP_ORDER_UNVERIFIED" in source_flags else _FLAGS[1:]),
                                   *(flag for flag in source_flags if flag in _INHERITABLE)]))
        required_cap = min([sample_period_ms, *caps.values()])
        manifest.update(input_quote_count=len(dataset.quotes), source_csv_sha256=dataset.raw_sha256,
                        source_metadata_sha256=dataset.metadata_sha256, source_quality_flags=source_flags,
                        quality_flags=flags, symbol=metadata["symbol"], price_currency=metadata["price_currency"],
                        source_id=metadata["source_id"], data_origin=metadata["data_origin"], usage_rights=metadata["usage_rights"],
                        sample_period_ms=sample_period_ms, max_native_gap_ms=max_native_gap_ms,
                        inherited_quote_gap_caps=caps, projection_required_max_quote_gap_ms=required_cap,
                        raw_csv_path=str(archived["native_csv"]), raw_metadata_path=str(archived["native_metadata"]),
                        native_input_timestamp_basis="utc_epoch_milliseconds",
                        derived_clock_semantics="completed_bucket_end_observation_not_native_tick_time",
                        equal_clock_policy="last physical source row within complete bucket; as-file observation-order assumption only")
        byte_counts = {kind: 0 for kind in ("output_csv", "raw_rows_path", "bucket_evidence_path")}
        digests = {kind: hashlib.sha256() for kind in byte_counts}
        previous = None
        bucket = None
        segment = 1
        first_output = last_output = None
        with (partial["output_csv"].open("xb") as csv_output,
              partial["raw_rows_path"].open("xb") as raw_output,
              partial["bucket_evidence_path"].open("xb") as bucket_output):
            handles = {"output_csv": csv_output, "raw_rows_path": raw_output, "bucket_evidence_path": bucket_output}
            for kind in handles:
                partial[kind].chmod(0o600)

            def write(kind, raw):
                limit = MAX_BYTES if kind == "output_csv" else MAX_EVIDENCE_BYTES
                if byte_counts[kind]+len(raw) > limit:
                    raise DataError("TICK_PROJECTION_OUTPUT_SIZE_LIMIT:"+kind)
                handles[kind].write(raw)
                digests[kind].update(raw)
                byte_counts[kind] += len(raw)

            write("output_csv", b"time_msc,bid,ask\n")

            def finish(group, witness=None):
                nonlocal first_output, last_output
                completed = witness is not None
                boundary = (group["index"]+1)*sample_period_ms
                witness_delay = witness.time_msc-boundary if completed else None
                if witness_delay is not None:
                    if witness_delay < 0:
                        raise DataError("TICK_PROJECTION_CAUSAL_BOUNDARY_INVALID")
                    prior_delay = manifest["maximum_witness_delay_ms"]
                    manifest["maximum_witness_delay_ms"] = witness_delay if prior_delay is None else max(prior_delay, witness_delay)
                reasons = list(group["reasons"])
                if not completed:
                    reasons.append("FINAL_INCOMPLETE_BUCKET")
                    manifest["incomplete_final_bucket_count"] += 1
                emit = completed and not group["dirty"]
                if group["dirty"]:
                    manifest["dirty_bucket_count"] += 1
                last = group["last"]
                if emit:
                    if (not last.time_msc < boundary <= witness.time_msc
                            or last_output is not None and boundary <= last_output):
                        raise DataError("TICK_PROJECTION_CAUSAL_BOUNDARY_INVALID")
                    if manifest["quote_count"] >= MAX_ROWS:
                        raise DataError("TICK_PROJECTION_OUTPUT_ROW_LIMIT")
                    write("output_csv", f"{boundary},{last.bid},{last.ask}\n".encode("ascii"))
                    manifest["quote_count"] += 1
                    first_output = boundary if first_output is None else first_output
                    last_output = boundary
                write("bucket_evidence_path", _line({
                    "schema_version": 1, "record_kind": "causal_tick_bucket_evidence",
                    "source_csv_sha256": dataset.raw_sha256, "segment_id": group["segment"],
                    "bucket_start_msc": group["index"]*sample_period_ms, "bucket_end_msc": boundary,
                    "source_row_first": group["first"].source_row, "source_row_last": last.source_row,
                    "source_record_index_first": group["first_index"], "source_record_index_last": group["last_index"],
                    "native_time_first_msc": group["first"].time_msc, "native_time_last_msc": last.time_msc,
                    "native_row_count": group["count"], "completed": completed, "emitted": emit,
                    "excluded_reasons": reasons, "selected_source_row": last.source_row if emit else None,
                    "selected_bid": str(last.bid) if emit else None, "selected_ask": str(last.ask) if emit else None,
                    "completion_witness_time_msc": witness.time_msc if witness is not None else None,
                    "completion_witness_source_row": witness.source_row if witness is not None else None,
                    "witness_delay_ms": witness_delay, "event_time_timer_assumed": True,
                    "witness_prices_incorporated": False, "exchange_sequence_verified": False,
                    "fill_evidence": False}))
                manifest["observed_bucket_count"] += 1

            for record_index, quote in enumerate(dataset.quotes, 1):
                index = quote.time_msc//sample_period_ms
                native_gap = quote.time_msc-previous.time_msc if previous is not None else None
                gap = native_gap is not None and native_gap > max_native_gap_ms
                equal_clock = native_gap == 0
                # Completion is established before the later row or its gap is
                # applied. Neither can change the prior bucket's price/state.
                if bucket is not None and index != bucket["index"]:
                    finish(bucket, quote)
                    manifest["empty_bucket_count_not_filled"] += index-bucket["index"]-1
                    bucket = None
                if gap:
                    segment += 1
                    manifest["native_gap_count"] += 1
                if bucket is None:
                    bucket = {"index": index, "first": quote, "last": quote, "first_index": record_index,
                              "last_index": record_index, "count": 0, "dirty": False, "reasons": [], "segment": segment}
                if gap:
                    bucket["dirty"] = True
                    bucket["segment"] = segment
                    if "NATIVE_CLOCK_GAP" not in bucket["reasons"]:
                        bucket["reasons"].append("NATIVE_CLOCK_GAP")
                write("raw_rows_path", _line({
                    "schema_version": 1, "record_kind": "native_csv_tick_projection_evidence",
                    "source_csv_sha256": dataset.raw_sha256, "source_metadata_sha256": dataset.metadata_sha256,
                    "source_record_index": record_index, "source_row": quote.source_row,
                    "native_time_msc": quote.time_msc, "bid": str(quote.bid), "ask": str(quote.ask),
                    "bucket_start_msc": index*sample_period_ms, "bucket_end_msc": (index+1)*sample_period_ms,
                    "segment_id": segment, "equal_clock_with_previous": equal_clock,
                    "native_gap_from_previous_ms": native_gap, "native_gap_exceeds_policy": gap,
                    "source_row_is_exchange_sequence": False, "execution_label": False}))
                manifest["raw_rows_written"] += 1
                manifest["duplicate_native_timestamp_rows"] += equal_clock
                bucket["last"], bucket["last_index"] = quote, record_index
                bucket["count"] += 1
                previous = quote
            if bucket is not None:
                finish(bucket)
            for output in handles.values():
                output.flush()
                os.fsync(output.fileno())
        if not manifest["quote_count"]:
            raise DataError("TICK_PROJECTION_NO_COMPLETE_CLEAN_BUCKETS")
        output_metadata = {
            **metadata, **_FALSE_FLAGS, "simulation_only": True,
            "event_time_timer_assumed": True, "timer_assumption": manifest["timer_assumption"],
            "projection_required_max_quote_gap_ms": required_cap, "quality_flags": flags,
            "source_tick_quality_flags": source_flags,
            "tick_projection": {
                "schema_version": 1, "sample_period_ms": sample_period_ms, "max_native_gap_ms": max_native_gap_ms,
                "inherited_quote_gap_caps": caps, "required_max_quote_gap_ms": required_cap,
                "native_input_timestamp_basis": "utc_epoch_milliseconds",
                "output_clock_semantics": manifest["derived_clock_semantics"],
                "source_csv_sha256": dataset.raw_sha256, "source_metadata_sha256": dataset.metadata_sha256,
                "source_row_identity": "physical CSV row in immutable archived input; not exchange sequence",
                "equal_clock_policy": manifest["equal_clock_policy"],
                "completion_rule": "later native clock reaches bucket end; incorporated native clocks strictly before boundary",
                "missing_bucket_policy": "no forward filling or artificial rows",
                "native_gap_policy": "drop entire later-row bucket and advance segment; do not taint prior completed bucket",
                "final_bucket_policy": "exclude unobserved completion at EOF",
                "raw_rows_sha256": digests["raw_rows_path"].hexdigest(),
                "bucket_evidence_sha256": digests["bucket_evidence_path"].hexdigest(),
                "input_quote_count": len(dataset.quotes), "output_quote_count": manifest["quote_count"],
                "maximum_witness_delay_ms": manifest["maximum_witness_delay_ms"],
                "timer_assumption": manifest["timer_assumption"],
                "exchange_sequence_verified": False, "receive_clock_verified": False, "fills_verified": False}}
        _metadata(json_bytes(output_metadata))
        _atomic(partial["output_metadata"], json_bytes(output_metadata))
        for kind, name in names.items():
            target = directory/name
            partial[kind].replace(target)
            manifest[kind] = str(target)
            manifest[kind+"_sha256"] = (digests[kind].hexdigest() if kind in digests else sha256(json_bytes(output_metadata)))
        manifest.update(status="completed", output_bytes=byte_counts,
                        first_time_msc=first_output, last_time_msc=last_output,
                        final_native_time_msc=dataset.quotes[-1].time_msc)
    except (DataError, OSError) as error:
        manifest["status"] = "failed"
        manifest["errors"].append(str(error) if isinstance(error, DataError) else "TICK_PROJECTION_LOCAL_IO_ERROR")
    except KeyboardInterrupt:
        manifest["status"] = "failed"
        manifest["errors"].append("INTERRUPTED")
    except Exception:
        manifest["status"] = "failed"
        manifest["errors"].append("TICK_PROJECTION_INTERNAL_ERROR")
        raise
    finally:
        if manifest["status"] != "completed":
            for kind, name in names.items():
                completed = directory/name
                if completed.exists():
                    completed.replace(partial[kind])
                manifest[kind] = None
            manifest["partial_outputs"] = [str(path) for path in partial.values() if path.exists()]
        manifest["finished_at_utc"] = now_utc()
        _atomic(manifest_path, json_bytes(manifest))
    return manifest
