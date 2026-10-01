"""Durable local quote-file simulation, with no broker or network interface.

Every step reconstructs the complete accepted prefix through the same causal
engine. This deliberately bounded implementation favours restart correctness
over throughput. SQLite commits the cursor, controls and full report together;
an incomplete final CSV line is never accepted. Existing file history remains
historical, and later file appends alone do not establish a live forward test.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
from uuid import uuid4

from trading_intelligence.common import DataError, json_bytes, load_json, now_utc, read_limited, sha256
from . import __version__
from .engine import replay
from .market import _load_bytes, _metadata
from .pipeline import _archive, parse_config
from .strategy import RollingBreakout

_DATABASE = "paper.sqlite3"
_FALSE_FLAGS = {"training_ready": False, "full_history_verified": False,
                "model_trained": False, "trading_enabled": False,
                "broker_connected": False, "broker_demo_verified": False,
                "forward_verified": False, "simulation_only": True}


def _connect(out: Path, *, create: bool = False) -> sqlite3.Connection:
    out = Path(out)
    path = out / _DATABASE
    if not create and not path.is_file():
        raise DataError("PAPER_SESSION_NOT_FOUND")
    if path.is_symlink():
        raise DataError("PAPER_DATABASE_SYMLINK_REJECTED")
    if create:
        out.mkdir(parents=True, exist_ok=True, mode=0o700)
        (out / "raw").mkdir(exist_ok=True, mode=0o700)
    try:
        connection = sqlite3.connect(path, timeout=0, isolation_level=None)
        path.chmod(0o600)
        connection.execute("BEGIN IMMEDIATE")
        if create:
            connection.execute("""CREATE TABLE IF NOT EXISTS paper_session (
                singleton INTEGER PRIMARY KEY CHECK (singleton=1),
                state_json BLOB NOT NULL, accepted_csv BLOB NOT NULL,
                report_json BLOB NOT NULL, report_sha256 TEXT NOT NULL,
                state_sha256 TEXT NOT NULL
            )""")
        return connection
    except sqlite3.DatabaseError as error:
        if "connection" in locals():
            connection.close()
        if "locked" in str(error).lower():
            raise DataError("PAPER_SESSION_BUSY") from None
        raise DataError("PAPER_DATABASE_UNAVAILABLE") from None


def _read_state(connection: sqlite3.Connection) -> tuple[dict, bytes, dict]:
    try:
        row = connection.execute("SELECT state_json,accepted_csv,report_json,report_sha256,state_sha256 "
                                 "FROM paper_session WHERE singleton=1").fetchone()
    except sqlite3.DatabaseError:
        raise DataError("PAPER_STATE_INVALID") from None
    if row is None:
        raise DataError("PAPER_SESSION_NOT_FOUND")
    state_raw = bytes(row[0])
    state = load_json(state_raw)
    accepted, report_raw = bytes(row[1]), bytes(row[2])
    if (not isinstance(state, dict) or state.get("schema_version") != 2
            or sha256(state_raw) != row[4]
            or sha256(accepted) != state.get("accepted_prefix_sha256")
            or sha256(report_raw) != row[3]):
        raise DataError("PAPER_STATE_HASH_MISMATCH")
    try:
        # Reports can exceed the 32 MiB input bound: they contain one equity
        # point per bounded input row. Decimal results were serialized as text.
        report = json.loads(report_raw)
    except (ValueError, UnicodeError, RecursionError):
        raise DataError("PAPER_REPORT_INVALID") from None
    if not isinstance(report, dict):
        raise DataError("PAPER_REPORT_INVALID")
    count = state.get("accepted_quote_count")
    event_count = state.get("event_count")
    if (type(count) is not int or count < 0
            or type(event_count) is not int or event_count < 0
            or state.get("accepted_byte_count") != len(accepted)
            or report.get("quote_count") != count
            or not isinstance(report.get("events"), list)
            or len(report["events"]) != event_count
            or not isinstance(report.get("equity_points"), list)
            or len(report["equity_points"]) != count
            or state.get("last_quote_time_msc") != (report["equity_points"][-1].get("time_msc") if count else None)
            or report.get("config_sha256") != state.get("config_sha256")
            or report.get("metadata_sha256") != state.get("metadata_sha256")
            or report.get("accepted_prefix_sha256") != state.get("accepted_prefix_sha256")
            or report.get("model_used") != state.get("model_used")
            or report.get("model_fitted_on") != state.get("model_fitted_on")
            or report.get("model_raw_sha256") != state.get("model_sha256")
            or report.get("filter_threshold") != state.get("filter_threshold")
            or report.get("threshold_selection_verified") != state.get("threshold_selection_verified")
            or any(report.get(key) != value for key, value in _FALSE_FLAGS.items())
            or type(state.get("initial_history_quote_count")) is not int
            or not 0 <= state["initial_history_quote_count"] <= count):
        raise DataError("PAPER_STATE_REPORT_INCONSISTENT")
    return state, accepted, report


def _write_state(connection: sqlite3.Connection, state: dict, accepted: bytes, report: dict) -> None:
    raw = json_bytes(report)
    state_raw = json_bytes(state)
    connection.execute("""INSERT INTO paper_session VALUES (1,?,?,?,?,?)
        ON CONFLICT(singleton) DO UPDATE SET state_json=excluded.state_json,
        accepted_csv=excluded.accepted_csv, report_json=excluded.report_json,
        report_sha256=excluded.report_sha256,state_sha256=excluded.state_sha256""",
                       (state_raw, accepted, raw, sha256(raw), sha256(state_raw)))


def _complete_prefix(raw: bytes) -> bytes:
    end = raw.rfind(b"\n")
    if end < 0:
        raise DataError("PAPER_CSV_HEADER_NOT_COMPLETE")
    return raw[:end + 1]


def _quotes(prefix: bytes, metadata_raw: bytes) -> tuple[list, dict]:
    metadata = _metadata(metadata_raw)
    if metadata["usage_rights"] == "not_verified":
        raise DataError("PAPER_USAGE_RIGHTS_NOT_ASSERTED")
    try:
        document = _load_bytes(prefix, metadata_raw)
    except DataError as error:
        if str(error) != "MARKET_NO_QUOTES":
            raise
        # The market loader validates the header before rejecting an empty
        # quote set. A header-only file is useful for a future append producer.
        return [], metadata
    if "EQUAL_TIMESTAMP_ORDER_UNVERIFIED" in document.quality_flags:
        raise DataError("PAPER_EQUAL_TIMESTAMP_ORDER_UNVERIFIED")
    return document.quotes, metadata


def _model_context(model_raw: bytes | None, config_raw: bytes, threshold: float | None,
                   selection_raw: bytes | None = None) -> dict:
    if model_raw is None:
        if threshold is not None:
            raise DataError("PAPER_THRESHOLD_REQUIRES_MODEL")
        return {"model": None, "threshold": None, "selection_verified": False,
                "minimum_quote_time_msc": None}
    from .learning import validate_model
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise DataError("PAPER_MODEL_THRESHOLD_REQUIRED")
    model = load_json(model_raw)
    validate_model(model)
    provenance = model["provenance"]
    if provenance.get("config_sha256") != sha256(config_raw):
        raise DataError("PAPER_MODEL_CONFIG_MISMATCH")
    dev_end = provenance.get("development_end_msc")
    val_end = provenance.get("validation_end_msc")
    if (provenance.get("training_partition") != "development_only"
            or type(dev_end) is not int or type(val_end) is not int or not 0 < dev_end < val_end):
        raise DataError("PAPER_MODEL_TRAINING_CUTOFF_REQUIRED")
    evaluation = load_json(config_raw)["evaluation"]
    if (dev_end != evaluation["development_end_msc"]
            or val_end != evaluation["validation_end_msc"]):
        raise DataError("PAPER_MODEL_EVALUATION_CUTOFF_MISMATCH")
    selected = provenance.get("filter_selection")
    verified = False
    minimum_clock = dev_end
    if selected is not None:
        if (not isinstance(selected, dict) or selected.get("selection_partition") != "validation"
                or selected.get("selected_threshold") != str(float(threshold))):
            raise DataError("PAPER_MODEL_THRESHOLD_SELECTION_MISMATCH")
        development_model = {key: value for key, value in model.items() if key != "model_sha256"}
        development_model["provenance"] = {key: value for key, value in provenance.items()
                                             if key != "filter_selection"}
        if sha256(json_bytes(development_model)) != selected.get("development_model_sha256"):
            raise DataError("PAPER_MODEL_SELECTION_WEIGHT_MISMATCH")
        # Even absent receipt bytes, a declared validation-selected threshold
        # must not be applied to earlier quotes whose outcomes informed it.
        minimum_clock = val_end
        if selection_raw is not None:
            if sha256(selection_raw) != selected.get("validation_selection_sha256"):
                raise DataError("PAPER_MODEL_SELECTION_RECEIPT_MISMATCH")
            receipt = load_json(selection_raw)
            choice = receipt.get("selected") if isinstance(receipt, dict) else None
            try:
                receipt_threshold = float(choice["threshold"])
            except (TypeError, KeyError, ValueError, OverflowError):
                raise DataError("PAPER_MODEL_SELECTION_RECEIPT_MISMATCH") from None
            if (not isinstance(choice, dict) or choice.get("eligible") is not True
                    or isinstance(choice["threshold"], bool)
                    or not math.isfinite(receipt_threshold) or receipt_threshold != float(threshold)
                    or receipt.get("config_sha256") != sha256(config_raw)
                    or receipt.get("model_sha256") != selected.get("development_model_sha256")):
                raise DataError("PAPER_MODEL_SELECTION_RECEIPT_MISMATCH")
            verified = True
    elif selection_raw is not None:
        raise DataError("PAPER_MODEL_SELECTION_RECEIPT_UNBOUND")
    return {"model": model, "threshold": float(threshold), "selection_verified": verified,
            "minimum_quote_time_msc": minimum_clock}


def _run(prefix: bytes, metadata_raw: bytes, config_raw: bytes, halt_clock: int | None,
         *, model_raw: bytes | None = None, threshold: float | None = None,
         selection_raw: bytes | None = None) -> tuple[dict, dict]:
    document, strategy, config, _ = parse_config(config_raw)
    quotes, metadata = _quotes(prefix, metadata_raw)
    if metadata["symbol"] != config.symbol or metadata["price_currency"] != config.price_currency:
        raise DataError("PAPER_INSTRUMENT_OR_CURRENCY_MISMATCH")
    context = _model_context(model_raw, config_raw, threshold, selection_raw)
    runner = RollingBreakout(strategy)
    model = context["model"]
    if model is not None:
        from .learning import FilteredStrategy
        if quotes and quotes[0].time_msc < context["minimum_quote_time_msc"]:
            raise DataError("PAPER_QUOTES_PRECEDE_MODEL_FIT_OR_SELECTION")
        runner = FilteredStrategy(strategy, model, context["threshold"])
    try:
        result = replay(quotes, runner, config, finalize=False,
                        entry_halt_from_time_msc=halt_clock)
    except ValueError:
        raise DataError("PAPER_EXECUTION_INPUT_INVALID") from None
    result.update(**_FALSE_FLAGS, execution_mode="local_quote_file_simulation",
                  data_origin=metadata["data_origin"],
                  config_sha256=sha256(config_raw), metadata_sha256=sha256(metadata_raw),
                  accepted_prefix_sha256=sha256(prefix),
                  quote_source_id=metadata["source_id"],
                  strategy_attribution=RollingBreakout.attribution,
                  stop_requested=halt_clock is not None,
                  entry_halt_from_time_msc=halt_clock,
                  state_policy="recompute_full_prefix_with_one_session_risk_budget",
                  evaluation_boundaries_applied=False,
                  live_or_broker_forward_evidence=False)
    result.update(model_used=model is not None, model_fit_previously=model is not None,
                  training_performed_in_session=False,
                  model_fitted_on=model["data_origin"] if model is not None else None,
                  model_content_sha256=model["model_sha256"] if model is not None else None,
                  model_raw_sha256=sha256(model_raw) if model_raw is not None else None,
                  filter_threshold=str(context["threshold"]) if model is not None else None,
                  threshold_selection_verified=context["selection_verified"],
                  minimum_model_use_quote_time_msc=context["minimum_quote_time_msc"],
                  filter_decisions=runner.decisions if model is not None else [])
    return result, metadata


def _status(state: dict, report: dict) -> str:
    if state["entry_halt_from_time_msc"] is not None:
        if report.get("open_position") is None and report.get("pending_decision") is None:
            return "stopped_flat"
        return "stop_requested_waiting_for_quotes"
    if report.get("risk_halted"):
        return "halted_flat" if report.get("open_position") is None else "risk_halted_waiting_for_quotes"
    return "monitoring_file" if report["quote_count"] else "waiting_for_quotes"


def _view(out: Path, state: dict, report: dict, *, new_event_count: int = 0,
          newly_accepted_quotes: int = 0) -> dict:
    return {**state, **_FALSE_FLAGS, "status": _status(state, report),
            "stop_requested": state["entry_halt_from_time_msc"] is not None,
            "database": str(Path(out).resolve() / _DATABASE),
            "new_event_count": new_event_count,
            "newly_accepted_quotes": newly_accepted_quotes, "report": report}


def _bound_optional(state: dict, out: Path, kind: str) -> bytes | None:
    if state.get(kind + "_source_path") is None:
        return None
    raw = read_limited(Path(state[kind + "_source_path"]))
    if sha256(raw) != state[kind + "_sha256"]:
        raise DataError("PAPER_BOUND_INPUT_CHANGED:" + kind)
    archived = Path(out) / state[kind + "_archive_path"]
    if archived.is_symlink() or sha256(read_limited(archived)) != state[kind + "_sha256"]:
        raise DataError("PAPER_BOUND_ARCHIVE_INVALID:" + kind)
    return raw


def _bound_inputs(state: dict, out: Path) -> tuple[bytes, bytes, bytes]:
    archived_csv = Path(out) / state["observed_csv_archive_path"]
    if (archived_csv.is_symlink()
            or sha256(read_limited(archived_csv)) != state["observed_csv_sha256"]):
        raise DataError("PAPER_BOUND_ARCHIVE_INVALID:csv")
    originals = []
    for kind in ("metadata", "config"):
        raw = read_limited(Path(state[kind + "_source_path"]))
        if sha256(raw) != state[kind + "_sha256"]:
            raise DataError("PAPER_BOUND_INPUT_CHANGED:" + kind)
        archived = Path(out) / state[kind + "_archive_path"]
        if archived.is_symlink():
            raise DataError("PAPER_BOUND_ARCHIVE_INVALID:" + kind)
        archived_raw = read_limited(archived)
        if sha256(archived_raw) != state[kind + "_sha256"]:
            raise DataError("PAPER_BOUND_ARCHIVE_INVALID:" + kind)
        originals.append(archived_raw)
    raw = read_limited(Path(state["csv_source_path"]))
    return raw, originals[0], originals[1]


def start_paper(csv_path: Path, metadata_path: Path, config_path: Path, out: Path,
                *, model_path: Path | None = None, threshold: float | None = None) -> dict:
    """Bind one explicit file stream and frozen config to a durable session.

    Starting with populated history processes it as history. The runner never
    watches a file implicitly: each explicit ``step_paper`` accepts new bytes.
    A supplied model is fixed inference, not fitting. Its development cutoff
    precedes all admitted quotes. A validation-selected threshold must also
    precede admitted quotes; its saved selection receipt can be hash checked.
    """
    out = Path(out)
    connection = _connect(out, create=True)
    try:
        if connection.execute("SELECT 1 FROM paper_session WHERE singleton=1").fetchone():
            raise DataError("PAPER_SESSION_ALREADY_EXISTS")
        paths = [Path(path).resolve() for path in (csv_path, metadata_path, config_path)]
        raw, metadata_raw, config_raw = [read_limited(path) for path in paths]
        prefix = _complete_prefix(raw)
        model_source = Path(model_path).resolve() if model_path is not None else None
        model_raw = read_limited(model_source) if model_source is not None else None
        model_context = _model_context(model_raw, config_raw, threshold)
        selection_source = None
        if (model_source is not None and model_context["model"]["provenance"].get("filter_selection") is not None
                and (model_source.parent / "selection.json").is_file()):
            selection_source = model_source.parent / "selection.json"
        selection_raw = read_limited(selection_source) if selection_source is not None else None
        report, metadata = _run(prefix, metadata_raw, config_raw, None, model_raw=model_raw,
                                threshold=threshold, selection_raw=selection_raw)
        archive_paths = [_archive(out, value, suffix) for value, suffix in
                         ((raw, "csv"), (metadata_raw, "json"), (config_raw, "json"))]
        stamp = now_utc()
        state = {
            "schema_version": 2, "software_version": __version__, "session_id": uuid4().hex,
            "started_at_utc": stamp, "last_step_at_utc": stamp,
            "csv_source_path": str(paths[0]), "metadata_source_path": str(paths[1]),
            "config_source_path": str(paths[2]), "metadata_sha256": sha256(metadata_raw),
            "config_sha256": sha256(config_raw), "metadata_archive_path": archive_paths[1],
            "config_archive_path": archive_paths[2], "observed_csv_archive_path": archive_paths[0],
            "observed_csv_sha256": sha256(raw), "accepted_prefix_sha256": sha256(prefix),
            "accepted_byte_count": len(prefix), "pending_incomplete_bytes": len(raw) - len(prefix),
            "accepted_quote_count": report["quote_count"],
            "initial_history_quote_count": report["quote_count"],
            "last_quote_time_msc": report["equity_points"][-1]["time_msc"] if report["quote_count"] else None,
            "event_count": len(report["events"]), "step_count": 0,
            "entry_halt_from_time_msc": None, "stop_requested_at_utc": None,
            "processing_mode": "historical_file_reprocessing" if report["quote_count"] else "waiting_for_file_appends",
            "risk_budget_scope": "entire_session_no_batch_or_utc_day_reset",
            "complete_line_policy": "accept_only_newline_terminated_csv_prefix",
            "stop_clock_basis": "last_accepted_quote_plus_one_not_wall_clock_aligned",
            "model_source_path": str(model_source) if model_source is not None else None,
            "model_sha256": sha256(model_raw) if model_raw is not None else None,
            "model_archive_path": _archive(out, model_raw, "json") if model_raw is not None else None,
            "selection_source_path": str(selection_source) if selection_source is not None else None,
            "selection_sha256": sha256(selection_raw) if selection_raw is not None else None,
            "selection_archive_path": _archive(out, selection_raw, "json") if selection_raw is not None else None,
            "filter_threshold": str(float(threshold)) if model_raw is not None else None,
            "model_used": report["model_used"], "model_fitted_on": report["model_fitted_on"],
            "threshold_selection_verified": report["threshold_selection_verified"],
            "source_id": metadata["source_id"], "symbol": metadata["symbol"],
            "usage_rights": metadata["usage_rights"], "data_origin": metadata["data_origin"],
            "blockers": ["NO_BROKER_CONNECTION", "NO_REAL_ORDER_SUBMISSION", "NO_VERIFIED_FORWARD_FEED",
                         "EXECUTION_ASSUMPTIONS_NOT_BROKER_VALIDATED", "NO_MODEL_TRAINING"],
        }
        if metadata["data_origin"] == "synthetic_fixture":
            state["blockers"].append("SYNTHETIC_ONLY_NOT_MARKET_EVIDENCE")
        if report["model_fitted_on"] == "synthetic_fixture":
            state["blockers"].append("SYNTHETIC_MODEL_NOT_MARKET_EVIDENCE")
        if report["model_used"] and not report["threshold_selection_verified"]:
            state["blockers"].append("MANUAL_THRESHOLD_NOT_VALIDATION_VERIFIED")
        _write_state(connection, state, prefix, report)
        connection.commit()
        return _view(out, state, report, new_event_count=len(report["events"]),
                     newly_accepted_quotes=report["quote_count"])
    finally:
        connection.close()


def step_paper(out: Path) -> dict:
    """Atomically accept complete appended rows without changing prior events."""
    out = Path(out)
    connection = _connect(out)
    try:
        state, accepted, previous_report = _read_state(connection)
        raw, metadata_raw, config_raw = _bound_inputs(state, out)
        model_raw = _bound_optional(state, out, "model")
        selection_raw = _bound_optional(state, out, "selection")
        if not raw.startswith(accepted):
            raise DataError("PAPER_SOURCE_PREFIX_CHANGED_OR_TRUNCATED")
        prefix = _complete_prefix(raw)
        if len(prefix) < len(accepted):
            raise DataError("PAPER_SOURCE_PREFIX_CHANGED_OR_TRUNCATED")
        newly_accepted = 0
        new_events = 0
        report = previous_report
        if prefix != accepted:
            report, _ = _run(prefix, metadata_raw, config_raw, state["entry_halt_from_time_msc"],
                             model_raw=model_raw,
                             threshold=float(state["filter_threshold"]) if model_raw is not None else None,
                             selection_raw=selection_raw)
            old_events = previous_report["events"]
            if report["events"][:len(old_events)] != old_events:
                raise DataError("PAPER_PRIOR_EVENT_REVISION_REJECTED")
            newly_accepted = report["quote_count"] - state["accepted_quote_count"]
            new_events = len(report["events"]) - state["event_count"]
        if sha256(raw) != state["observed_csv_sha256"]:
            state["observed_csv_archive_path"] = _archive(out, raw, "csv")
        state.update(last_step_at_utc=now_utc(), step_count=state["step_count"] + 1,
                     observed_csv_sha256=sha256(raw), accepted_prefix_sha256=sha256(prefix),
                     accepted_byte_count=len(prefix), pending_incomplete_bytes=len(raw) - len(prefix),
                     accepted_quote_count=report["quote_count"], event_count=len(report["events"]),
                     last_quote_time_msc=report["equity_points"][-1]["time_msc"] if report["quote_count"] else None)
        if newly_accepted:
            state["processing_mode"] = "appended_quote_simulation"
        _write_state(connection, state, prefix, report)
        connection.commit()
        return _view(out, state, report, new_event_count=new_events,
                     newly_accepted_quotes=newly_accepted)
    finally:
        connection.close()


def stop_paper(out: Path) -> dict:
    """Persist an irreversible entry halt; no quote or fill is fabricated.

    Pending entries are cancelled and open positions request delayed simulated
    exits when the next quote arrives. The previous report remains the report
    of previously accepted quotes until a later step processes that quote.
    """
    out = Path(out)
    connection = _connect(out)
    try:
        state, accepted, report = _read_state(connection)
        if state["entry_halt_from_time_msc"] is None:
            state["entry_halt_from_time_msc"] = ((state["last_quote_time_msc"] + 1)
                                                  if state["last_quote_time_msc"] is not None else 0)
            state["stop_requested_at_utc"] = now_utc()
            _write_state(connection, state, accepted, report)
        connection.commit()
        return _view(out, state, report)
    finally:
        connection.close()


def paper_status(out: Path) -> dict:
    """Return the committed session and report without consuming any quotes."""
    connection = _connect(Path(out))
    try:
        state, _, report = _read_state(connection)
        return _view(Path(out), state, report)
    finally:
        connection.close()
