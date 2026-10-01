"""Fixed native-data research plan and a completely fictional engineering run.

Writing a plan never acquires data. The demonstration never reads real source
data, authenticates, invokes acquisition or connects to an exchange or broker.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from trading_intelligence.common import DataError, json_bytes, now_utc, read_limited, sha256
from .pipeline import _archive, _atomic, parse_config

_DAYS = ["20170102", "20170103", "20170104"]
_FALSE_FLAGS = {"training_ready": False, "full_history_verified": False,
                "trading_enabled": False, "broker_connected": False,
                "broker_demo_verified": False, "forward_verified": False,
                "market_history_verified": False, "model_trained_on_real_market": False,
                "expert_trade_history": False, "expert_trader_imitation_verified": False}


def _milliseconds(day: str, hour: int = 0) -> int:
    date = datetime.strptime(day, "%Y%m%d").replace(hour=hour, tzinfo=timezone.utc)
    return int(date.timestamp())*1000


def _research_config(*, synthetic: bool) -> dict:
    strategy = {"lookback_quotes": 3 if synthetic else 5,
                "breakout_buffer": "0.005" if synthetic else "0.01",
                "stop_distance": "0.04" if synthetic else "0.10",
                "target_distance": "0.06" if synthetic else "0.20",
                "max_hold_ms": 5000 if synthetic else 60000,
                "session_start_minute_utc": 540, "session_end_minute_utc": 550 if synthetic else 895,
                "cooldown_ms": 1000 if synthetic else 5000}
    execution = {"symbol": "PEKAO", "quantity": "1", "contract_multiplier": "1", "price_currency": "PLN",
                 "commission_per_unit_per_side": "0.001" if synthetic else "0.02",
                 "slippage_price": "0.001" if synthetic else "0.01", "latency_ms": 100,
                 "max_quote_gap_ms": 1000, "max_entry_spread": "0.04" if synthetic else "0.10",
                 "max_loss_currency": "1000" if synthetic else "100", "max_trades": 1000}
    return {"schema_version": 1, "basis": "independent_rule_hypothesis", "strategy": strategy,
            "execution": execution,
            "evaluation": {"development_end_msc": _milliseconds(_DAYS[1]),
                           "validation_end_msc": _milliseconds(_DAYS[2])}}


def _spec(source: dict, expected_sha256: str, *, synthetic: bool) -> dict:
    return {"schema_version": 1, "format": "wselob_orders_v1", "expected_sha256": expected_sha256,
            "symbol": "PEKAO", "symbol_idx": 11322, "days": list(_DAYS), "sample_period_ms": 1000,
            "max_event_gap_ms": 60000, "session_start_minute_warsaw": 600,
            "session_end_minute_warsaw": 611 if synthetic else 960,
            "source_clock_evidence": (
                "Fictional generator explicitly writes UTC epoch nanoseconds; sampled quotes use UTC epoch milliseconds."
                if synthetic else
                "WSELOB depositor field semantics interpreted as UTC epoch nanoseconds; selected January 2017 days are checked in Europe/Warsaw. Native time is not a broker receive clock."),
            "retransmission_completion_policy": "first_non_retransmission_event_assumption", "source": source}


def _write_fixed(path: Path, raw: bytes) -> None:
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            raise DataError("WSE_PLAN_EXISTING_FILE_CONFLICT")
        return
    _atomic(path, raw)


def write_wse_plan(out: Path) -> dict:
    """Write the fixed source contract and predeclared January PEKAO hypothesis.

    CC BY attribution and separate replay/training permission assertions refer
    to the public depositor license; they do not certify execution semantics,
    history completeness, matching phase, trader identity or broker costs.
    """
    from .acquire import _WSE_CONTRACT, WSE_SOURCE_CONTRACT_SHA256
    from .wse import _specification

    out = Path(out)
    directory = out/"wse-plan"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    contract = asdict(_WSE_CONTRACT)
    rights = ("Public depositor record " + contract["source_record_url"] + " labels WSELOB-2017 V1 CC BY 4.0; "
              + contract["license_url"] + "; attribution preserved and derived reconstruction is explicitly identified.")
    source = {"schema_version": 1, "source_id": contract["source_id"], "symbol": "PEKAO", "price_currency": "PLN",
              "timestamp_basis": "utc_epoch_milliseconds",
              "timezone_evidence": "Derived complete bucket-end boundaries in UTC, with native day identity checked in Europe/Warsaw.",
              "data_origin": "user_supplied_unverified", "usage_rights": "user_asserted_permitted",
              "rights_evidence": rights, "training_usage_rights": "user_asserted_permitted",
              "training_rights_evidence": rights, "license": contract["license"], "license_url": contract["license_url"],
              "attribution": contract["attribution"],
              "transformation_notice": "Derived visible-limit-order reconstruction and causal bucket-end sampling; no execution or expert-trader labels.",
              "source_record_url": contract["source_record_url"], "broker_verified": False,
              "training_ready": False, "full_history_verified": False}
    spec = _spec(source, contract["expected_sha256"], synthetic=False)
    config = _research_config(synthetic=False)
    _specification(json_bytes(spec))
    parse_config(json_bytes(config))
    files = {"source_contract": (directory/"source.contract.json", json_bytes(contract)),
             "spec": (directory/"import.spec.json", json_bytes(spec)),
             "config": (directory/"research.config.json", json_bytes(config))}
    for path, raw in files.values():
        _write_fixed(path, raw)
    result = {"schema_version": 1, "status": "completed", "record_kind": "predeclared_native_research_plan",
              "network_used": False, "actual_source_acquired": False, "model_fitted": False,
              "source_contract_sha256": WSE_SOURCE_CONTRACT_SHA256,
              "expected_source_sha256": contract["expected_sha256"], "expected_source_bytes": contract["expected_bytes"],
              "symbol": "PEKAO", "price_currency": "PLN", "quantity": "1", "contract_multiplier": "1",
              "plan_before_any_successful_data_import": "intended_future_run_order_not_globally_verified",
              "frozen_current_plan_for_future_run": True,
              "external_data_visibility": "unknown",
              "temporal_scope": "Current fixed plan is written for a future local run; prior acquisition attempts or external viewing are not audited by this command.",
              "config_basis": "independent_rule_hypothesis; fee/slippage/latency assumptions are not broker validated",
              "source_semantics": "native order events and derived visible bid/ask; no claimed expert executions or executable depth",
              "selected_days": list(_DAYS), "required_execution_max_quote_gap_ms": 1000,
              "rights_assertion_basis": rights, "attribution": contract["attribution"],
              "paths": {kind: str(path) for kind, (path, _) in files.items()},
              "file_sha256": {kind: sha256(raw) for kind, (_, raw) in files.items()},
              "blockers": ["NATIVE_HISTORY_NOT_ACQUIRED", "RECONSTRUCTION_ASSUMPTIONS_UNVERIFIED",
                           "EXECUTION_COSTS_NOT_BROKER_VALIDATED", "NO_EXPERT_TRADE_IMPLICATION", "NO_BROKER_FORWARD_EVIDENCE",
                           "PREVIOUS_ACQUISITION_AND_EXTERNAL_VISIBILITY_UNKNOWN"],
              **_FALSE_FLAGS}
    result.update(spec_path=result["paths"]["spec"], config_path=result["paths"]["config"],
                  source_contract_path=result["paths"]["source_contract"], manifest=str(directory/"manifest.json"))
    _atomic(directory/"manifest.json", json_bytes(result))
    return result


def run_wse_benchmark(file: Path, spec_path: Path, config_path: Path, out: Path) -> dict:
    """Run a supplied local HDF through immutable import, fit and frozen stress.

    This command does not acquire data. The supplied source declaration and
    permissions remain explicit assertions; a matching checksum does not verify
    broker fills, market completeness, expert-trader strategy or unseen data.
    """
    from .evaluation import run_cost_stress
    from .learning_pipeline import run_learning
    from .wse import import_wse

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    (out/"raw").mkdir(exist_ok=True, mode=0o700)
    run_id = uuid4().hex
    directory = out/"wse-benchmark-runs"/run_id
    directory.mkdir(parents=True, mode=0o700)
    manifest_path, summary_path = directory/"manifest.json", directory/"summary.json"
    result = {"schema_version": 1, "run_id": run_id, "status": "in_progress",
              "started_at_utc": now_utc(), "finished_at_utc": None,
              "network_used": False, "acquisition_performed": False,
              "record_kind": "local_native_history_benchmark", "simulation_only": True,
              "model_fitted": False, "source_history_imported": False, "source_hash_verified_against_supplied_spec": False,
              "source_data_origin": None, "synthetic_only": None,
              "raw_files": [], "source_refs": {}, "stages": {}, "errors": [],
              "parameter_selection_scope": "development fit and validation threshold selection; frozen test and cost stress with no refit",
              "external_data_visibility": "unknown",
              "blockers": ["NATIVE_RECONSTRUCTION_ASSUMPTIONS_UNVERIFIED", "NO_EXPERT_TRADER_HISTORY",
                           "EXECUTION_COSTS_NOT_BROKER_VALIDATED", "NO_BROKER_FORWARD_EVIDENCE",
                           "SOURCE_PERMISSION_ASSERTIONS_NOT_INDEPENDENTLY_VERIFIED", "HOLDOUT_MAY_HAVE_BEEN_VIEWED_EXTERNALLY"],
              "manifest": str(manifest_path), "summary": str(summary_path), **_FALSE_FLAGS}
    _atomic(manifest_path, json_bytes(result))
    try:
        archived = {}
        # Snapshot both declared contracts before the native importer can read
        # anything. Downstream stages always use these immutable byte copies.
        for kind, source in (("native_spec", Path(spec_path)), ("frozen_config", Path(config_path))):
            raw = read_limited(source)
            relative = _archive(out, raw, "json")
            archived[kind] = out/relative
            result["raw_files"].append({"kind": kind, "path": str(out/relative), "sha256": sha256(raw), "bytes": len(raw)})
            _atomic(manifest_path, json_bytes(result))
        config_raw = read_limited(archived["frozen_config"])
        config, _, _, _ = parse_config(config_raw)
        original = Path(file)
        if str(original).lower().startswith(("http:", "https:", "ftp:", "s3:", "file:")):
            raise DataError("WSE_BENCHMARK_LOCAL_FILE_REQUIRED")
        if not original.is_file():
            raise DataError("WSE_BENCHMARK_LOCAL_ORIGINAL_FILE_UNAVAILABLE")
        original = original.resolve()
        result["source_refs"].update(original_file=str(original), original_spec_path=str(Path(spec_path).resolve()),
                                     original_config_path=str(Path(config_path).resolve()),
                                     frozen_spec_path=str(archived["native_spec"]),
                                     frozen_config_path=str(archived["frozen_config"]),
                                     config_sha256=sha256(config_raw))
        result.update(symbol=config["execution"]["symbol"], price_currency=config["execution"]["price_currency"])
        imported = import_wse(original, archived["native_spec"], out/"native-import")
        result["stages"]["native_import"] = imported
        _atomic(manifest_path, json_bytes(result))
        if imported["status"] != "completed":
            raise DataError("WSE_BENCHMARK_IMPORT_FAILED")
        result.update(source_history_imported=True, source_hash_verified_against_supplied_spec=True,
                      source_data_origin=imported["data_origin"], synthetic_only=imported["data_origin"] == "synthetic_fixture")
        result["source_refs"].update(source_hdf_sha256=imported["source_sha256"], raw_hdf_path=imported["raw_hdf_path"],
                                     native_events_path=imported["native_events_path"], quote_evidence_path=imported["quote_evidence_path"],
                                     derived_quotes_path=imported["output_csv"], derived_metadata_path=imported["output_metadata"])
        learned = run_learning(Path(imported["output_csv"]), Path(imported["output_metadata"]),
                               archived["frozen_config"], out/"learning")
        result["stages"]["learning"] = learned
        result["model_fitted"] = learned.get("model_fitted") is True
        _atomic(manifest_path, json_bytes(result))
        if learned["status"] != "completed" or learned.get("selected_threshold") is None or not learned.get("model"):
            raise DataError("WSE_BENCHMARK_FROZEN_SELECTION_UNAVAILABLE")
        result["source_refs"].update(selected_model_path=learned["model"], development_model_path=learned["development_model"],
                                     learning_summary_path=learned["summary"])
        stressed = run_cost_stress(Path(imported["output_csv"]), Path(imported["output_metadata"]),
                                   archived["frozen_config"], Path(learned["model"]),
                                   learned["selected_threshold"], out/"stress")
        result["stages"]["cost_stress"] = stressed
        if stressed["status"] != "completed":
            raise DataError("WSE_BENCHMARK_COST_STRESS_FAILED")
        result["source_refs"]["cost_stress_summary_path"] = stressed["summary"]
        result.update(status="completed", evaluation_status="synthetic_behavior_check" if result["synthetic_only"] else "unaccepted_market_research")
        if result["synthetic_only"]:
            result["blockers"].append("SYNTHETIC_ONLY_NOT_MARKET_HISTORY")
    except (DataError, OSError) as error:
        result["status"] = "failed"
        result["errors"].append(str(error) if isinstance(error, DataError) else "WSE_BENCHMARK_LOCAL_IO_ERROR")
    except KeyboardInterrupt:
        result["status"] = "failed"
        result["errors"].append("INTERRUPTED")
    except Exception:
        result["status"] = "failed"
        result["errors"].append("WSE_BENCHMARK_INTERNAL_ERROR")
        raise
    finally:
        result["finished_at_utc"] = now_utc()
        _atomic(summary_path, json_bytes(result))
        _atomic(manifest_path, json_bytes(result))
    return result


def _fictional_hdf(directory: Path) -> tuple[Path, Path, Path]:
    try:
        import h5py
        import numpy as np
    except ImportError:
        raise DataError("NATIVE_DEMO_OPTIONAL_H5PY_REQUIRED") from None
    from .wse import FIELDS

    directory.mkdir(parents=True, mode=0o700)
    hdf = directory/"orders.synthetic.h5"
    dtype = np.dtype([(name, "S1" if name == "action_type" else "<i8") for name in FIELDS])
    with h5py.File(hdf, "w") as output:
        for day_index, day in enumerate(_DAYS):
            base_ns = _milliseconds(day, 9)*1_000_000
            events = []

            def event(clock, action, order_id=0, *, price=-1, side=-1, volume=-1, order_type=-1):
                return {"time": clock, "priority_date": base_ns, "order_date": base_ns,
                        "symbol_idx": 11322, "price": price, "agg_volume": 10, "volume": volume,
                        "order_id": order_id, "num_orders": 1, "side": side, "order_type": order_type,
                        "action_type": action, "price_level": 2}

            events.append(event(base_ns-900, "F"))
            events.append(event(base_ns-800, "Y", 1, price=10999, side=1, volume=10, order_type=2))
            events.append(event(base_ns-700, "Y", 2, price=11001, side=2, volume=10, order_type=2))
            seed, offset, previous_mid = 97+day_index*61, 0, 11000
            for tick in range(603):
                seed = (1664525*seed+1013904223) % (2**32)
                if tick < 600:
                    regime = (tick//60) % 4
                    offset += int(seed % 11)-5+(2 if regime == 0 else -2 if regime == 1 else 0)
                mid = 11000+offset
                # Safe message order avoids an intermediate crossed book when
                # a price jump exceeds the spread. Both clocks remain strictly
                # inside the same observation bucket, after its start boundary.
                sides = (2, 1) if mid > previous_mid else (1, 2)
                for substep, side in enumerate(sides, 1):
                    events.append(event(base_ns+tick*1_000_000_000+substep*100, "M", side,
                                        price=mid-1 if side == 1 else mid+1))
                previous_mid = mid
            table = np.empty(len(events), dtype=dtype)
            for index, row in enumerate(events):
                table[index] = tuple(row[field].encode("ascii") if field == "action_type" else row[field] for field in FIELDS)
            output.create_group("d"+day).create_dataset("table", data=table, compression="gzip")
    hdf.chmod(0o600)
    source = {"schema_version": 1, "source_id": "fictional_native_pekao_v1", "symbol": "PEKAO", "price_currency": "PLN",
              "timestamp_basis": "utc_epoch_milliseconds", "timezone_evidence": "Fictional UTC nanosecond events, causal UTC millisecond boundaries.",
              "data_origin": "synthetic_fixture", "usage_rights": "synthetic_only", "training_usage_rights": "synthetic_only",
              "rights_evidence": "Generated fictional orders for offline engineering checks.",
              "training_rights_evidence": "Generated fictional order messages; no market or expert-trader history.",
              "broker_verified": False, "training_ready": False, "full_history_verified": False}
    spec_path, config_path = directory/"import.synthetic.json", directory/"research.synthetic.json"
    _atomic(spec_path, json_bytes(_spec(source, sha256(hdf.read_bytes()), synthetic=True)))
    _atomic(config_path, json_bytes(_research_config(synthetic=True)))
    return hdf, spec_path, config_path


def run_native_demo(out: Path) -> dict:
    """Exercise real native-table parsing on fictional messages and frozen tests."""
    from .evaluation import run_cost_stress
    from .learning_pipeline import run_learning
    from .wse import import_wse

    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise DataError("NATIVE_DEMO_REQUIRES_FRESH_OUTPUT_DIRECTORY")
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_path = out/"native-workflow.json"
    result = {"schema_version": 1, "status": "in_progress", "started_at_utc": now_utc(),
              "finished_at_utc": None, "network_used": False, "synthetic_only": True,
              "simulation_only": True, "actual_source_acquired": False, "model_fitted": False,
              "symbol": "PEKAO", "price_currency": "PLN", "stages": {}, "errors": [],
              "native_timestamp_basis": "utc_epoch_nanoseconds",
              "sampling_rule": "only native messages strictly before completed UTC bucket-end boundary",
              "bootstrap_policy": "first_non_retransmission_event_assumption",
              "matching_phase_verified": False, "fills_or_queue_priority_identified": False,
              "blockers": ["SYNTHETIC_ONLY_NOT_MARKET_HISTORY", "NATIVE_RECONSTRUCTION_ASSUMPTIONS_UNVERIFIED",
                           "NO_EXPERT_TRADER_HISTORY", "EXECUTION_COSTS_NOT_BROKER_VALIDATED", "NO_BROKER_FORWARD_EVIDENCE"],
              "manifest": str(manifest_path), **_FALSE_FLAGS}
    _atomic(manifest_path, json_bytes(result))
    try:
        hdf, spec, config = _fictional_hdf(out/"synthetic-inputs")
        result["fixture"] = {"hdf": str(hdf), "spec": str(spec), "config": str(config),
                             "hdf_sha256": sha256(hdf.read_bytes()), "spec_sha256": sha256(spec.read_bytes()),
                             "config_sha256": sha256(config.read_bytes()), "days": list(_DAYS)}
        imported = import_wse(hdf, spec, out/"native-import")
        result["stages"]["native_import"] = imported
        _atomic(manifest_path, json_bytes(result))
        if imported["status"] != "completed":
            raise DataError("NATIVE_DEMO_IMPORT_FAILED")
        learned = run_learning(Path(imported["output_csv"]), Path(imported["output_metadata"]), config, out/"learning")
        result["stages"]["learning"] = learned
        _atomic(manifest_path, json_bytes(result))
        if learned["status"] != "completed" or learned.get("selected_threshold") is None or not learned.get("model"):
            raise DataError("NATIVE_DEMO_FROZEN_SELECTION_UNAVAILABLE")
        result["model_fitted"] = True
        stressed = run_cost_stress(Path(imported["output_csv"]), Path(imported["output_metadata"]), config,
                                   Path(learned["model"]), learned["selected_threshold"], out/"stress")
        result["stages"]["cost_stress"] = stressed
        if stressed["status"] != "completed":
            raise DataError("NATIVE_DEMO_COST_STRESS_FAILED")
        result["status"] = "completed"
    except (DataError, OSError) as error:
        result["status"] = "failed"
        result["errors"].append(str(error) if isinstance(error, DataError) else "NATIVE_DEMO_LOCAL_IO_ERROR")
    except KeyboardInterrupt:
        result["status"] = "failed"
        result["errors"].append("INTERRUPTED")
    except Exception:
        result["status"] = "failed"
        result["errors"].append("NATIVE_DEMO_INTERNAL_ERROR")
        raise
    finally:
        result["finished_at_utc"] = now_utc()
        _atomic(manifest_path, json_bytes(result))
    return result
