# Supplied vendor captures and bounded daily replay

This Phase 1b delivery adds offline Alpaca-format capture staging, durable quarantine and multi-day replay manifests. It does not establish authenticated access, source entitlement, authoritative calendar coverage or a completed research dataset.

## Vendor capture staging

`AlpacaMarketStore.import_bars(...)` archives one supplied multi-symbol Alpaca daily-bars response page. Provide source/import IDs, original response bytes, receipt and processing-completion times, explicit symbol-to-listing bindings and declared request configuration: raw `1Day`, IEX or SIP feed, market timezone and request currency (default USD). Register source, permissions and listing identities first. Request declarations are not proof that a request was made or a feed entitlement exists.

Numbers are parsed using exact decimals. Valid rows become staged candidates; malformed JSON, ambiguous same-day rows, unmapped symbols and invalid OHLC/numeric fields are recorded in an immutable quarantine journal. The same import ID cannot be reused with changed bytes or configuration. Raw bytes, request metadata, candidates and quarantine are committed together; imports reject existing caller transactions rather than committing unrelated writes. A failed operational write has no complete capture result.

`capture_as_of(source_id, import_id, as_of=...)` exposes captures only after processing completion and verifies hashes of the raw payload and result manifest plus the quarantine journal. A later correction is a new capture/import ID; no automatic vendor revision ordering or merging across pages is implemented.

The provider bar timestamp is preserved as `provider_timestamp_raw` and a normalized instant. It is **not** a publication time or an equity session boundary. Candidate `published_at`, `session_start` and `session_end` remain unknown. The adapter does not insert market snapshots or fabricate evidence publication dates. Explicit listing bindings are caller assertions; historical symbol/as-of mapping and full exchange session coverage still require admission review.

A missing next-page token means unknown pagination status. A nonempty token means more pages. A terminal token describes only that supplied page; `page_complete` means no parse/quarantine issues on a terminal page. It does not certify requested-date coverage, a full response chain, historical completeness or training readiness. No transport, pagination fetcher, calendar reader, credential handling or order endpoint is added.

## Multi-day replay

`replay_dates(store, source_id, listing_id, expected_dates, as_of=...)` requires an explicit, unique, increasing list of canonical ISO dates. It does not generate business days or infer exchange holidays. Existing normalized records follow [MARKET_DATA.md](MARKET_DATA.md).

For each date, missing known sessions or bars are named in a gap report. Missing data never becomes a zero price or return. Ambiguous effective starts, mismatched sessions, invalid action dates, missing permissions and integrity failures block replay instead of becoming ordinary gaps. Known snapshots are verified even if another required record is missing. Reads share a SQLite savepoint snapshot and do not commit the caller's transaction.

The manifest records its cutoff, requested dates, listing/source, snapshot/evidence IDs, raw and normalized hashes and gaps. Its SHA-256 is reproducible for the same stored snapshots and configuration, including after restart. `complete_scope` covers only the supplied dates and known session/bar availability. It does not prove that dates were not omitted, that actions are complete or that data are historically admissible. Training, full-history and live flags remain false.

## Runnable synthetic demonstration

```bash
PYTHONPATH=src python3 -m trading_intelligence market-pipeline-demo --out data/market-demo
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The repeatable demonstration stages an invented vendor-shaped valid row with unknown publication/session data and quarantines an invalid row. Separately labelled normalized fixtures replay two of three explicit dates; the middle date appears as a gap. No staged candidate is promoted by inventing its missing timestamps. The ignored output directory contains a SQLite database and report.json. CI runs the same demonstration on Python 3.11–3.13.

## Evidence and remaining work

All added regression cases use synthetic fixtures. Tests cover receipt/processing visibility, restart/idempotence, input conflicts, permissions, raw/result/quarantine corruption, strict decimal/OHLC parsing, ambiguous rows, pagination uncertainty, gap reporting, late corrections, deterministic manifests and transaction isolation. An existing input validation defect in `MarketDataStore` was fixed so structured kind/listing values raise a contract error instead of leaking TypeError or SQLite binding errors.

Authoritative calendar import, transport and authenticated account checks, current data entitlements, historical symbol/universe admission, revisions/cancellations across captures, corporate-action accounting and multi-day rename/delisting acceptance remain pending. No model, LEAN baseline, trading performance or live readiness is claimed. Before any predictive model, artifact dependencies, outcome queues and incident lineage remain required.

Official references consulted for field/request semantics:

- Alpaca historical stock bars: https://docs.alpaca.markets/us/reference/stockbars
- Alpaca calendar API documentation: https://alpaca.markets/sdks/python/api_reference/trading/calendar.html
- Alpaca historical market data field description: https://github.com/alpacahq/bkdocs/blob/master/content/market-data/historical.md
