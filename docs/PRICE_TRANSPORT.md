# Bounded Alpaca daily-price capture

`AlpacaPriceReader` exposes only `GET https://data.alpaca.markets/v2/stocks/bars`. It requires an explicit Alpaca paper route and runtime keys. A route labels a request; neither a bars response nor these tests verifies which account owns the credentials. No account edits or orders are available.

`read(symbols, start_date, end_date, feed='iex', page_token=None, limit=1000, max_bytes=2000000)` accepts 1–50 unique supported uppercase symbols, canonical inclusive date bounds spanning at most 366 New York calendar dates, and IEX or SIP. It sends explicit `timeframe=1Day`, `adjustment=raw`, `asof=-`, `currency=USD`, `sort=asc` and a bounded integer limit. `asof=-` disables Alpaca's implicit historical symbol remapping; the caller still needs verified identity evidence for its explicit bindings. The date bounds are encoded as the full inclusive New York local days in UTC, preserving DST. They are query windows, not a claim about the exact session included by a provider aggregate.

Responses must be bounded, nonempty, uncompressed JSON from the exact requested URL with status 200. Redirects are blocked; HTTP/network errors omit provider details and credentials. Byte, symbol, date, timeout and token bounds are enforced. No retries or alternative endpoints occur inside the reader.

## Durable orchestration

`sync_prices(store, source_id=..., import_id=..., route=..., symbol_listings=..., start_date=..., end_date=..., feed=..., reader=..., clock=None, max_pages=10, max_total_bytes=20000000, page_limit=1000)` requires an explicitly declared provider source, storage/research permissions and USD listing bindings. It stages each original response through the existing `import_bars`. A wrapper journal preserves each page's endpoint/query/route, raw hash, capture ID, processing availability and pagination token. Provider publication remains unknown. Nothing is promoted into market snapshots or training.

Request, page and terminal-result journals are immutable and hash checked. A terminal retry with unchanged configuration returns its existing report without refetching, including an incomplete/failed report. Changed configuration under the same ID conflicts. A previously interrupted job lacking a terminal report is marked incomplete on retry; use a new explicit import ID to make another bounded network attempt. Raw pages already archived remain available for diagnosis. If a process is interrupted after a raw page was captured but before its wrapper journal was saved, that capture remains in the capture archive and is not claimed as a verified page of the completed report.

Only an explicit null terminal token completes pagination. A missing token, repeated token, page or byte limit, request failure, invalid/quarantined row, out-of-range record or duplicate listing/date across pages produces an incomplete/quarantined report. Partial failures retain earlier raw pages and their journals. Oversized HTTP responses are rejected at the byte boundary; a full oversized original response cannot be archived by this bounded reader. Completion of pagination says nothing about missing sessions, delistings, feed coverage, historical availability or model-training rights.

The sync function requires an idle database connection and never commits a caller transaction. It does not claim an atomic external download: each completed page is durable independently. Maximums are 100 pages and 200 MB total; defaults are 10 pages and 20 MB. Errors are not automatically retried.

## Synthetic demonstration

The runnable helper `trading_intelligence.price_demo.price_demo(directory)` uses injected two-page GET responses and a source explicitly labelled `synthetic_fixture`. It calls the reader and raw staging importer directly, without pretending that the invented responses came from a real provider connection. It writes a local database and `price-report.json`, and produces the same report on rerun.

```python
from trading_intelligence.price_demo import price_demo
price_demo('data/price-demo')
```

Tests exercise fixed GET routing, credentials/error redaction, DST date bounds, token encoding, HTTP/media/redirect/byte failures, durable partial downloads, restart/idempotence, interruption, request conflicts, malformed payload quarantine, token cycles, missing tokens, scope violations and cross-page duplicates. Tests and injected demos establish local behavior only. No authenticated market feed has been exercised in this delivery.

Official reference checked 25 October 2026: https://docs.alpaca.markets/us/reference/stockbars . The reference documents raw adjustment, pagination, feed choices, explicit currency and `asof` symbol mapping. The bounds, journal policy and admission separation above are our implementation choices.

## Configured CLI

Create the provider source, declared permissions and canonical USD listings through the existing store API first. Supply a JSON object mapping each requested exact symbol to its listing ID in a local file. Configure `ALPACA_PAPER_API_KEY` and `ALPACA_PAPER_SECRET_KEY` locally, then run:

```sh
PYTHONPATH=src python -m trading_intelligence price-sync \
  --database /path/to/research.sqlite3 --connection-id configured-paper \
  --account-number configured-account --source-id configured-provider \
  --import-id bounded-prices-001 --start-date 2026-01-05 --end-date 2026-01-07 \
  --symbol-listings /path/to/symbol-listings.json --feed iex --max-pages 10
```

An import report can be incomplete while the command itself successfully preserves diagnostic evidence. Inspect `state`, `reason` and `pages_complete`; even `complete_pages` never means historical dataset admission. Credentials are environment values, never command arguments or report fields.
