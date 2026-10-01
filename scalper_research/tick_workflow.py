"""Local tick research workflow; no acquisition or broker execution."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from trading_intelligence.common import DataError, json_bytes, load_json, now_utc, sha256
from .market import _read_limited, load_quotes, validate_quote_execution
from .pipeline import _archive, _atomic, parse_config

_FALSE = {"training_ready": False, "full_history_verified": False, "trading_enabled": False,
          "broker_connected": False, "broker_verified": False, "forward_verified": False,
          "expert_trader_imitation_verified": False, "model_trained_on_real_market": False}
ASSETS = ("EURUSD", "Nasdaq", "XAUUSD", "GBPJPY", "EURJPY")


def write_tick_plan(out: Path) -> dict:
    """Write a candidate acquisition plan, with no assumed contracts or rights."""
    out = Path(out)
    directory = out/"tick-plan"/uuid4().hex
    directory.mkdir(parents=True, mode=0o700)
    assets = []
    for asset in ASSETS:
        assets.append({"requested_asset": asset, "exact_broker_symbol": None, "broker_product": None,
                       "candidate_histdata_symbol": "NSXUSD" if asset == "Nasdaq" else asset,
                       "candidate_is_actual_broker_product": False,
                       "requested_from_utc": "2024-01-01T00:00:00Z",
                       "requested_until_utc_exclusive": "2026-10-01T00:00:00Z",
                       "requested_period_is_available_coverage": False,
                       "original_archive": None, "original_csv": None, "sha256": None,
                       "observed_first_time_msc": None, "observed_last_time_msc": None,
                       "received_tick_rows": 0, "received_market_bytes": 0,
                       "quantity_unit": None, "contract_multiplier": None, "commission_basis": None,
                       "training_usage_rights": "not_verified", "status": "awaiting_original_and_evidence"})
    result = {"schema_version": 1, "record_kind": "multiasset_candidate_plan", "status": "completed",
              "created_at_utc": now_utc(), "network_used": False, "acquisition_performed": False,
              "actual_source_acquired": False, "model_fitted": False, "assets": assets,
              "spelling_normalization": {"input": "GPBJPY", "canonical": "GBPJPY"},
              "period_basis": "proposed multi-regime target, not user-confirmed or provider-verified",
              "catalog_probe": {"source_url": "https://www.histdata.com/download-free-forex-data/",
                                "checked_on": "2026-10-01", "network_attempted": True,
                                "network_request_count": 1, "received_bytes": 0,
                                "status": "failed", "error": "NETWORK_BLOCKED_OR_UNAVAILABLE"},
              "steps": ["confirm exact product and existing data rights",
                        "obtain original archives through permitted access",
                        "import one small original per asset and reconcile clock/scale/rows",
                        "audit requested coverage, sessions and missing intervals",
                        "freeze historical units/costs, strategy and chronological partitions",
                        "project with explicit event-time sampling and gap constraints",
                        "fit development, freeze validation choice, evaluate later test and cost stress",
                        "obtain separate broker demo fills and forward evidence before any live use"],
              "guides": ["docs/TICK_SOURCE_AUDIT_SV.md", "docs/TICK_EXECUTION_EVIDENCE_SV.md",
                         "docs/TICK_WORKFLOW_SV.md", "docs/MT5_EXPORT_SV.md"],
              "blockers": ["NO_ORIGINAL_TICK_HISTORY", "BROKER_PRODUCT_UNKNOWN",
                           "HISTORICAL_CONTRACT_AND_COSTS_UNVERIFIED", "TRAINING_RIGHTS_NOT_VERIFIED",
                           "NO_BROKER_FORWARD_EVIDENCE"], **_FALSE}
    path = directory/"manifest.json"
    result["manifest"] = str(path)
    _atomic(path, json_bytes(result))
    return result


def run_tick_benchmark(file: Path, metadata_path: Path, config_path: Path, out: Path, *,
                       sample_period_ms: int, max_native_gap_ms: int) -> dict:
    """Archive one explicit source, derive observations, fit and freeze evaluation.

    Quotes and hypothetical labels never assert broker fills or expert imitation.
    Event-time bucket observations do not supply a broker receive clock or prove
    executable liquidity. Every asset requires its own supplied config/currency.
    """
    from .evaluation import run_cost_stress
    from .learning_pipeline import run_learning
    from .tick_projection import project_ticks

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    (out/"raw").mkdir(exist_ok=True, mode=0o700)
    directory = out/"tick-benchmark-runs"/uuid4().hex
    directory.mkdir(parents=True, mode=0o700)
    manifest_path = directory/"manifest.json"
    result = {"schema_version": 1, "record_kind": "local_tick_history_benchmark",
              "status": "in_progress", "started_at_utc": now_utc(), "finished_at_utc": None,
              "manifest": str(manifest_path), "network_used": False, "acquisition_performed": False,
              "simulation_only": True, "model_fitted": False, "actual_source_acquired": False,
              "source_data_origin": None, "synthetic_only": None,
              "raw_files": [], "stages": {}, "errors": [],
              "sample_period_ms": sample_period_ms, "max_native_gap_ms": max_native_gap_ms,
              "selection_scope": "development fit; validation threshold; frozen test and stress without refit",
              "external_holdout_visibility": "unknown",
              "blockers": ["EVENT_TIME_NOT_VERIFIED_BROKER_RECEIVE_CLOCK",
                           "DERIVED_OBSERVATIONS_NOT_VERIFIED_EXECUTABLE_LIQUIDITY",
                           "SOURCE_PERMISSION_ASSERTIONS_NOT_INDEPENDENTLY_VERIFIED",
                           "HISTORICAL_CONTRACT_AND_COSTS_NOT_BROKER_VALIDATED",
                           "NO_EXPERT_TRADER_HISTORY", "NO_BROKER_FORWARD_EVIDENCE",
                           "HOLDOUT_MAY_HAVE_BEEN_VIEWED_EXTERNALLY"], **_FALSE}
    _atomic(manifest_path, json_bytes(result))
    try:
        archived = {}
        for kind, source, suffix in (("source_quotes", Path(file), "csv"),
                                     ("source_metadata", Path(metadata_path), "json"),
                                     ("frozen_config", Path(config_path), "json")):
            raw = _read_limited(source)
            relative = _archive(out, raw, suffix)
            target = out/relative
            target.chmod(0o400)
            archived[kind] = target
            result["raw_files"].append({"kind": kind, "path": str(target), "sha256": sha256(raw), "bytes": len(raw)})
            _atomic(manifest_path, json_bytes(result))
        frozen_raw = _read_limited(archived["frozen_config"])
        config, _, engine_config, _ = parse_config(frozen_raw)
        source = load_quotes(archived["source_quotes"], archived["source_metadata"])
        result.update(symbol=source.metadata["symbol"], price_currency=source.metadata["price_currency"],
                      source_data_origin=source.metadata["data_origin"],
                      synthetic_only=source.metadata["data_origin"] == "synthetic_fixture",
                      source_quote_count=len(source.quotes), source_quality_flags=source.quality_flags)
        if source.metadata["symbol"] != engine_config.symbol or source.metadata["price_currency"] != engine_config.price_currency:
            raise DataError("TICK_BENCHMARK_INSTRUMENT_OR_CURRENCY_MISMATCH")
        projected = project_ticks(archived["source_quotes"], archived["source_metadata"], out/"projection",
                                  sample_period_ms=sample_period_ms, max_native_gap_ms=max_native_gap_ms)
        result["stages"]["projection"] = projected
        _atomic(manifest_path, json_bytes(result))
        if projected["status"] != "completed":
            raise DataError("TICK_BENCHMARK_PROJECTION_FAILED")
        projected_metadata = load_json(_read_limited(Path(projected["output_metadata"])))
        validate_quote_execution(projected_metadata, engine_config)
        learned = run_learning(Path(projected["output_csv"]), Path(projected["output_metadata"]),
                               archived["frozen_config"], out/"learning")
        result["stages"]["learning"] = learned
        result["model_fitted"] = learned.get("model_fitted") is True
        _atomic(manifest_path, json_bytes(result))
        if learned["status"] != "completed" or learned.get("selected_threshold") is None or not learned.get("model"):
            raise DataError("TICK_BENCHMARK_FROZEN_SELECTION_UNAVAILABLE")
        stressed = run_cost_stress(Path(projected["output_csv"]), Path(projected["output_metadata"]),
                                   archived["frozen_config"], Path(learned["model"]),
                                   learned["selected_threshold"], out/"stress")
        result["stages"]["cost_stress"] = stressed
        if stressed["status"] != "completed":
            raise DataError("TICK_BENCHMARK_COST_STRESS_FAILED")
        result.update(status="completed",
                      evaluation_status="synthetic_behavior_check" if result["synthetic_only"] else "unaccepted_market_research")
    except (DataError, OSError) as error:
        result["status"] = "failed"
        result["errors"].append(str(error) if isinstance(error, DataError) else "TICK_BENCHMARK_LOCAL_IO_ERROR")
    except KeyboardInterrupt:
        result["status"] = "failed"
        result["errors"].append("INTERRUPTED")
    except Exception:
        result["status"] = "failed"
        result["errors"].append("TICK_BENCHMARK_INTERNAL_ERROR")
        raise
    finally:
        result["finished_at_utc"] = now_utc()
        _atomic(manifest_path, json_bytes(result))
    return result


def run_tick_demo(out: Path) -> dict:
    """Exercise five separate fictional quote products and currencies offline."""
    from .workflow import learning_demo_inputs

    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise DataError("TICK_DEMO_REQUIRES_FRESH_OUTPUT_DIRECTORY")
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = out/"tick-demo.json"
    result = {"schema_version": 1, "status": "in_progress", "started_at_utc": now_utc(),
              "finished_at_utc": None, "manifest": str(path), "synthetic_only": True,
              "simulation_only": True, "actual_source_acquired": False, "network_used": False,
              "model_fitted": False, "assets": {}, "errors": [],
              "cross_currency_pnl_aggregated": False,
              "fixture_note": "Fictional prices, sizes and fees; no broker specification or return evidence.", **_FALSE}
    _atomic(path, json_bytes(result))
    try:
        base_paths = learning_demo_inputs(out/"fixture-base")
        original_lines = base_paths[0].read_text().splitlines()[1:]
        base_metadata = load_json(base_paths[1].read_bytes())
        base_config = load_json(base_paths[2].read_bytes())
        # Price/quantity scales only exercise different decimal and currency paths.
        settings = (("EURUSD", "EURUSD", "USD", "1.1", "1", "1000"),
                    ("Nasdaq", "NAS100_SYNTHETIC", "USD", "18000", "10000", "1"),
                    ("XAUUSD", "XAUUSD", "USD", "2000", "1000", "1"),
                    ("GBPJPY", "GBPJPY", "JPY", "180", "100", "1000"),
                    ("EURJPY", "EURJPY", "JPY", "160", "100", "1000"))
        for asset, symbol, currency, pivot, scaling, quantity in settings:
            factor = Decimal(scaling)
            directory = out/"synthetic-inputs"/symbol
            directory.mkdir(parents=True, mode=0o700)
            lines = ["time_msc,bid,ask"]
            for line in original_lines:
                native_time, bid, ask = line.split(",")
                bid = Decimal(pivot)+(Decimal(bid)-Decimal("1.1"))*factor
                ask = Decimal(pivot)+(Decimal(ask)-Decimal("1.1"))*factor
                clock = int(native_time)
                # Two distinct prices share one native millisecond; no extra time
                # is invented to impose a fictional exchange sequence.
                lines.extend([f"{clock-2},{bid},{ask}",
                              f"{clock-1},{bid-factor*Decimal('0.000001')},{ask}",
                              f"{clock-1},{bid},{ask}"])
            metadata = {**base_metadata, "source_id": "fictional_tick_"+symbol.lower(),
                        "symbol": symbol, "price_currency": currency,
                        "timezone_evidence": "fictional generator defines UTC ms; equal clocks preserve physical row order"}
            config = load_json(json_bytes(base_config))
            config["execution"].update(symbol=symbol, price_currency=currency, quantity=quantity)
            for key in ("slippage_price", "max_entry_spread", "commission_per_unit_per_side"):
                config["execution"][key] = str(Decimal(config["execution"][key])*factor)
            config["execution"]["max_loss_currency"] = "1000000"
            for key in ("breakout_buffer", "stop_distance", "target_distance"):
                config["strategy"][key] = str(Decimal(config["strategy"][key])*factor)
            paths = (directory/"ticks.synthetic.csv", directory/"source.synthetic.json", directory/"config.synthetic.json")
            _atomic(paths[0], ("\n".join(lines)+"\n").encode())
            _atomic(paths[1], json_bytes(metadata))
            _atomic(paths[2], json_bytes(config))
            benchmark = run_tick_benchmark(*paths, out/"assets"/symbol,
                                           sample_period_ms=1000, max_native_gap_ms=1000)
            result["assets"][asset] = benchmark
            _atomic(path, json_bytes(result))
            if benchmark["status"] != "completed":
                raise DataError("TICK_DEMO_ASSET_FAILED:"+asset)
        result.update(status="completed", model_fitted=True)
    except (DataError, OSError) as error:
        result["status"] = "failed"
        result["errors"].append(str(error) if isinstance(error, DataError) else "TICK_DEMO_LOCAL_IO_ERROR")
    except KeyboardInterrupt:
        result["status"] = "failed"
        result["errors"].append("INTERRUPTED")
    except Exception:
        result["status"] = "failed"
        result["errors"].append("TICK_DEMO_INTERNAL_ERROR")
        raise
    finally:
        result["finished_at_utc"] = now_utc()
        _atomic(path, json_bytes(result))
    return result
