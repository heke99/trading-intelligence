"""Frozen configuration, chronological partitions and auditable replay outputs."""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from trading_intelligence.common import DataError, json_bytes, load_json, now_utc, read_limited, sha256
from . import __version__
from .strategy import RollingBreakout, StrategyConfig, bounded_integer, positive_decimal


def _atomic(path: Path, raw: bytes) -> None:
    temporary = path.parent / (uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as handle:
            os.chmod(temporary, 0o600)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _archive(out: Path, raw: bytes, suffix: str) -> str:
    digest = sha256(raw)
    path = out / "raw" / f"{digest}.{suffix}"
    temporary = out / "raw" / (uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as handle:
            os.chmod(temporary, 0o600)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or sha256(read_limited(path)) != digest:
                raise DataError("REPLAY_RAW_HASH_MISMATCH") from None
    finally:
        temporary.unlink(missing_ok=True)
    return str(path.relative_to(out))


def parse_config(raw: bytes):
    from .engine import EngineConfig

    document = load_json(raw)
    if (not isinstance(document, dict) or set(document) != {"schema_version", "basis", "strategy", "execution", "evaluation"}
            or type(document["schema_version"]) is not int or document["schema_version"] != 1
            or document["basis"] != "independent_rule_hypothesis"):
        raise DataError("REPLAY_CONFIG_SCHEMA_INVALID")
    strategy = StrategyConfig.from_dict(document["strategy"])
    execution = document["execution"]
    expected = {"symbol", "quantity", "contract_multiplier", "price_currency", "commission_per_unit_per_side",
                "slippage_price", "latency_ms", "max_quote_gap_ms", "max_entry_spread", "max_loss_currency", "max_trades"}
    if not isinstance(execution, dict) or set(execution) != expected:
        raise DataError("EXECUTION_CONFIG_FIELDS_INVALID")
    values = {key: execution[key] for key in ("symbol", "price_currency")}
    for key, value in values.items():
        if (not isinstance(value, str) or not value or len(value) > 64
                or value != value.strip() or any(character.isspace() or ord(character) < 32 for character in value)):
            raise DataError("EXECUTION_CONFIG_TEXT_INVALID:" + key)
    for key in ("quantity", "contract_multiplier", "max_entry_spread", "max_loss_currency"):
        values[key] = positive_decimal(execution[key], key)
    for key in ("commission_per_unit_per_side", "slippage_price"):
        values[key] = positive_decimal(execution[key], key, allow_zero=True)
    for key, minimum, maximum in (("latency_ms", 1, 60000), ("max_quote_gap_ms", 1, 3600000), ("max_trades", 1, 100000)):
        values[key] = bounded_integer(execution[key], key, minimum, maximum)
    engine = EngineConfig(**values)
    evaluation = document["evaluation"]
    if not isinstance(evaluation, dict) or set(evaluation) != {"development_end_msc", "validation_end_msc"}:
        raise DataError("REPLAY_SPLIT_FIELDS_INVALID")
    dev_end = bounded_integer(evaluation["development_end_msc"], "development_end_msc", 1, 253402300799999)
    val_end = bounded_integer(evaluation["validation_end_msc"], "validation_end_msc", 1, 253402300799999)
    if dev_end >= val_end:
        raise DataError("REPLAY_SPLIT_ORDER_INVALID")
    return document, strategy, engine, (dev_end, val_end)


def run_research(csv_path: Path, metadata_path: Path, config_path: Path, out: Path) -> dict:
    from .market import load_quotes, validate_quote_execution
    from .engine import replay

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    (out / "raw").mkdir(exist_ok=True, mode=0o700)
    run_id = uuid4().hex
    directory = out / "replay-runs" / run_id
    directory.mkdir(parents=True, mode=0o700)
    manifest = {
        "schema_version": 1, "software_version": __version__, "run_id": run_id,
        "started_at_utc": now_utc(), "finished_at_utc": None, "status": "in_progress",
        "raw_files": [], "errors": [], "training_ready": False, "full_history_verified": False,
        "model_trained": False, "trading_enabled": False, "replay_accepted": False,
        "training_rights": "not_verified",
        "simulation_only": True, "strategy_attribution": RollingBreakout.attribution,
        "config_selection": "one supplied frozen config; no fitting or parameter search",
        "evaluation_status": "not_evaluated", "market_data_used": None,
        "blockers": ["NO_MODEL_TRAINING", "NO_LIVE_EXECUTION", "EXECUTION_ASSUMPTIONS_NOT_BROKER_VALIDATED",
                     "ACCEPTANCE_CRITERIA_NOT_DEFINED", "EVALUATION_PERIOD_MAY_HAVE_BEEN_SEEN_EXTERNALLY"],
    }
    _atomic(directory / "manifest.json", json_bytes(manifest))
    try:
        inputs = [("market_quotes", Path(csv_path), "csv"), ("market_metadata", Path(metadata_path), "json"),
                  ("frozen_config", Path(config_path), "json")]
        archived = {}
        for kind, path, suffix in inputs:
            raw = read_limited(path)
            relative = _archive(out, raw, suffix)
            archived[kind] = out / relative
            manifest["raw_files"].append({"kind": kind, "path": relative, "sha256": sha256(raw), "bytes": len(raw)})
            _atomic(directory / "manifest.json", json_bytes(manifest))
        config_raw = read_limited(archived["frozen_config"])
        document, strategy_config, engine_config, boundaries = parse_config(config_raw)
        dataset = load_quotes(archived["market_quotes"], archived["market_metadata"])
        metadata = dataset.metadata
        manifest["market_data_used"] = {"source_id": metadata["source_id"], "symbol": metadata["symbol"],
                                        "data_origin": metadata["data_origin"], "quote_count": len(dataset.quotes),
                                        "usage_rights": metadata["usage_rights"], "quality_flags": dataset.quality_flags,
                                        "raw_sha256": dataset.raw_sha256, "metadata_sha256": dataset.metadata_sha256,
                                        "max_gap_ms": max((b.time_msc-a.time_msc for a,b in zip(dataset.quotes,dataset.quotes[1:])), default=0)}
        if metadata["symbol"] != engine_config.symbol or metadata["price_currency"] != engine_config.price_currency:
            raise DataError("REPLAY_INSTRUMENT_OR_CURRENCY_MISMATCH")
        validate_quote_execution(metadata, engine_config)
        if metadata["usage_rights"] == "not_verified":
            raise DataError("REPLAY_USAGE_RIGHTS_NOT_ASSERTED")
        if "EQUAL_TIMESTAMP_ORDER_UNVERIFIED" in dataset.quality_flags:
            raise DataError("REPLAY_EQUAL_TIMESTAMP_ORDER_UNVERIFIED")
        quotes = dataset.quotes
        dev_end, val_end = boundaries
        partitions = {
            "development": [q for q in quotes if q.time_msc < dev_end],
            "validation": [q for q in quotes if dev_end <= q.time_msc < val_end],
            "test": [q for q in quotes if q.time_msc >= val_end],
        }
        # No random shuffle, shared positions/history or quote lookahead across partitions.
        if any(len(rows) < strategy_config.lookback_quotes + 2 for rows in partitions.values()):
            raise DataError("REPLAY_PARTITION_TOO_SHORT")
        manifest.update(config_sha256=sha256(config_raw), frozen_config=document,
                        split_policy="[start,development_end); [development_end,validation_end); [validation_end,end]",
                        partition_initialization="flat position, empty signal history, independent risk budget",
                        synthetic_only=metadata["data_origin"] == "synthetic_fixture")
        reports = {}
        for name, rows in partitions.items():
            try:
                result = replay(rows, RollingBreakout(strategy_config), engine_config)
            except ValueError:
                raise DataError("REPLAY_EXECUTION_INPUT_INVALID") from None
            result.update(partition=name, data_origin=metadata["data_origin"], quote_count=len(rows),
                          first_time_msc=rows[0].time_msc, last_time_msc=rows[-1].time_msc,
                          config_sha256=manifest["config_sha256"], training_ready=False, replay_accepted=False)
            _atomic(directory / (name + ".json"), json_bytes(result))
            reports[name] = result
        manifest["partitions"] = {name: {"quote_count": len(rows), "first_time_msc": rows[0].time_msc,
                                          "last_time_msc": rows[-1].time_msc, "report": name + ".json"}
                                  for name, rows in partitions.items()}
        manifest["evaluation_status"] = "synthetic_behavior_check" if manifest["synthetic_only"] else "unaccepted_quote_research"
        if manifest["synthetic_only"]:
            manifest["blockers"].append("SYNTHETIC_ONLY_NOT_MARKET_EVIDENCE")
        for name, report in reports.items():
            if report.get("open_position") is not None:
                manifest["blockers"].append("OPEN_POSITION_AT_PARTITION_END:" + name)
            if "GAP_PRICE_PATH_UNKNOWN" in report.get("quality_flags", []):
                manifest["blockers"].append("GAP_PRICE_PATH_UNKNOWN:" + name)
        _atomic(directory / "summary.json", json_bytes({
            "schema_version": 1, "strategy": RollingBreakout.name, "config": document,
            "market": manifest["market_data_used"], "partitions": reports,
            "model_trained": False, "training_ready": False, "replay_accepted": False, "trading_enabled": False,
            "comparison_policy": "no best partition or parameter selected",
        }))
        manifest["status"] = "completed"
    except (DataError, OSError) as error:
        manifest["status"] = "failed"
        manifest["errors"].append(str(error) if isinstance(error, DataError) else "REPLAY_LOCAL_IO_ERROR")
    except KeyboardInterrupt:
        manifest["status"] = "failed"
        manifest["errors"].append("INTERRUPTED")
    except Exception:
        manifest["status"] = "failed"
        manifest["errors"].append("REPLAY_INTERNAL_ERROR")
        raise
    finally:
        manifest["finished_at_utc"] = now_utc()
        _atomic(directory / "manifest.json", json_bytes(manifest))
    return {**manifest, "manifest": str(directory / "manifest.json"), "summary": str(directory / "summary.json") if manifest["status"] == "completed" else None}


def research_status(out: Path) -> dict:
    paths = list((Path(out) / "replay-runs").glob("*/manifest.json"))
    if not paths:
        raise DataError("NO_REPLAY_RUNS_FOUND")
    manifests = [load_json(read_limited(path)) for path in paths]
    latest = max(manifests, key=lambda m: m["started_at_utc"])
    return {**latest, "manifest": str(Path(out) / "replay-runs" / latest["run_id"] / "manifest.json")}
