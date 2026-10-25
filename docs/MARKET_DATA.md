# Normalized daily market record foundation

This Phase 1b slice adds `MarketDataStore` on top of the existing evidence store. It imports **one supplied normalized JSON record per original payload**, retaining raw bytes, revision/correction lineage, explicit listing identity and separate publication, receipt and processing-completion times. It has no vendor transport and does not certify exchange calendars, historical availability or data rights.

Supported kinds are `session`, `bar`, `split` and `cash_dividend`. All records have exactly these keys:

```json
{"kind":"bar","listing_id":"explicit-listing","date":"2026-01-05","start":"2026-01-05T14:30:00Z","end":"2026-01-05T21:00:00Z","currency":"USD","values":{"open":"100","high":"105","low":"95","close":"102","volume":"50","price_kind":"raw"}}
```

The values and session dates above are invented fixtures, not actual exchange reference data. Dates label an explicit trading day. All timestamps must include offsets. Numeric values are decimal strings; floating-point JSON numbers, NaN, negative volume and inconsistent OHLC bounds are rejected. A completed bar cannot be published before its interval ends. Adjusted bars cannot masquerade as raw prices.

| Kind | Exact `values` keys | Limits |
| --- | --- | --- |
| session | timezone | Valid IANA zone; one contiguous daytime equity session; supplied open/close on the declared local date |
| bar | open, high, low, close, volume, price_kind | Raw positive OHLC; bar interval must match the session during replay |
| split | new_shares, old_shares | Positive explicit ratio; no automatic price/quantity adjustment |
| cash_dividend | amount, payment_date | Nonnegative amount in listing currency; payment not before declared ex-date |

`import_record` accepts source/record/revision IDs, original bytes, publication/receipt/processing times and optional `correction_of` evidence ID. Register the entity, equity/ETF listing, source origin and storage/research permissions using existing APIs first. Successful import returns a snapshot ID; `market_snapshots` retains its backing evidence ID. Keep record IDs stable across revisions. Corrections must retain kind, listing, date and effective start, refer to the earlier same source record and become available after the predecessor. Changing identity or moving an effective start requires separate future cancellation/supersession semantics and is not supported here. Retries reuse the snapshot; changing processing availability is rejected.

`replay_day(source_id, listing_id, trading_date, as_of=...)` requires both a session and a completed bar available by the cutoff. It returns their evidence-backed snapshots and any known same-day supported actions. Revisions imported later do not change earlier replay. A missing day/session is an explicit error, never a zero return or invented holiday. No fallback between sources or symbol guessing occurs. Multiple effective starts for the same kind/day block replay as ambiguous.

Replay verifies raw and snapshot hashes and research-use declarations at the requested cutoff. As in the existing prototype, these declarations are metadata, not independent entitlement verification. Historical replay must not be used to bypass current license revocation in production. SQLite direct writes can bypass append-only APIs; this is not a tamper-proof access boundary.

## What this slice does not establish

- It is not a complete price feed, authoritative calendar importer or production ingestion service. Processing timestamps remain caller assertions; a production adapter needs a trusted operational clock and durable observations.
- There is no batch completeness guarantee. A failed snapshot write can leave raw evidence for diagnosis. Invalid payloads raise errors; a durable quarantine/job journal is still needed.
- No source data has been admitted for training. All added tests are synthetic. Successful import is not evidence of complete, licensed or historically available data.
- Split/dividend records are versioned observations only. Ex-date entitlement, payment booking, price adjustment, portfolio quantities, total returns and double-count prevention in a cash ledger remain future work. Multiple distributions of the same kind on a single day and cancellations are not supported.
- Name changes continue to use the existing temporal identifier mechanism. This module does not import corporate reorganizations, delistings or historical membership.
- Intraday bars, overnight/multi-segment sessions, fund NAV orders, futures data/settlement, LEAN, strategy simulation, human journals, hedging and live orders are not implemented by this slice.

## Verification

Run `PYTHONPATH=src python3 -m unittest discover -s tests -v`. The new tests cover processing availability, late corrections, processing-order reversal, restart/idempotence, split/dividend preservation of raw prices, gaps, mismatched sessions, decimal/OHLC validation, invalid identity/currency/timezone, naive timestamps, duplicate JSON keys, revoked research permission and raw/snapshot corruption. Session tests use explicit winter/summer offsets, not a hardcoded UTC opening hour. These tests verify local contracts, not market performance or exchange accuracy.

Next: select/admit a data source, add vendor normalization and durable quarantine, import authoritative dated calendars and corporate actions, and verify a bounded multi-day replay with gaps, rename and delisting cases. Only an admitted data slice can support the first LEAN baseline.
