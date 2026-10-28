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
    hedge_demo_parser = commands.add_parser("hedge-research-demo", help="Compare invented hedges and monitor partial/orphan exposure without orders")
    hedge_demo_parser.add_argument("--out", type=Path, required=True)
    for name in ("hedge-search", "hedge-monitor"):
        command = commands.add_parser(name, help="Evidence-backed hedge research; no broker transport")
        for option in ("database", "search-id", "evidence-id", "as-of"):
            command.add_argument("--" + option, required=True)
        command.add_argument("--opportunity-id" if name == "hedge-search" else "--monitor-id", required=True)
    opportunity_demo_parser = commands.add_parser("event-opportunity-demo", help="Compare invented event price scenarios and exposure without network or orders")
    opportunity_demo_parser.add_argument("--out", type=Path, required=True)
    opportunity = commands.add_parser("event-opportunity", help="Assess supplied evidence-backed price/cost/account sensitivity")
    for option in ("database", "assessment-id", "analysis-id", "evidence-id", "as-of"):
        opportunity.add_argument("--" + option, required=True)
    events_demo = commands.add_parser("event-intelligence-demo", help="Replay invented event revisions and facility context without network or orders")
    events_demo.add_argument("--out", type=Path, required=True)
    analysis_demo = commands.add_parser("event-analysis-demo", help="Run an invented scenario analysis through a mocked Responses transport; no network")
    analysis_demo.add_argument("--out", type=Path, required=True)
    analysis = commands.add_parser("event-analyze", help="Send a frozen event context to OpenAI for source-cited research scenarios")
    for option in ("database", "request-id", "analysis-id", "source-id", "event-id", "as-of", "expires-at", "model"):
        analysis.add_argument("--" + option, required=True)
    analysis.add_argument("--radius-km", type=float, required=True)
    analysis.add_argument("--max-output-tokens", type=int, default=4096)
    analysis.add_argument("--env-file", type=Path)
    analysis.add_argument("--external-processing-reviewed", action="store_true",
                          help="Confirm the selected sources permit sending this packet to the API")
    events_sync = commands.add_parser("event-sync", help="Capture one public USGS or GDACS feed into an explicitly configured source")
    for option in ("database", "source-id", "import-id"):
        events_sync.add_argument("--" + option, required=True)
    from .event_sources import EVENT_FEEDS
    events_sync.add_argument("--feed", choices=tuple(EVENT_FEEDS), required=True)
    event_context = commands.add_parser("event-context", help="Inspect dated facility proximity; geographic relevance does not establish damage")
    for option in ("database", "source-id", "event-id", "as-of"):
        event_context.add_argument("--" + option, required=True)
    event_context.add_argument("--radius-km", type=float, required=True)
    events_watch = commands.add_parser("event-watch", help="Continuously collect and produce evidence context; never submits orders")
    for option in ("database", "source-id"):
        events_watch.add_argument("--" + option, required=True)
    events_watch.add_argument("--feed", choices=tuple(EVENT_FEEDS), required=True)
    events_watch.add_argument("--out", type=Path, required=True)
    events_watch.add_argument("--radius-km", type=float, required=True)
    events_watch.add_argument("--poll-seconds", type=float, default=60)
    events_watch.add_argument("--iterations", type=int)
    command = commands.add_parser("demo", help="Run an invented offline evidence and identity example")
    command.add_argument("--out", type=Path, required=True)
    futures_command = commands.add_parser("futures-demo", help="Preview an invented futures opening intent offline")
    futures_command.add_argument("--out", type=Path, required=True)
    brokers_command = commands.add_parser("brokers-demo", help="Prepare two invented broker formats without sending orders")
    brokers_command.add_argument("--out", type=Path, required=True)
    import_command = commands.add_parser("reference-import-demo", help="Normalize invented broker responses into an immutable raw archive")
    import_command.add_argument("--out", type=Path, required=True)
    corporate = commands.add_parser("corporate-replay-demo", help="Replay invented split, dividend and symbol-rename proofs")
    corporate.add_argument("--out", type=Path, required=True)
    market = commands.add_parser("market-pipeline-demo", help="Stage invented vendor bars and report bounded replay gaps offline")
    market.add_argument("--out", type=Path, required=True)
    admission = commands.add_parser("admission-demo", help="Demonstrate synthetic calendar staging and fail-closed review gates")
    admission.add_argument("--out", type=Path, required=True)
    lean_demo = commands.add_parser("lean-readiness-demo", help="Run four synthetic LEAN readiness and baseline examples")
    lean_demo.add_argument("--out", type=Path, required=True)
    doctor = commands.add_parser("readiness", help="Read-only configuration/source/runtime diagnostic; never connects")
    doctor.add_argument("--database", type=Path)
    doctor.add_argument("--source-id", action="append", default=[])
    export = commands.add_parser("lean-export", help="Export a verified synthetic replay bundle; real dataset admission remains required")
    for option in ("database", "source-id", "listing-id", "dates-file", "as-of", "out"):
        export.add_argument("--" + option, required=True)
    foundations = commands.add_parser("research-foundations-demo", help="Demonstrate four synthetic source and learning foundations")
    foundations.add_argument("--out", type=Path, required=True)
    sec = commands.add_parser("sec-sync", help="Read a bounded public SEC submissions capture with identified contact")
    for option in ("database", "source-id", "import-id", "cik"):
        sec.add_argument("--" + option, required=True)
    prices = commands.add_parser("price-sync", help="Read bounded Alpaca raw daily bars; requires configured provider source")
    for option in ("database", "connection-id", "account-number", "source-id", "import-id", "start-date", "end-date", "symbol-listings"):
        prices.add_argument("--" + option, required=True)
    prices.add_argument("--feed", choices=("iex", "sip"), default="iex")
    prices.add_argument("--max-pages", type=int, default=10)
    calendar = commands.add_parser("calendar-sync", help="Read and stage bounded Alpaca paper Trading calendar; requires source configuration")
    for option in ("database", "connection-id", "account-number", "source-id", "import-id", "start-date", "end-date", "venue"):
        calendar.add_argument("--" + option, required=True)
    sync = commands.add_parser("alpaca-sync", help="Read paper account/assets only; requires configured source and account")
    for option in ("database", "connection-id", "account-number", "expected-account-id", "source-id", "import-id"):
        sync.add_argument("--" + option, required=True)
    args = parser.parse_args()
    if args.command == "hedge-research-demo":
        from .hedge_demo import hedge_demo
        result = hedge_demo(args.out)
    elif args.command in {"hedge-search", "hedge-monitor"}:
        from .hedge_research import HedgeResearchStore
        from .contracts import ContractError
        try:
            if not Path(args.database).is_file():
                raise ContractError("Existing evidence database required")
            with HedgeResearchStore(args.database) as store:
                cutoff = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
                if args.command == "hedge-search":
                    result = store.search(args.search_id, args.opportunity_id, args.evidence_id, as_of=cutoff)
                else:
                    result = store.monitor(args.monitor_id, args.search_id, args.evidence_id, as_of=cutoff)
        except (ContractError, OSError, ValueError) as error:
            parser.exit(2, f"Hedge research rejected: {error}\n")
    elif args.command == "event-opportunity-demo":
        from .event_opportunity_demo import opportunity_demo
        result = opportunity_demo(args.out)
    elif args.command == "event-opportunity":
        from .event_opportunity import EventOpportunityStore
        from .contracts import ContractError
        try:
            if not Path(args.database).is_file():
                raise ContractError("Existing evidence database required")
            with EventOpportunityStore(args.database) as store:
                result = store.assess(args.assessment_id, args.analysis_id, args.evidence_id,
                    as_of=datetime.fromisoformat(args.as_of.replace("Z", "+00:00")))
        except (ContractError, OSError, ValueError) as error:
            parser.exit(2, f"Event sensitivity rejected: {error}\n")
    elif args.command == "event-intelligence-demo":
        from .event_demo import event_demo
        result = event_demo(args.out)
    elif args.command == "event-analysis-demo":
        from .event_analysis_demo import event_analysis_demo
        result = event_analysis_demo(args.out)
    elif args.command == "event-analyze":
        from .contracts import ContractError
        from .event_analysis import EventAnalysisStore
        from .event_analysis_sync import analyze_event, analysis_code_version, openai_credential
        from .openai_event_reader import OpenAIEventReader
        try:
            if not Path(args.database).is_file():
                raise ContractError("An existing source-configured evidence database is required")
            if not args.external_processing_reviewed:
                raise ContractError("Review source rights for external processing before API dispatch")
            reader = OpenAIEventReader(openai_credential(args.env_file))
            with EventAnalysisStore(args.database) as store:
                result = analyze_event(store, request_id=args.request_id, analysis_id=args.analysis_id,
                    source_id=args.source_id, event_id=args.event_id,
                    as_of=datetime.fromisoformat(args.as_of.replace("Z", "+00:00")),
                    expires_at=datetime.fromisoformat(args.expires_at.replace("Z", "+00:00")),
                    radius_km=args.radius_km, model=args.model, code_version=analysis_code_version(),
                    reader=reader, max_output_tokens=args.max_output_tokens,
                    external_processing_reviewed=args.external_processing_reviewed)
        except (ContractError, OSError, ValueError) as error:
            parser.exit(2, f"Event analysis rejected: {error}\n")
    elif args.command in {"event-sync", "event-context", "event-watch"}:
        from .contracts import ContractError
        from .event_context import EventContextStore
        from .event_sources import UsgsEventReader
        from .event_sync import sync_events, watch_events
        try:
            if not Path(args.database).is_file():
                raise ContractError("An existing source-configured evidence database is required")
            with EventContextStore(args.database) as store:
                if args.command == "event-context":
                    cutoff = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
                    result = store.context(args.source_id, args.event_id, as_of=cutoff,
                                           radius_km=args.radius_km)
                else:
                    if args.feed == "gdacs":
                        from .gdacs_events import GdacsEventReader
                        reader = GdacsEventReader()
                    else:
                        reader = UsgsEventReader(args.feed)
                    if args.command == "event-sync":
                        result = sync_events(store, source_id=args.source_id, import_id=args.import_id,
                                             feed=args.feed, reader=reader)
                    else:
                        args.out.mkdir(parents=True, exist_ok=True)
                        for report in watch_events(store, source_id=args.source_id, feed=args.feed,
                                reader=reader, radius_km=args.radius_km,
                                poll_seconds=args.poll_seconds, iterations=args.iterations):
                            path = args.out/f"{report['run_id']}-{report['iteration']:06d}.json"
                            with path.open('x', encoding='utf-8') as output:
                                output.write(json.dumps(report, sort_keys=True, indent=2)+'\n')
                            summary = {key: report[key] for key in
                                ('status', 'source_id', 'feed', 'iteration', 'orders_sent', 'live_trading')}
                            summary['report_file'] = str(path)
                            print(json.dumps(summary, sort_keys=True), flush=True)
                        return
        except KeyboardInterrupt:
            parser.exit(130, "Event collection stopped; existing captures are preserved.\n")
        except (ContractError, OSError, ValueError) as error:
            parser.exit(2, f"Event operation rejected: {error}\n")
    elif args.command == "alpaca-sync":
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
    elif args.command == "lean-readiness-demo":
        from .lean_readiness_demo import lean_readiness_demo
        result = lean_readiness_demo(args.out)
    elif args.command == "readiness":
        from .readiness import diagnostic
        from .contracts import ContractError
        try:
            result = diagnostic(database=args.database, source_ids=args.source_id)
        except ContractError as error:
            parser.exit(2, f"Diagnostic rejected: {error}\n")
    elif args.command == "lean-export":
        from .lean_export import export_bundle
        from .market_data import MarketDataStore
        from .contracts import ContractError
        try:
            if not Path(args.database).is_file():
                raise ContractError("An existing evidence database is required")
            dates = json.loads(Path(args.dates_file).read_text())
            cutoff = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
            with MarketDataStore(args.database) as store:
                result = export_bundle(store, args.source_id, args.listing_id, dates,
                    as_of=cutoff, directory=Path(args.out))
        except (ContractError, OSError, ValueError) as error:
            parser.exit(2, f"Export rejected: {error}\n")
    elif args.command == "research-foundations-demo":
        from .research_foundations_demo import research_foundations_demo
        result = research_foundations_demo(args.out)
    elif args.command == "sec-sync":
        import os
        from .sec_filings import SecFilingsStore, SecSubmissionsReader, sync_sec
        from .contracts import ContractError
        contact = os.environ.get("SEC_USER_AGENT")
        if not contact:
            parser.error("Configure SEC_USER_AGENT with application name and contact locally")
        try:
            with SecFilingsStore(args.database) as store:
                result = sync_sec(store, source_id=args.source_id, import_id=args.import_id,
                    cik=args.cik, reader=SecSubmissionsReader(contact))
        except ContractError as error:
            parser.exit(2, f"SEC import rejected: {error}\n")
    elif args.command == "price-sync":
        import os
        from .alpaca_market import AlpacaMarketStore
        from .alpaca_price_reader import AlpacaPriceReader
        from .brokers import BrokerAccount, Environment
        from .price_sync import sync_prices
        from .contracts import ContractError
        key = os.environ.get("ALPACA_PAPER_API_KEY")
        secret = os.environ.get("ALPACA_PAPER_SECRET_KEY")
        if not key or not secret:
            parser.error("Configure ALPACA_PAPER_API_KEY and ALPACA_PAPER_SECRET_KEY locally")
        try:
            bindings = json.loads(Path(args.symbol_listings).read_text())
            route = BrokerAccount("alpaca", args.connection_id, args.account_number, Environment.PAPER)
            with AlpacaMarketStore(args.database) as store:
                result = sync_prices(store, source_id=args.source_id, import_id=args.import_id,
                    route=route, symbol_listings=bindings, start_date=args.start_date,
                    end_date=args.end_date, feed=args.feed, max_pages=args.max_pages,
                    reader=AlpacaPriceReader(route, key, secret))
        except (ContractError, OSError, ValueError) as error:
            parser.exit(2, f"Price import rejected: {error}\n")
    elif args.command == "admission-demo":
        from .admission_demo import admission_demo
        result = admission_demo(args.out)
    elif args.command == "calendar-sync":
        import os
        from .alpaca_calendar import AlpacaCalendarStore
        from .alpaca_calendar_reader import AlpacaCalendarReader
        from .brokers import BrokerAccount, Environment
        from .calendar_sync import sync_calendar
        from .contracts import ContractError
        key = os.environ.get("ALPACA_PAPER_API_KEY")
        secret = os.environ.get("ALPACA_PAPER_SECRET_KEY")
        if not key or not secret:
            parser.error("Configure ALPACA_PAPER_API_KEY and ALPACA_PAPER_SECRET_KEY locally")
        try:
            route = BrokerAccount("alpaca", args.connection_id, args.account_number, Environment.PAPER)
            with AlpacaCalendarStore(args.database) as store:
                captured = sync_calendar(store, source_id=args.source_id, import_id=args.import_id,
                    route=route, start_date=args.start_date, end_date=args.end_date, venue=args.venue,
                    reader=AlpacaCalendarReader(route, key, secret))
            result = dict(import_id=captured["import_id"], candidates=len(captured["candidates"]),
                quarantined_rows=len(captured["quarantined"]), available_at=captured["available_at"],
                capture_origin=captured["capture_origin"], authenticated_account_verified=False,
                calendar_complete=False, training_ready=False, live_trading=False, orders_sent=0)
        except ContractError as error:
            parser.exit(2, f"Calendar import rejected: {error}\n")
    elif args.command == "corporate-replay-demo":
        from .corporate_demo import corporate_demo
        result = corporate_demo(args.out)
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
    print(json.dumps(result, indent=2, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
