"""Predeclared execution-cost stress for an already-frozen research policy.

There is no fitting, threshold search, broker connection or acceptance decision.
The reported PnL is hypothetical quote-currency PnL under supplied assumptions.
"""
from __future__ import annotations

from decimal import Context, Decimal, localcontext
from pathlib import Path
from uuid import uuid4

from trading_intelligence.common import DataError, json_bytes, load_json, now_utc, read_limited, sha256
from . import __version__
from .learning import FilteredStrategy
from .paper import _model_context
from .pipeline import _archive, _atomic, parse_config
from .strategy import RollingBreakout

SCENARIOS = (
    ("base", 1, 1, 1),
    ("fee_2x", 2, 1, 1),
    ("slippage_2x", 1, 2, 1),
    ("latency_2x", 1, 1, 2),
    ("combined_2x", 2, 2, 2),
)
_FALSE_FLAGS = {"training_ready": False, "full_history_verified": False,
                "trading_enabled": False, "replay_accepted": False,
                "forward_verified": False, "broker_connected": False,
                "broker_demo_verified": False, "market_history_verified": False,
                "model_trained_on_real_market": False, "training_performed": False}


def _scenario_documents(document: dict) -> list[tuple[str, dict]]:
    """Scale exactly, then revalidate original supported bounds without caps."""
    result = []
    with localcontext(Context(prec=1024)):
        for name, fee_scale, slip_scale, latency_scale in SCENARIOS:
            scenario = {**document, "execution": dict(document["execution"])}
            execution = scenario["execution"]
            execution["commission_per_unit_per_side"] = str(Decimal(execution["commission_per_unit_per_side"])*fee_scale)
            execution["slippage_price"] = str(Decimal(execution["slippage_price"])*slip_scale)
            execution["latency_ms"] *= latency_scale
            parse_config(json_bytes(scenario))
            result.append((name, scenario))
    return result


def _metrics(report: dict) -> dict:
    return {"quote_count": report["quote_count"], "entered_trade_count": report["entered_trade_count"],
            "closed_trade_count": report["closed_trade_count"],
            "has_open_position": report.get("open_position") is not None,
            "has_unfilled_decision": report.get("pending_decision") is not None,
            "risk_halted": report["risk_halted"], "quality_flags": report["quality_flags"],
            "realized_net_pnl_currency": report["realized_net_pnl_currency"],
            "ending_net_equity_currency": report["ending_net_equity_currency"],
            "maximum_drawdown_currency": report["maximum_drawdown_currency"],
            "diagnostics": {"positive_ending_net_equity": Decimal(report["ending_net_equity_currency"]) > 0,
                            "at_least_twenty_closed_trades": report["closed_trade_count"] >= 20,
                            "flat_at_end": report.get("open_position") is None,
                            "no_unknown_gap_path": "GAP_PRICE_PATH_UNKNOWN" not in report["quality_flags"],
                            "risk_not_halted": not report["risk_halted"]}}


def run_cost_stress(csv_path: Path, metadata_path: Path, config_path: Path,
                    model_path: Path, threshold: float, out: Path) -> dict:
    """Replay one frozen filter under five fixed execution assumptions.

    A complete source CSV may include earlier development/validation rows.
    Those rows are explicitly counted and excluded; they never warm up the
    holdout strategy. Selection-bound models require their matching receipt.
    A development-only model may instead use an explicit manual threshold;
    its threshold selection remains unverified and evaluation starts after fit.
    """
    from .engine import replay
    from .market import load_quotes, validate_quote_execution

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    (out/"raw").mkdir(exist_ok=True, mode=0o700)
    run_id = uuid4().hex
    directory = out/"stress-runs"/run_id
    directory.mkdir(parents=True, mode=0o700)
    manifest = {
        "schema_version": 1, "software_version": __version__, "run_id": run_id,
        "started_at_utc": now_utc(), "finished_at_utc": None, "status": "in_progress",
        "raw_files": [], "errors": [], "simulation_only": True, **_FALSE_FLAGS,
        "model_fit_previously": False, "threshold_selection_verified": False,
        "strategy_attribution": RollingBreakout.attribution,
        "evaluation_status": "not_evaluated", "preregistration": {
            "scenarios": [{"name": name, "fee_multiplier": fee, "slippage_multiplier": slip,
                           "latency_multiplier": latency} for name, fee, slip, latency in SCENARIOS],
            "benchmarks": ["no_model_same_rule_base_costs", "reject_all_base_costs"],
            "frozen_policy": "same previously fitted coefficients and supplied threshold in every cost scenario",
            "selection_policy": "no fitting, threshold search, scenario selection or acceptance",
            "diagnostics": "net positive, at least twenty closed trades, flat end, no unknown gap path, no risk halt",
            "diagnostic_scope": "engineering observations, not statistical adequacy or broker admission",
        },
        "blockers": ["EXECUTION_ASSUMPTIONS_NOT_BROKER_VALIDATED", "NO_BROKER_FORWARD_EVIDENCE",
                     "MARKET_HISTORY_NOT_INDEPENDENTLY_VERIFIED", "TRADER_IMITATION_NOT_ESTABLISHED",
                     "HOLDOUT_MAY_HAVE_BEEN_VIEWED_EXTERNALLY", "ACCEPTANCE_NOT_AUTHORIZED"],
    }
    _atomic(directory/"manifest.json", json_bytes(manifest))
    summary_path = directory/"summary.json"
    try:
        archived = {}
        for kind, source, suffix in (("market_quotes", Path(csv_path), "csv"),
                                     ("market_metadata", Path(metadata_path), "json"),
                                     ("frozen_config", Path(config_path), "json"),
                                     ("frozen_model", Path(model_path), "json")):
            raw = read_limited(source)
            relative = _archive(out, raw, suffix)
            archived[kind] = out/relative
            manifest["raw_files"].append({"kind": kind, "path": relative, "sha256": sha256(raw), "bytes": len(raw)})
            _atomic(directory/"manifest.json", json_bytes(manifest))
        config_raw = read_limited(archived["frozen_config"])
        document, strategy_config, base_execution, _ = parse_config(config_raw)
        model_raw = read_limited(archived["frozen_model"])
        # Validate before deciding whether this model declares a selection receipt.
        try:
            context = _model_context(model_raw, config_raw, threshold)
        except DataError as error:
            raise DataError(str(error).replace("PAPER_", "STRESS_", 1)) from None
        model = context["model"]
        selection_raw = None
        if model["provenance"].get("filter_selection") is not None:
            selection_path = Path(model_path).parent/"selection.json"
            if not selection_path.is_file():
                raise DataError("STRESS_MODEL_SELECTION_RECEIPT_REQUIRED")
            selection_raw = read_limited(selection_path)
            relative = _archive(out, selection_raw, "json")
            manifest["raw_files"].append({"kind": "frozen_selection", "path": relative,
                                          "sha256": sha256(selection_raw), "bytes": len(selection_raw)})
            _atomic(directory/"manifest.json", json_bytes(manifest))
            try:
                context = _model_context(model_raw, config_raw, threshold, read_limited(out/relative))
            except DataError as error:
                raise DataError(str(error).replace("PAPER_", "STRESS_", 1)) from None
        dataset = load_quotes(archived["market_quotes"], archived["market_metadata"])
        metadata = dataset.metadata
        if metadata["usage_rights"] == "not_verified":
            raise DataError("STRESS_USAGE_RIGHTS_NOT_ASSERTED")
        if metadata["symbol"] != base_execution.symbol or metadata["price_currency"] != base_execution.price_currency:
            raise DataError("STRESS_INSTRUMENT_OR_CURRENCY_MISMATCH")
        validate_quote_execution(metadata, base_execution)
        if "EQUAL_TIMESTAMP_ORDER_UNVERIFIED" in dataset.quality_flags:
            raise DataError("STRESS_EQUAL_TIMESTAMP_ORDER_UNVERIFIED")
        cutoff = context["minimum_quote_time_msc"]
        quotes = [quote for quote in dataset.quotes if quote.time_msc >= cutoff]
        if len(quotes) < strategy_config.lookback_quotes+2:
            raise DataError("STRESS_HOLDOUT_TOO_SHORT_OR_PRECEDES_FIT_OR_SELECTION")
        manifest.update(
            model_fit_previously=True, model_content_sha256=model["model_sha256"], model_raw_sha256=sha256(model_raw),
            model_data_origin=model["data_origin"], threshold=str(context["threshold"]),
            threshold_selection_verified=context["selection_verified"],
            config_sha256=sha256(config_raw), model_original_quotes_sha256=model["provenance"].get("raw_quotes_sha256"),
            model_original_metadata_sha256=model["provenance"].get("metadata_sha256"),
            source_quotes_sha256=dataset.raw_sha256, source_metadata_sha256=dataset.metadata_sha256,
            source_id=metadata["source_id"], source_data_origin=metadata["data_origin"], source_quality_flags=dataset.quality_flags,
            quote_currency=metadata["price_currency"], symbol=metadata["symbol"],
            cash_balance_or_fx_conversion_applied=False, minimum_quote_time_msc=cutoff,
            holdout_policy="include source rows at or after frozen model use cutoff; no preceding-quote warmup",
            excluded_earlier_quote_count=len(dataset.quotes)-len(quotes), quote_count=len(quotes),
            first_time_msc=quotes[0].time_msc, last_time_msc=quotes[-1].time_msc,
            maximum_holdout_gap_ms=max((b.time_msc-a.time_msc for a,b in zip(quotes, quotes[1:])), default=0),
            synthetic_only=metadata["data_origin"] == "synthetic_fixture",
        )
        scenarios = _scenario_documents(document)
        if not context["selection_verified"]:
            manifest["blockers"].append("MANUAL_THRESHOLD_SELECTION_NOT_VERIFIED")
        if manifest["synthetic_only"]:
            manifest["blockers"].append("SYNTHETIC_QUOTES_NOT_MARKET_EVIDENCE")
        if model["data_origin"] == "synthetic_fixture":
            manifest["blockers"].append("MODEL_FITTED_ON_SYNTHETIC_QUOTES")
        scenario_results = {}
        benchmarks = {}

        def evaluate(name, settings, runner, *, benchmark=None):
            config_bytes = json_bytes(settings)
            _, _, execution, _ = parse_config(config_bytes)
            try:
                report = replay(quotes, runner, execution)
            except ValueError as error:
                if isinstance(error, DataError):
                    raise
                raise DataError("STRESS_EXECUTION_INPUT_INVALID") from None
            report.update(quote_count=len(quotes), scenario=name, benchmark=benchmark,
                          quote_currency=metadata["price_currency"], source_data_origin=metadata["data_origin"],
                          source_quality_flags=list(dataset.quality_flags),
                          frozen_config_sha256=manifest["config_sha256"], scenario_config_sha256=sha256(config_bytes),
                          source_quotes_sha256=dataset.raw_sha256, model_content_sha256=model["model_sha256"],
                          model_used=isinstance(runner, FilteredStrategy),
                          frozen_threshold=str(context["threshold"]),
                          actual_filter_threshold=str(runner.threshold) if isinstance(runner, FilteredStrategy) else None,
                          simulation_only=True, cost_basis="quote currency; per-unit-per-side commission and absolute-price slippage",
                          **_FALSE_FLAGS)
            if isinstance(runner, FilteredStrategy):
                report["filter_decisions"] = runner.decisions
            _atomic(directory/(name+".json"), json_bytes(report))
            _atomic(directory/(name+".config.json"), config_bytes)
            return {"report": name+".json", "execution": settings["execution"], **_metrics(report)}

        for name, settings in scenarios:
            scenario_results[name] = evaluate(name, settings, FilteredStrategy(strategy_config, model, context["threshold"]))
        benchmarks["no_model"] = evaluate("benchmark_no_model", document, RollingBreakout(strategy_config),
                                           benchmark="no_model_same_rule_base_costs")
        benchmarks["reject_all"] = evaluate("benchmark_reject_all", document,
                                             FilteredStrategy(strategy_config, model, 1.0),
                                             benchmark="explicit_reject_all_control_base_costs")
        manifest.update(status="completed", finished_at_utc=now_utc(),
                        scenario_results=scenario_results, benchmarks=benchmarks,
                        evaluation_status="synthetic_behavior_check" if manifest["synthetic_only"] else "unaccepted_market_research")
        _atomic(summary_path, json_bytes({**manifest, "status": "completed",
                                         "report_semantics": "realized net excludes open EOF positions; ending equity includes hypothetical liquidation costs",
                                         "parameter_selection_performed": False, "acceptance": "unaccepted"}))
    except (DataError, OSError) as error:
        manifest["status"] = "failed"
        manifest["errors"].append(str(error) if isinstance(error, DataError) else "STRESS_LOCAL_IO_ERROR")
    except KeyboardInterrupt:
        manifest["status"] = "failed"
        manifest["errors"].append("INTERRUPTED")
    except Exception:
        manifest["status"] = "failed"
        manifest["errors"].append("STRESS_INTERNAL_ERROR")
        raise
    finally:
        manifest["finished_at_utc"] = manifest["finished_at_utc"] or now_utc()
        _atomic(directory/"manifest.json", json_bytes(manifest))
    return {**manifest, "manifest": str(directory/"manifest.json"),
            "summary": str(summary_path) if manifest["status"] == "completed" else None}
