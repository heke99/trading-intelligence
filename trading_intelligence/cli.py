"""Dependency-free command line. API secrets are never accepted as CLI flags."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from . import __version__
from .collective2 import C2Client, COMMISSION_PLANS
from .common import DataError, json_bytes, load_json, read_limited
from .pipeline import fetch_history, import_csv, import_json, inspect_csv
from .publisher_pipeline import import_trader_xlsx, import_publisher_evidence, publisher_status
from .trader_acquisition import download_trader_sources


def _summary(report: dict, out: Path) -> dict:
    keys = ("run_id", "strategy_id", "status", "source_rows", "inserted_versions", "duplicate_observations",
            "revision_observations", "quarantined_rows", "training_ready", "full_history_verified",
            "endpoint_traversal", "errors", "blockers")
    return {**{k: report[k] for k in keys},
            "manifest": str(out / "runs" / report["run_id"] / "manifest.json")}


def _publisher_summary(report: dict, out: Path) -> dict:
    keys = ("run_id", "mode", "status", "source_rows", "inserted_versions", "duplicate_observations",
            "revision_observations", "inserted_snapshots", "temporal_quarantined_rows", "record_type_counts",
            "quality_flag_counts", "training_ready", "full_history_verified", "market_history_joined",
            "training_rights", "errors", "blockers")
    return {**{key: report[key] for key in keys},
            "manifest": str(out / "publisher-runs" / report["run_id"] / "manifest.json")}


def _demo(out: Path) -> dict:
    # Entirely made-up records. Never mix their performance with real research data.
    strategy = 900000001
    base = {"StrategyId": strategy, "C2Symbol": {"FullSymbol": "EUR/USD", "SymbolType": "forex"},
            "ExchangeSymbol": {"Currency": "USD"}}
    closed = [{**base, "Id": i, "TradeId": i,
               "OpenDate": f"2024-01-0{i}T09:00:00Z", "CloseDate": f"2024-01-0{i}T10:00:00Z",
               "AvgOpenFillPrice": "1.1000", "AvgCloseFillPrice": exit_price,
               "OpenedQuantity": "1000", "ClosedQuantity": "1000", "OpenSide": "1", "CloseSide": "2",
               "ProfitLoss": pnl, "Commission": "0.10"}
              for i, exit_price, pnl in ((2, "1.1010", "1.00"), (3, "1.0990", "-1.00"))]
    orders = [{**base, "Id": 100+i, "SignalId": 100+i, "Side": "1", "OpenClose": "O",
               "OrderStatus": "2", "PostedDate": f"2024-01-0{i}T08:59:59Z",
               "OrderQuantity": "1000", "FilledQuantity": "1000", "AvgFillPrice": "1.1000"}
              for i in (2, 3)]
    reports = []
    with tempfile.TemporaryDirectory() as directory:
        for kind, rows in (("closed_trades", closed), ("orders", orders)):
            path = Path(directory) / (kind + ".json")
            path.write_bytes(json_bytes({"Results": rows, "ResponseStatus": {"ErrorCode": "200"}}))
            report = import_json(path, out, kind=kind, strategy_id=strategy, synthetic=True)
            reports.append(_summary(report, out))
    return {"synthetic_only": True, "network_used": False, "training_ready": False, "runs": reports}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read-only trading-history acquisition; no trading or training.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Run an offline synthetic import")
    demo.add_argument("--out", type=Path, default=Path("data/demo"))
    fetch = sub.add_parser("fetch", help="Fetch closed trades + paginated orders, using GET only")
    fetch.add_argument("--strategy-id", type=int, required=True)
    fetch.add_argument("--out", type=Path, required=True)
    fetch.add_argument("--commission-plan", choices=sorted(COMMISSION_PLANS), default="0")
    fetch.add_argument("--max-pages", type=int, default=200)
    fetch.add_argument("--acknowledge-authorized-access", action="store_true",
                       help="Confirm you may retrieve and store this strategy's data (NOT an ML license)")
    fetch.add_argument("--naive-timezone", help="Only for verified timezone-less trade timestamps")
    fetch.add_argument("--timezone-evidence", help="Non-secret reference to written timezone confirmation")
    imp = sub.add_parser("import-json", help="Import one saved API4 response, not a guessed JSON format")
    imp.add_argument("file", type=Path)
    imp.add_argument("--kind", choices=["orders", "closed_trades"], required=True)
    imp.add_argument("--strategy-id", type=int, required=True)
    imp.add_argument("--out", type=Path, required=True)
    imp.add_argument("--naive-timezone")
    imp.add_argument("--timezone-evidence")
    imp.add_argument("--synthetic-fixture", action="store_true", help="Mark local test data as synthetic")
    inspect = sub.add_parser("inspect-csv", help="Show headers/count only; does not print private trade rows")
    inspect.add_argument("file", type=Path)
    csv_imp = sub.add_parser("import-csv", help="Import a CSV with a reviewed, explicit column mapping")
    csv_imp.add_argument("file", type=Path)
    csv_imp.add_argument("--mapping", type=Path, required=True)
    csv_imp.add_argument("--strategy-id", type=int, required=True)
    csv_imp.add_argument("--out", type=Path, required=True)
    csv_imp.add_argument("--synthetic-fixture", action="store_true", help="Mark local test data as synthetic")
    status = sub.add_parser("status", help="Show the newest manifest, including incomplete/failed runs")
    status.add_argument("--out", type=Path, required=True)
    download = sub.add_parser("download-trader-sources", help="Fetch exact reviewed public XLSX URLs; stop on access errors")
    download.add_argument("--catalog", type=Path, required=True)
    download.add_argument("--out", type=Path, required=True)
    download.add_argument("--source-id", action="append")
    trader = sub.add_parser("import-trader-xlsx", help="Import documented publisher XLSX as observations, not C2 fills")
    trader.add_argument("--catalog", type=Path, required=True)
    trader.add_argument("--raw-dir", type=Path, required=True)
    trader.add_argument("--out", type=Path, required=True)
    trader.add_argument("--source-id", action="append", help="Select catalog source IDs; default all")
    trader.add_argument("--day-only", action="store_true", help="Keep Swing sheets outside this requested import scope")
    trader.add_argument("--receipts-dir", type=Path, help="Optional hash-matched download_manifest receipts")
    trader.add_argument("--synthetic-fixture", action="store_true")
    evidence = sub.add_parser("import-publisher-evidence", help="Import reviewed image/journal facts or education cards")
    evidence.add_argument("file", type=Path)
    evidence.add_argument("--kind", choices=["image_transactions", "journal_summaries", "strategy_cards"], required=True)
    evidence.add_argument("--source-id", required=True)
    evidence.add_argument("--out", type=Path, required=True)
    evidence.add_argument("--assets-root", type=Path, help="For images: root containing the reported original asset path")
    evidence.add_argument("--synthetic-fixture", action="store_true")
    publisher = sub.add_parser("publisher-status", help="Show publisher evidence scope, quality and historical versions")
    publisher.add_argument("--out", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "demo":
            result = _demo(args.out)
        elif args.command == "fetch":
            if not args.acknowledge_authorized_access:
                raise DataError("AUTHORIZED_ACCESS_ACK_REQUIRED")
            if args.naive_timezone and not args.timezone_evidence:
                raise DataError("TIMEZONE_EVIDENCE_REQUIRED")
            key = os.environ.get("C2_API_KEY")
            if not key:
                if not sys.stdin.isatty():
                    raise DataError("API_KEY_REQUIRED_USE_LOCAL_ENV_OR_INTERACTIVE_PROMPT")
                key = getpass.getpass("Collective2 API4 key (hidden; never send it in chat): ")
            client = C2Client(key, max_pages=args.max_pages)
            report = fetch_history(client, args.out, strategy_id=args.strategy_id,
                                   commission_plan=args.commission_plan,
                                   naive_timezone=args.naive_timezone, timezone_evidence=args.timezone_evidence)
            result = _summary(report, args.out)
        elif args.command == "import-json":
            report = import_json(args.file, args.out, kind=args.kind, strategy_id=args.strategy_id,
                                 naive_timezone=args.naive_timezone, timezone_evidence=args.timezone_evidence,
                                 synthetic=args.synthetic_fixture)
            result = _summary(report, args.out)
        elif args.command == "inspect-csv":
            result = inspect_csv(args.file)
        elif args.command == "import-csv":
            result = _summary(import_csv(args.file, args.mapping, args.out, strategy_id=args.strategy_id, synthetic=args.synthetic_fixture), args.out)
        elif args.command == "download-trader-sources":
            result = download_trader_sources(args.catalog, args.out, source_ids=args.source_id)
        elif args.command == "import-trader-xlsx":
            report = import_trader_xlsx(args.catalog, args.raw_dir, args.out, source_ids=args.source_id,
                                       include_swing=not args.day_only, synthetic=args.synthetic_fixture,
                                       receipts_dir=args.receipts_dir)
            result = _publisher_summary(report, args.out)
        elif args.command == "import-publisher-evidence":
            report = import_publisher_evidence(args.file, args.out, kind=args.kind, source_id=args.source_id,
                                               synthetic=args.synthetic_fixture, assets_root=args.assets_root)
            result = _publisher_summary(report, args.out)
        elif args.command == "publisher-status":
            status = publisher_status(args.out)
            result = {**status, "latest_run": _publisher_summary(status["latest_run"], args.out)}
        else:
            files = list((args.out / "runs").glob("*/manifest.json"))
            if not files:
                raise DataError("NO_RUNS_FOUND")
            reports = [load_json(read_limited(path)) for path in files]
            report = max(reports, key=lambda m: m["started_at_utc"])
            result = _summary(report, args.out)
        print(json_bytes(result).decode(), end="")
        if "INTERRUPTED" in result.get("errors", []):
            return 130
        return 2 if result.get("status") == "failed" else 0
    except DataError as error:
        print(json.dumps({"error": str(error), "training_ready": False}), file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error):
        print('{"error":"LOCAL_IO_OR_DATABASE_ERROR","training_ready":false}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('{"error":"INTERRUPTED","training_ready":false}', file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
