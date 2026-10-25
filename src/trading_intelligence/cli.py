"""A repeatable offline demonstration, containing invented data only."""

import argparse
from datetime import datetime
import json
from pathlib import Path

from .contracts import AssetKind, DataOrigin, Entity, Instrument, Listing, Use
from .store import EvidenceStore


def demo(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    first = datetime.fromisoformat("2026-01-01T12:00:00+00:00")
    corrected = datetime.fromisoformat("2026-01-05T12:00:00+00:00")
    effective = datetime.fromisoformat("2025-01-01T00:00:00+00:00")
    with EvidenceStore(directory / "evidence.sqlite3") as store:
        store.register_source("synthetic-demo", DataOrigin.SYNTHETIC)
        store.set_permissions("synthetic-demo", known_at=effective, uses={Use.STORAGE, Use.RESEARCH})
        store.register_entity(Entity("demo-company", "Invented example company"))
        store.register_instrument(Instrument("demo-equity", "demo-company", AssetKind.EQUITY))
        store.register_listing(Listing("demo-old-listing", "demo-equity", "XNAS", "USD"))
        store.register_listing(Listing("demo-new-listing", "demo-equity", "XNYS", "USD"))
        old = store.ingest(source_id="synthetic-demo", record_id="listing-map", revision_id="1",
                           payload=b'{"listing":"demo-old-listing"}', published_at=first, received_at=first)
        new = store.ingest(source_id="synthetic-demo", record_id="listing-map", revision_id="2",
                           payload=b'{"listing":"demo-new-listing"}', published_at=first,
                           received_at=corrected, correction_of=old)
        for at, listing, evidence in [(first, "demo-old-listing", old), (corrected, "demo-new-listing", new)]:
            store.put_identifier(mapping_id="demo-map", provider="synthetic", value="DEMO",
                                 listing_id=listing, valid_from=effective, known_at=at, evidence_id=evidence)
        before = store.resolve_identifier("synthetic", "DEMO", effective_at=first, as_of=first)
        after = store.resolve_identifier("synthetic", "DEMO", effective_at=first, as_of=corrected)
        return {"origin": DataOrigin.SYNTHETIC.value, "before_correction": before,
                "after_correction": after, "counts": store.counts(),
                "training_implemented": False, "live_trading": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("demo", help="Run an invented offline evidence and identity example")
    command.add_argument("--out", type=Path, required=True)
    futures_command = commands.add_parser("futures-demo", help="Preview an invented futures opening intent offline")
    futures_command.add_argument("--out", type=Path, required=True)
    brokers_command = commands.add_parser("brokers-demo", help="Prepare two invented broker formats without sending orders")
    brokers_command.add_argument("--out", type=Path, required=True)
    import_command = commands.add_parser("reference-import-demo", help="Normalize invented broker responses into an immutable raw archive")
    import_command.add_argument("--out", type=Path, required=True)
    market = commands.add_parser("market-pipeline-demo", help="Stage invented vendor bars and report bounded replay gaps offline")
    market.add_argument("--out", type=Path, required=True)
    sync = commands.add_parser("alpaca-sync", help="Read paper account/assets only; requires configured source and account")
    for option in ("database", "connection-id", "account-number", "expected-account-id", "source-id", "import-id"):
        sync.add_argument("--" + option, required=True)
    args = parser.parse_args()
    if args.command == "alpaca-sync":
        import os
        from .alpaca_reader import AlpacaReferenceReader
        from .broker_imports import BrokerImportStore
        from .brokers import BrokerAccount, Environment
        from .contracts import ContractError
        key = os.environ.get("ALPACA_PAPER_API_KEY")
        secret = os.environ.get("ALPACA_PAPER_SECRET_KEY")
        if not key or not secret:
            parser.error("Configure ALPACA_PAPER_API_KEY and ALPACA_PAPER_SECRET_KEY in your local environment")
        try:
            route = BrokerAccount("alpaca", args.connection_id, args.account_number, Environment.PAPER)
            with BrokerImportStore(args.database) as store:
                imported = store.sync_alpaca(route, import_id=args.import_id, source_id=args.source_id,
                                             expected_native_id=args.expected_account_id,
                                             reader=AlpacaReferenceReader(key, secret))
            result = dict(import_id=imported["import_id"], state=imported["report"]["state"],
                          available_at=imported["available_at"], normalized_assets=len(imported["report"]["assets"]),
                          quarantined_rows=len(imported["report"]["quarantined"]),
                          training_ready=False, orders_sent=0, live_trading=False)
        except ContractError as error:
            parser.exit(2, f"Reference import rejected: {error}\n")
    elif args.command == "market-pipeline-demo":
        from .market_pipeline_demo import market_pipeline_demo
        result = market_pipeline_demo(args.out)
    elif args.command == "reference-import-demo":
        from .import_demo import reference_import_demo
        result = reference_import_demo(args.out)
    elif args.command == "brokers-demo":
        from .broker_demo import broker_demo
        result = broker_demo(args.out)
    elif args.command == "futures-demo":
        from .futures_demo import futures_demo
        result = futures_demo(args.out)
    else:
        result = demo(args.out)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
