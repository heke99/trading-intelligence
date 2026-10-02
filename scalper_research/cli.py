"""Local quote research, learning and simulation; no broker order interface."""
from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
import sys

from trading_intelligence.common import DataError, json_bytes
from . import __version__
from .market import import_quotes
from .pipeline import _atomic, run_research, research_status


def demo_inputs(directory: Path) -> tuple[Path, Path, Path]:
    """Write a fixed fictional market, never download or pretend to measure edge."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = 1704186000000  # 2024-01-02 09:00 UTC, artificial quotes below.
    offsets = [-2, 0, 1, 1, 4, 5, 8, 8, 10, 9, 6, 4, 1, -2, -4, -6, -7, -5, -3, 0, 3, 5, 6, 4]
    lines = ["time_msc,bid,ask"]
    for index, offset in enumerate(offsets * 3):
        mid = Decimal("1.100000") + Decimal(offset) * Decimal("0.000010")
        lines.append(f"{base + index * 250},{mid - Decimal('0.000010')},{mid + Decimal('0.000010')}")
    metadata = {
        "schema_version": 1, "source_id": "fictional_eurusd_quote_fixture_v1", "symbol": "EURUSD",
        "timestamp_basis": "utc_epoch_milliseconds", "timezone_evidence": "fixture generator defines UTC epoch milliseconds",
        "data_origin": "synthetic_fixture", "price_currency": "USD", "usage_rights": "synthetic_only",
        "rights_evidence": "entirely fictional prices generated for offline behavior checks",
    }
    config = {
        "schema_version": 1, "basis": "independent_rule_hypothesis",
        "strategy": {"lookback_quotes": 3, "breakout_buffer": "0.000005", "stop_distance": "0.000040",
                     "target_distance": "0.000060", "max_hold_ms": 1500,
                     "session_start_minute_utc": 0, "session_end_minute_utc": 1440, "cooldown_ms": 500},
        "execution": {"symbol": "EURUSD", "quantity": "1000", "contract_multiplier": "1", "price_currency": "USD",
                      "commission_per_unit_per_side": "0.000001", "slippage_price": "0.000001", "latency_ms": 100,
                      "max_quote_gap_ms": 1000, "max_entry_spread": "0.000040", "max_loss_currency": "1", "max_trades": 10},
        "evaluation": {"development_end_msc": base + 24 * 250, "validation_end_msc": base + 48 * 250},
    }
    paths = (directory / "quotes.synthetic.csv", directory / "market.synthetic.json", directory / "config.synthetic.json")
    _atomic(paths[0], ("\n".join(lines) + "\n").encode())
    _atomic(paths[1], json_bytes(metadata))
    _atomic(paths[2], json_bytes(config))
    return paths


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Offline bid/ask import, chronological learning and durable local simulation.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Run fictional quotes through isolated chronological partitions")
    demo.add_argument("--out", type=Path, required=True)
    imp = sub.add_parser("import-quotes", help="Archive an explicit UTC-ms bid/ask CSV without inventing its clock or rights")
    imp.add_argument("file", type=Path)
    imp.add_argument("--metadata", type=Path, required=True)
    imp.add_argument("--out", type=Path, required=True)
    run = sub.add_parser("replay", help="Replay one frozen config across chronological development/validation/test")
    run.add_argument("file", type=Path)
    run.add_argument("--metadata", type=Path, required=True)
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    status = sub.add_parser("status", help="Show newest replay including failed/incomplete run")
    status.add_argument("--out", type=Path, required=True)
    ht = sub.add_parser("import-histdata", help="Convert one local Generic ASCII tick CSV with explicit fixed EST and hash")
    ht.add_argument("file", type=Path)
    ht.add_argument("--spec", type=Path, required=True)
    ht.add_argument("--out", type=Path, required=True)
    shards = sub.add_parser("shard-ticks", help="Archive a large local CSV; split on UTC day/capacity without splitting equal clocks")
    shards.add_argument("file", type=Path)
    shards.add_argument("--evidence", type=Path, required=True, help="Market metadata JSON, or a HistData spec with original file hash")
    shards.add_argument("--source-format", choices=("utc_bidask_csv_v1", "histdata_generic_ascii_tick_v1"), required=True)
    shards.add_argument("--max-shard-rows", type=int, default=500_000)
    shards.add_argument("--max-shard-bytes", type=int, default=32 * 1024 * 1024)
    shards.add_argument("--gap-report-ms", type=int, default=60_000)
    shards.add_argument("--out", type=Path, required=True)
    verify = sub.add_parser("verify-tick-corpus", help="Recheck shard hashes, row locators and strict edges; not authenticity or completeness")
    verify.add_argument("manifest", type=Path)
    proj = sub.add_parser("project-ticks", help="Preserve raw tick rows and derive completed event-time buckets without forward fill")
    proj.add_argument("file", type=Path)
    proj.add_argument("--metadata", type=Path, required=True)
    proj.add_argument("--sample-period-ms", type=int, required=True)
    proj.add_argument("--max-native-gap-ms", type=int, required=True)
    proj.add_argument("--out", type=Path, required=True)
    tr = sub.add_parser("tick-run", help="Archive one local source/config, project, learn and stress one frozen hypothesis")
    tr.add_argument("file", type=Path)
    tr.add_argument("--metadata", type=Path, required=True)
    tr.add_argument("--config", type=Path, required=True)
    tr.add_argument("--sample-period-ms", type=int, required=True)
    tr.add_argument("--max-native-gap-ms", type=int, required=True)
    tr.add_argument("--out", type=Path, required=True)
    for command, help_text in (("tick-plan", "Write the five-asset acquisition and evidence plan without fetching"),
                               ("tick-demo", "Exercise five fictional tick products, development fit and frozen cost stress")):
        ts = sub.add_parser(command, help=help_text)
        ts.add_argument("--out", type=Path, required=True)
    bi5 = sub.add_parser("convert-bi5", help="Decode a local BI5 with explicit clock, scale and source evidence")
    bi5.add_argument("file", type=Path)
    bi5.add_argument("--spec", type=Path, required=True)
    bi5.add_argument("--out", type=Path, required=True)
    ws = sub.add_parser("import-wse", help="Preserve native order events and derive explicit causal boundary snapshots")
    ws.add_argument("file", type=Path)
    ws.add_argument("--spec", type=Path, required=True)
    ws.add_argument("--out", type=Path, required=True)
    wrun = sub.add_parser("wse-run", help="Archive a local native-data plan, import, learn and stress one frozen selection")
    wrun.add_argument("file", type=Path)
    wrun.add_argument("--spec", type=Path, required=True)
    wrun.add_argument("--config", type=Path, required=True)
    wrun.add_argument("--out", type=Path, required=True)
    for command, help_text in (("acquire-wse", "Retrieve and verify the fixed CC BY PEKAO original; no broker or credentials"),
                               ("wse-plan", "Write a predeclared instrument-specific WSE research plan"),
                               ("native-demo", "Exercise synthetic HDF orders, reconstruction, learning and cost stress")):
        wsub = sub.add_parser(command, help=help_text)
        wsub.add_argument("--out", type=Path, required=True)
    learn = sub.add_parser("learn", help="Fit on development only, select threshold on validation, then test once")
    learn.add_argument("file", type=Path)
    learn.add_argument("--metadata", type=Path, required=True)
    learn.add_argument("--config", type=Path, required=True)
    learn.add_argument("--out", type=Path, required=True)
    stress = sub.add_parser("stress", help="Replay one frozen model with five predeclared cost scenarios")
    stress.add_argument("file", type=Path)
    stress.add_argument("--metadata", type=Path, required=True)
    stress.add_argument("--config", type=Path, required=True)
    stress.add_argument("--model", type=Path, required=True)
    stress.add_argument("--threshold", type=float, required=True)
    stress.add_argument("--out", type=Path, required=True)
    ls = sub.add_parser("learning-status", help="Show latest learning receipt including failures")
    ls.add_argument("--out", type=Path, required=True)
    sub.add_parser("strategy-audit", help="Show evidence and market fields still required for named-trader strategies")
    ps = sub.add_parser("paper-start", help="Bind a local append-only quote file to one persistent simulation")
    ps.add_argument("file", type=Path)
    ps.add_argument("--metadata", type=Path, required=True)
    ps.add_argument("--config", type=Path, required=True)
    ps.add_argument("--model", type=Path)
    ps.add_argument("--threshold", type=float)
    ps.add_argument("--out", type=Path, required=True)
    for command, help_text in (("paper-step", "Process complete new quote rows with the same frozen state"),
                               ("paper-stop", "Persist an entry halt; any exit needs later quotes"),
                               ("paper-status", "Read durable simulation status"),
                               ("all-demo", "Exercise every implemented stage on fictional data")):
        psub = sub.add_parser(command, help=help_text)
        psub.add_argument("--out", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "demo":
            paths = demo_inputs(args.out / "synthetic-inputs")
            imported = import_quotes(paths[0], paths[1], args.out)
            if imported["status"] != "completed":
                result = imported
            else:
                result = run_research(*paths, args.out)
                result.update(network_used=False, synthetic_only=True)
        elif args.command == "import-quotes":
            result = import_quotes(args.file, args.metadata, args.out)
        elif args.command == "replay":
            result = run_research(args.file, args.metadata, args.config, args.out)
        elif args.command == "status":
            result = research_status(args.out)
        elif args.command == "import-histdata":
            from .histdata import import_histdata
            result = import_histdata(args.file, args.spec, args.out)
        elif args.command == "shard-ticks":
            from .tick_corpus import shard_ticks
            result = shard_ticks(args.file, args.evidence, args.out, source_format=args.source_format,
                                 max_shard_rows=args.max_shard_rows, max_shard_bytes=args.max_shard_bytes,
                                 gap_report_ms=args.gap_report_ms)
        elif args.command == "verify-tick-corpus":
            from .tick_corpus import verify_tick_corpus
            result = verify_tick_corpus(args.manifest)
        elif args.command == "project-ticks":
            from .tick_projection import project_ticks
            result = project_ticks(args.file, args.metadata, args.out,
                                   sample_period_ms=args.sample_period_ms, max_native_gap_ms=args.max_native_gap_ms)
        elif args.command == "tick-run":
            from .tick_workflow import run_tick_benchmark
            result = run_tick_benchmark(args.file, args.metadata, args.config, args.out,
                                        sample_period_ms=args.sample_period_ms, max_native_gap_ms=args.max_native_gap_ms)
        elif args.command in ("tick-plan", "tick-demo"):
            from .tick_workflow import write_tick_plan, run_tick_demo
            result = write_tick_plan(args.out) if args.command == "tick-plan" else run_tick_demo(args.out)
        elif args.command == "convert-bi5":
            from .bi5 import convert_bi5
            result = convert_bi5(args.file, args.spec, args.out)
        elif args.command == "acquire-wse":
            from .acquire import acquire_wse
            result = acquire_wse(args.out)
        elif args.command == "import-wse":
            from .wse import import_wse
            result = import_wse(args.file, args.spec, args.out)
        elif args.command == "wse-run":
            from .native_workflow import run_wse_benchmark
            result = run_wse_benchmark(args.file, args.spec, args.config, args.out)
        elif args.command in ("wse-plan", "native-demo"):
            from .native_workflow import write_wse_plan, run_native_demo
            result = write_wse_plan(args.out) if args.command == "wse-plan" else run_native_demo(args.out)
        elif args.command == "learn":
            from .learning_pipeline import run_learning
            result = run_learning(args.file, args.metadata, args.config, args.out)
        elif args.command == "stress":
            from .evaluation import run_cost_stress
            result = run_cost_stress(args.file, args.metadata, args.config, args.model, args.threshold, args.out)
        elif args.command == "learning-status":
            from .learning_pipeline import learning_status
            result = learning_status(args.out)
        elif args.command == "strategy-audit":
            from .strategy_requirements import strategy_requirements
            result = {"status": "completed", **strategy_requirements()}
        elif args.command == "paper-start":
            from .paper import start_paper
            result = start_paper(args.file, args.metadata, args.config, args.out,
                                 model_path=args.model, threshold=args.threshold)
        elif args.command.startswith("paper-"):
            from .paper import step_paper, stop_paper, paper_status
            operation = {"paper-step": step_paper, "paper-stop": stop_paper, "paper-status": paper_status}[args.command]
            result = operation(args.out)
        else:
            from .workflow import run_all_demo
            result = run_all_demo(args.out)
        print(json_bytes(result).decode(), end="")
        if any(error in ("INTERRUPTED", "ACQUIRE_INTERRUPTED") for error in result.get("errors", [])):
            return 130
        return 2 if result["status"] == "failed" else 0
    except DataError as error:
        print(json_bytes({"error": str(error), "training_ready": False, "trading_enabled": False}).decode(), file=sys.stderr, end="")
        return 2
    except OSError:
        print('{"error":"RESEARCH_LOCAL_IO_ERROR","training_ready":false}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('{"error":"INTERRUPTED","training_ready":false}', file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
