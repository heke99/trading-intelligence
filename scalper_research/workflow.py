"""One offline engineering demonstration, with explicit evidence boundaries."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from trading_intelligence.common import DataError, json_bytes, load_json, now_utc, read_limited
from .pipeline import _atomic


def learning_demo_inputs(directory: Path) -> tuple[Path, Path, Path]:
    """Generate three fictional sessions, never market or expert-trade evidence.

    A fixed pseudo-random integer walk includes trends and reversals to exercise
    both outcome classes. Session-close quotes allow pending exits to complete.
    Nothing about the fixture is a measurement of trading profitability.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = 1704186000000  # 2024-01-02 09:00 UTC.
    lines = ["time_msc,bid,ask"]
    for day in range(3):
        seed = 97 + day * 61
        offset = 0
        for tick in range(603):
            seed = (1664525 * seed + 1013904223) % (2 ** 32)
            if tick < 600:
                regime = (tick // 60) % 4
                noise = int(seed % 11) - 5
                offset += noise + (2 if regime == 0 else -2 if regime == 1 else 0)
            mid = Decimal("1.100000") + Decimal(offset) * Decimal("0.000010")
            lines.append(f"{base + day * 86400000 + tick * 1000},{mid - Decimal('0.000010')},{mid + Decimal('0.000010')}")
    metadata = {
        "schema_version": 1, "source_id": "fictional_learning_quote_fixture_v1", "symbol": "EURUSD",
        "timestamp_basis": "utc_epoch_milliseconds", "timezone_evidence": "generator explicitly defines UTC epoch milliseconds",
        "data_origin": "synthetic_fixture", "price_currency": "USD", "usage_rights": "synthetic_only",
        "training_usage_rights": "synthetic_only",
        "rights_evidence": "fictional prices generated locally for offline engineering checks",
        "training_rights_evidence": "generated fixture; not a trader or market history",
    }
    config = {
        "schema_version": 1, "basis": "independent_rule_hypothesis",
        "strategy": {"lookback_quotes": 3, "breakout_buffer": "0.000005", "stop_distance": "0.000040",
                     "target_distance": "0.000060", "max_hold_ms": 5000,
                     "session_start_minute_utc": 540, "session_end_minute_utc": 550, "cooldown_ms": 1000},
        "execution": {"symbol": "EURUSD", "quantity": "1000", "contract_multiplier": "1", "price_currency": "USD",
                      "commission_per_unit_per_side": "0.000001", "slippage_price": "0.000001", "latency_ms": 100,
                      "max_quote_gap_ms": 1000, "max_entry_spread": "0.000040", "max_loss_currency": "1000", "max_trades": 1000},
        "evaluation": {"development_end_msc": base + 86400000, "validation_end_msc": base + 2 * 86400000},
    }
    paths = (directory / "quotes.synthetic.csv", directory / "market.synthetic.json", directory / "config.synthetic.json")
    _atomic(paths[0], ("\n".join(lines) + "\n").encode())
    _atomic(paths[1], json_bytes(metadata))
    _atomic(paths[2], json_bytes(config))
    return paths


def _run_all_demo(out: Path) -> dict:
    """Exercise import, learning, frozen evaluation and a stopped paper session."""
    from .learning_pipeline import run_learning
    from .market import import_quotes
    from .paper import start_paper, step_paper, stop_paper, paper_status

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (out / "paper" / "paper.sqlite3").exists():
        raise DataError("ALL_DEMO_REQUIRES_FRESH_OUTPUT_DIRECTORY")
    paths = learning_demo_inputs(out / "synthetic-inputs")
    result = {
        "schema_version": 1, "status": "in_progress", "started_at_utc": now_utc(),
        "network_used": False, "synthetic_only": True, "simulation_only": True,
        "training_ready": False, "full_history_verified": False, "trading_enabled": False,
        "forward_verified": False, "broker_connected": False,
        "model_trained_on_real_market": False, "expert_trader_imitation_verified": False,
        "stages": {}, "errors": [],
        "remaining_evidence": ["PERMITTED_TIMESTAMPED_MARKET_QUOTES", "DOCUMENTED_EXPERT_DECISIONS_IF_IMITATION_IS_INTENDED",
                               "UNTOUCHED_MARKET_TEST_AND_COST_STRESS", "BROKER_DEMO_EXECUTION_AND_FORWARD_EVIDENCE"],
    }
    manifest = out / "workflow.json"
    _atomic(manifest, json_bytes(result))
    imported = import_quotes(paths[0], paths[1], out / "quotes")
    result["stages"]["quote_import"] = {"status": imported["status"], "manifest": imported.get("manifest_path")}
    if imported["status"] != "completed":
        result.update(status="failed", errors=imported.get("errors", []))
    else:
        learned = run_learning(*paths, out / "learning")
        result["stages"]["learning"] = learned
        if learned["status"] != "completed" or learned.get("selected_threshold") is None:
            result.update(status="failed", errors=learned.get("errors", []) + ["DEMO_FROZEN_SELECTION_UNAVAILABLE"])
        else:
            # The fictional test session follows both fit and selection clocks.
            # Appending historical rows is not a broker or verified forward test.
            input_lines = paths[0].read_bytes().splitlines(keepends=True)
            all_lines = [input_lines[0], *input_lines[1 + 2 * 603:]]
            producer = out / "synthetic-inputs" / "paper.synthetic.csv"
            _atomic(producer, all_lines[0])
            model_path = learned.get("model") or learned.get("model_path")
            if not model_path:
                raise DataError("DEMO_MODEL_PATH_UNAVAILABLE")
            session = start_paper(producer, paths[1], paths[2], out / "paper",
                                  model_path=Path(model_path), threshold=float(learned["selected_threshold"]))
            _atomic(producer, b"".join(all_lines[:201]))
            first = step_paper(out / "paper")
            restarted = paper_status(out / "paper")
            if first["accepted_prefix_sha256"] != restarted["accepted_prefix_sha256"]:
                raise DataError("DEMO_PAPER_RESTART_MISMATCH")
            stopped = stop_paper(out / "paper")
            _atomic(producer, b"".join(all_lines[:604]))
            final = step_paper(out / "paper")
            if final["status"] != "stopped_flat":
                raise DataError("DEMO_PAPER_STOP_DID_NOT_COMPLETE")
            result["stages"]["paper"] = {
                "status": final["status"], "initial_status": session["status"],
                "observed_before_stop": first["report"]["quote_count"],
                "stop_request_status": stopped["status"], "database": final["database"],
                "quote_count": final["report"]["quote_count"], "model_used": True,
                "mode": "appended_fictional_quotes", "forward_verified": False,
                "closed_trade_count": final["report"]["closed_trade_count"],
                "pending_decision": final["report"]["pending_decision"],
            }
            _atomic(out / "paper-proof.json", json_bytes(final))
            result.update(status="completed", model_fitted=True)
    result["finished_at_utc"] = now_utc()
    result["manifest"] = str(manifest)
    _atomic(manifest, json_bytes(result))
    return result


def run_all_demo(out: Path) -> dict:
    """Keep a finished failure receipt when an interrupted stage cannot finish."""
    out = Path(out)
    # Reusing an existing simulation must not rewrite its original receipt.
    if (out / "paper" / "paper.sqlite3").exists():
        raise DataError("ALL_DEMO_REQUIRES_FRESH_OUTPUT_DIRECTORY")
    try:
        return _run_all_demo(out)
    except BaseException as error:
        manifest = out / "workflow.json"
        if manifest.exists():
            result = load_json(read_limited(manifest))
            if result.get("status") == "in_progress":
                code = (str(error) if isinstance(error, DataError) else "INTERRUPTED"
                        if isinstance(error, KeyboardInterrupt) else "WORKFLOW_LOCAL_IO_ERROR"
                        if isinstance(error, OSError) else "WORKFLOW_INTERNAL_ERROR")
                result.update(status="failed", finished_at_utc=now_utc())
                result["errors"].append(code)
                _atomic(manifest, json_bytes(result))
        raise
