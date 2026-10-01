"""Auditable development-only fitting and sequential held-out evaluation.

The labels describe simulated independent-rule outcomes after assumed costs.
They do not reconstruct expert traders' trades, verify market history, establish
profitability, or authorize broker trading. All inputs remain outside Git.
"""
from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from uuid import uuid4

from trading_intelligence.common import DataError, json_bytes, load_json, now_utc, read_limited, sha256
from . import __version__
from .learning import (CaptureStrategy, FEATURE_NAMES, FEATURE_VERSION, FIT_PARAMETERS,
                       FilteredStrategy, fit, training_rows_with_audit, validate_model)
from .pipeline import _archive, _atomic, parse_config
from .strategy import RollingBreakout

THRESHOLDS = (0.0, 0.4, 0.5, 0.6, 0.7)
MIN_VALIDATION_CLOSED_TRADES = 5
_FALSE_GATES = {"training_ready": False, "full_history_verified": False,
                "trading_enabled": False, "replay_accepted": False,
                "forward_verified": False, "market_history_verified": False,
                "model_trained_on_real_market": False}


def _eligibility(report: dict) -> list[str]:
    """Engineering eligibility for threshold selection, never trade acceptance."""
    reasons = []
    if report["closed_trade_count"] < MIN_VALIDATION_CLOSED_TRADES:
        reasons.append("VALIDATION_TOO_FEW_CLOSED_TRADES")
    if report.get("open_position") is not None:
        reasons.append("VALIDATION_OPEN_POSITION")
    if "GAP_PRICE_PATH_UNKNOWN" in report.get("quality_flags", []):
        reasons.append("VALIDATION_GAP_PRICE_PATH_UNKNOWN")
    if report["risk_halted"]:
        reasons.append("VALIDATION_RISK_HALTED")
    return reasons


def _rights(metadata: dict) -> str:
    if metadata["data_origin"] == "synthetic_fixture":
        if metadata["usage_rights"] != "synthetic_only":
            raise DataError("LEARNING_SYNTHETIC_RIGHTS_CONFLICT")
        return "synthetic_only"
    if metadata["usage_rights"] != "user_asserted_permitted":
        raise DataError("LEARNING_REPLAY_USAGE_RIGHTS_NOT_ASSERTED")
    if metadata.get("training_usage_rights") != "user_asserted_permitted":
        raise DataError("LEARNING_TRAINING_USAGE_RIGHTS_NOT_ASSERTED")
    evidence = metadata.get("training_rights_evidence")
    if (not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 4096
            or any(ord(character) < 32 and character not in "\n\t" for character in evidence)):
        raise DataError("LEARNING_TRAINING_RIGHTS_EVIDENCE_REQUIRED")
    return "user_asserted_permitted_not_independently_verified"


def run_learning(csv_path: Path, metadata_path: Path, config_path: Path, out: Path) -> dict:
    """Fit once on development, select only on validation, then evaluate test.

    Fixed thresholds and eligibility criteria are recorded before any fitting.
    Every candidate gets a complete fresh validation replay with its own state.
    Test quotes never participate in fitting or candidate ranking; no refit is
    performed. Repeating this command does not make externally viewed test data
    unseen, so the audit deliberately leaves all acceptance gates false.
    """
    from .engine import replay
    from .market import load_quotes

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    (out / "raw").mkdir(exist_ok=True, mode=0o700)
    run_id = uuid4().hex
    directory = out / "learning-runs" / run_id
    directory.mkdir(parents=True, mode=0o700)
    preregistration = {
        "threshold_candidates": list(THRESHOLDS),
        "fit_parameters": dict(FIT_PARAMETERS),
        "selection_eligibility": {"minimum_validation_closed_trades": MIN_VALIDATION_CLOSED_TRADES,
                                  "open_position_allowed": False, "gap_allowed": False,
                                  "risk_halt_allowed": False},
        "selection_order": "maximum validation ending net equity; equal equity prefers higher threshold",
        "validation_objective": "ending_net_equity_currency_after_assumed_execution_costs",
        "test_policy": "selected frozen model and threshold evaluated once after selection; baseline independently evaluated once",
        "refit_policy": "never refit on validation or test",
        "adequacy": "engineering admission limits, not sufficient statistical power or profitability evidence",
    }
    manifest = {
        "schema_version": 1, "software_version": __version__, "run_id": run_id,
        "started_at_utc": now_utc(), "finished_at_utc": None, "status": "in_progress",
        "raw_files": [], "errors": [], **_FALSE_GATES,
        "model_fitted": False, "model_fitted_on_user_supplied_quotes": False,
        "simulation_only": True, "strategy_attribution": RollingBreakout.attribution,
        "label_basis": "hypothetical_independent_rule_outcomes_after_frozen_assumed_costs",
        "training_rights": "not_verified", "market_data_used": None,
        "preregistration": preregistration, "selected_threshold": None,
        "selection_status": "not_started", "evaluation_status": "not_evaluated",
        "blockers": ["NO_BROKER_EXECUTION", "EXECUTION_ASSUMPTIONS_NOT_BROKER_VALIDATED",
                     "MARKET_HISTORY_NOT_INDEPENDENTLY_VERIFIED", "TRADER_IMITATION_NOT_ESTABLISHED",
                     "EVALUATION_PERIOD_MAY_HAVE_BEEN_SEEN_EXTERNALLY", "ACCEPTANCE_NOT_AUTHORIZED"],
    }
    _atomic(directory / "manifest.json", json_bytes(manifest))
    model_path = directory / "development_model.json"
    selected_model_path = directory / "selected_model.json"
    summary_path = directory / "summary.json"
    try:
        archived = {}
        for kind, path, suffix in (("market_quotes", Path(csv_path), "csv"),
                                   ("market_metadata", Path(metadata_path), "json"),
                                   ("frozen_config", Path(config_path), "json")):
            raw = read_limited(path)
            relative = _archive(out, raw, suffix)
            archived[kind] = out / relative
            manifest["raw_files"].append({"kind": kind, "path": relative, "sha256": sha256(raw), "bytes": len(raw)})
            _atomic(directory / "manifest.json", json_bytes(manifest))
        config_raw = read_limited(archived["frozen_config"])
        document, strategy_config, engine_config, (dev_end, val_end) = parse_config(config_raw)
        dataset = load_quotes(archived["market_quotes"], archived["market_metadata"])
        metadata = dataset.metadata
        manifest["market_data_used"] = {
            "source_id": metadata["source_id"], "symbol": metadata["symbol"],
            "data_origin": metadata["data_origin"], "quote_count": len(dataset.quotes),
            "usage_rights": metadata["usage_rights"], "quality_flags": dataset.quality_flags,
            "raw_sha256": dataset.raw_sha256, "metadata_sha256": dataset.metadata_sha256,
            "max_gap_ms": max((b.time_msc-a.time_msc for a,b in zip(dataset.quotes,dataset.quotes[1:])), default=0),
        }
        if metadata["symbol"] != engine_config.symbol or metadata["price_currency"] != engine_config.price_currency:
            raise DataError("LEARNING_INSTRUMENT_OR_CURRENCY_MISMATCH")
        manifest["training_rights"] = _rights(metadata)
        if "EQUAL_TIMESTAMP_ORDER_UNVERIFIED" in dataset.quality_flags:
            raise DataError("LEARNING_EQUAL_TIMESTAMP_ORDER_UNVERIFIED")
        partitions = {
            "development": [q for q in dataset.quotes if q.time_msc < dev_end],
            "validation": [q for q in dataset.quotes if dev_end <= q.time_msc < val_end],
            "test": [q for q in dataset.quotes if q.time_msc >= val_end],
        }
        if any(len(rows) < strategy_config.lookback_quotes + 2 for rows in partitions.values()):
            raise DataError("LEARNING_PARTITION_TOO_SHORT")
        config_hash = sha256(config_raw)
        manifest.update(config_sha256=config_hash, frozen_config=document,
                        split_policy="[start,development_end); [development_end,validation_end); [validation_end,end]",
                        partition_initialization="flat position, empty signal history, independent risk budget",
                        synthetic_only=metadata["data_origin"] == "synthetic_fixture",
                        partitions={name: {"quote_count": len(rows), "first_time_msc": rows[0].time_msc,
                                           "last_time_msc": rows[-1].time_msc} for name, rows in partitions.items()})
        reports = {}

        def evaluate(rows, strategy, name):
            try:
                report = replay(rows, strategy, engine_config)
            except ValueError as error:
                if isinstance(error, DataError):
                    raise
                raise DataError("LEARNING_EXECUTION_INPUT_INVALID") from None
            report.update(partition=name, data_origin=metadata["data_origin"], quote_count=len(rows),
                          first_time_msc=rows[0].time_msc, last_time_msc=rows[-1].time_msc,
                          config_sha256=config_hash, **_FALSE_GATES)
            if isinstance(strategy, FilteredStrategy):
                report.update(model_sha256=strategy.model["model_sha256"],
                              threshold=strategy.threshold, filter_decisions=strategy.decisions)
            _atomic(directory / (name + ".json"), json_bytes(report))
            reports[name] = report
            return report

        capture = CaptureStrategy(strategy_config)
        baseline_development = evaluate(partitions["development"], capture, "baseline_development")
        audit = training_rows_with_audit(baseline_development, capture, dev_end)
        training_rows = audit["rows"]
        rows_raw = b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False) + "\n").encode("utf-8") for row in training_rows)
        _atomic(directory / "training_rows.jsonl", rows_raw)
        _atomic(directory / "training_audit.json", json_bytes(audit))
        manifest.update(training_row_count=len(training_rows), training_rows_sha256=sha256(rows_raw),
                        training_positive_count=sum(row["label"] for row in training_rows),
                        training_negative_count=sum(1-row["label"] for row in training_rows),
                        training_audit="training_audit.json", training_rows="training_rows.jsonl")
        provenance = {
            "raw_quotes_sha256": dataset.raw_sha256, "metadata_sha256": dataset.metadata_sha256,
            "config_sha256": config_hash, "training_rows_sha256": sha256(rows_raw),
            "development_end_msc": dev_end, "validation_end_msc": val_end,
            "feature_version": FEATURE_VERSION, "feature_names": list(FEATURE_NAMES),
            "strategy_attribution": RollingBreakout.attribution,
            "label_basis": manifest["label_basis"], "training_rights": manifest["training_rights"],
            "training_rights_evidence": metadata.get("training_rights_evidence"),
            "source_id": metadata["source_id"], "quote_currency": metadata["price_currency"],
            "training_partition": "development_only", "real_market_history_verified": False,
        }
        model = fit([row["features"] for row in training_rows], [row["label"] for row in training_rows],
                    origin=metadata["data_origin"], provenance=provenance)
        _atomic(model_path, json_bytes(model))
        # Validate exactly the saved representation, including its content hash.
        model = load_json(read_limited(model_path))
        validate_model(model)
        manifest.update(model_fitted=True, development_model_sha256=model["model_sha256"],
                        development_model="development_model.json",
                        model_fitted_on_user_supplied_quotes=metadata["data_origin"] == "user_supplied_unverified")
        evaluate(partitions["validation"], RollingBreakout(strategy_config), "baseline_validation")
        candidates = []
        for index, threshold in enumerate(THRESHOLDS):
            name = f"validation_candidate_{index}"
            report = evaluate(partitions["validation"], FilteredStrategy(strategy_config, model, threshold), name)
            reasons = _eligibility(report)
            candidates.append({"threshold": threshold, "report": name + ".json", "eligible": not reasons,
                               "ineligibility_reasons": reasons,
                               "closed_trade_count": report["closed_trade_count"],
                               "ending_net_equity_currency": report["ending_net_equity_currency"]})
        manifest["validation_candidates"] = candidates
        eligible = [candidate for candidate in candidates if candidate["eligible"]]
        selected_test = None
        baseline_test = None
        if eligible:
            selected = max(eligible, key=lambda candidate: (Decimal(candidate["ending_net_equity_currency"]), candidate["threshold"]))
            threshold = selected["threshold"]
            manifest.update(selection_status="selected_for_unaccepted_test_research", selected_threshold=threshold)
            selection_raw = json_bytes({"selected": selected, "candidates": candidates,
                                        "preregistration": preregistration,
                                        "model_sha256": model["model_sha256"],
                                        "config_sha256": config_hash, **_FALSE_GATES})
            _atomic(directory / "selection.json", selection_raw)
            # Binding a selected threshold changes audit metadata, never fitted
            # parameters. Keep the original model used by every validation run.
            selected_model = load_json(read_limited(model_path))
            selected_model["provenance"]["filter_selection"] = {
                "selected_threshold": str(threshold), "selection_partition": "validation",
                "rule": "maximum_validation_ending_net_equity_then_higher_threshold",
                "validation_selection_sha256": sha256(selection_raw),
                "development_model_sha256": model["model_sha256"],
                "coefficient_policy": "coefficients fitted development only; validation selects threshold and audit metadata only",
            }
            selected_model["model_sha256"] = sha256(json_bytes({key: value for key, value in selected_model.items()
                                                               if key != "model_sha256"}))
            validate_model(selected_model)
            _atomic(selected_model_path, json_bytes(selected_model))
            selected_model = load_json(read_limited(selected_model_path))
            validate_model(selected_model)
            manifest.update(model="selected_model.json", model_sha256=selected_model["model_sha256"],
                            selection_sha256=sha256(selection_raw),
                            selected_model_coefficient_policy="unchanged development coefficients; validation audit metadata only")
            # Save the frozen selection before touching test price outcomes.
            _atomic(directory / "manifest.json", json_bytes(manifest))
            selected_test = evaluate(partitions["test"], FilteredStrategy(strategy_config, selected_model, threshold), "selected_test")
            baseline_test = evaluate(partitions["test"], RollingBreakout(strategy_config), "baseline_test")
        else:
            manifest["selection_status"] = "blocked_no_eligible_validation_candidate"
            manifest["blockers"].append("NO_ELIGIBLE_VALIDATION_CANDIDATE")
            _atomic(directory / "selection.json", json_bytes({"selected": None, "candidates": candidates,
                                                               "preregistration": preregistration, **_FALSE_GATES}))
        manifest["evaluation_status"] = "synthetic_behavior_check" if manifest["synthetic_only"] else "unaccepted_market_research"
        if manifest["synthetic_only"]:
            manifest["blockers"].append("SYNTHETIC_ONLY_NOT_MARKET_EVIDENCE")
        summary = {"schema_version": 1, "market": manifest["market_data_used"], "frozen_config": document,
                   "preregistration": preregistration, "development_model": model,
                   "selected_model": selected_model if eligible else None,
                   "training_audit": {key: value for key, value in audit.items() if key != "rows"},
                   "validation_candidates": candidates, "selected_threshold": manifest["selected_threshold"],
                   "selection_status": manifest["selection_status"], "evaluation_status": manifest["evaluation_status"],
                   "reports": reports, "selected_test": selected_test, "baseline_test": baseline_test,
                   "model_fitted": True, "simulation_only": True,
                   "model_fitted_on_user_supplied_quotes": manifest["model_fitted_on_user_supplied_quotes"],
                   "blockers": manifest["blockers"], **_FALSE_GATES}
        _atomic(summary_path, json_bytes(summary))
        manifest["status"] = "completed"
    except (DataError, OSError) as error:
        manifest["status"] = "failed"
        manifest["errors"].append(str(error) if isinstance(error, DataError) else "LEARNING_LOCAL_IO_ERROR")
    except KeyboardInterrupt:
        manifest["status"] = "failed"
        manifest["errors"].append("INTERRUPTED")
    except Exception:
        manifest["status"] = "failed"
        manifest["errors"].append("LEARNING_INTERNAL_ERROR")
        raise
    finally:
        manifest["finished_at_utc"] = now_utc()
        _atomic(directory / "manifest.json", json_bytes(manifest))
    return {**manifest, "manifest": str(directory / "manifest.json"),
            "summary": str(summary_path) if manifest["status"] == "completed" else None,
            "development_model": str(model_path) if manifest["model_fitted"] else None,
            "model": str(selected_model_path) if selected_model_path.exists() else None}


def learning_status(out: Path) -> dict:
    """Return the newest attempted run, including a failed admission attempt."""
    paths = list((Path(out) / "learning-runs").glob("*/manifest.json"))
    if not paths:
        raise DataError("NO_LEARNING_RUNS_FOUND")
    manifests = [(load_json(read_limited(path)), path) for path in paths]
    latest, path = max(manifests, key=lambda item: (item[0]["started_at_utc"], item[0]["run_id"]))
    directory = path.parent
    return {**latest, "manifest": str(path),
            "summary": str(directory / "summary.json") if latest["status"] == "completed" else None,
            "development_model": str(directory / "development_model.json") if latest["model_fitted"] else None,
            "model": str(directory / "selected_model.json") if (directory / "selected_model.json").exists() else None}
