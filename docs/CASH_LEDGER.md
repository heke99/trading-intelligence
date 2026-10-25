# Offline cash and position journal

`CashLedgerStore` records supplied hypothetical equity-style accounting events. It generates no fills, dispatches no orders and does not provide authoritative broker state. Both supported origins (`synthetic_fixture`, `externally_supplied_simulation`) remain simulated. Nothing in this journal establishes profitability, source correctness, LEAN execution or training readiness.

One database supports one explicit three-letter currency and one origin. The first event is `opening_cash`; later events are `buy`, `sell`, `split` and `dividend`. Buys subtract quantity × price plus fee; sells add quantity × price minus fee. Splits change held quantity only; a dividend's supplied amount is **total cash**, not an inferred per-share entitlement. No shorts, negative cash, FX, fund NAV execution, futures margin, tax lots, cost basis, settlement, withholding, fractional cash-in-lieu or portfolio valuation is implemented. Unsupported cases fail. Use a fresh reviewed journal for corrections; correction fields and arbitrary cash adjustments are rejected. Old events cannot be deleted or silently overwritten through this API.

Every event requires immutable `event_id`, `source_ref`, `origin`, `currency`, timezone-aware `occurred_at` and `observed_at`. Observation cannot precede occurrence or exceed the registration clock. Economic events must be appended in chronological order; delayed earlier events require a separate reconstruction rather than rewriting this journal. Registration time is sampled from the operational clock, distinct from supplied event/observation times; historical `state(as_of=...)` includes only events registered by that cutoff. No timestamp proves external publication, action entitlement or provider access.

All monetary amounts, fees and quantities are finite nonnegative decimal **strings**, with positive quantities/prices/split ratios, at most 18 fractional places and bounded magnitude. Decimal calculation avoids binary floats. Nonterminating or out-of-bounds split quantities fail. Fees must be explicit, including `"0"`. IDs bind canonical event bytes, registration time and append sequence to SHA-256. Reads require contiguous sequences and monotonic registration times; writes reject a registration clock earlier than the last stored registration. Identical retries survive restart; changed content under an existing ID fails. Reads check stored hashes. These are local integrity checks, not a tamperproof log against a database administrator who can recompute hashes.

## Declared report adapter

`import_declared_report(payload: bytes)` accepts this exact versioned UTF-8 JSON envelope, atomically, with bounded byte/event counts and duplicate-field rejection:

```json
{"format":"offline-cash-events-v1","events":[{"event_id":"opening","kind":"opening_cash","occurred_at":"2026-01-01T00:00:00Z","observed_at":"2026-01-01T01:00:00Z","currency":"USD","origin":"externally_supplied_simulation","source_ref":"my-offline-report:1","amount":"1000"}]}
```

A LEAN report exporter can map its externally generated simulated fills into this contract and supply immutable instrument IDs plus explicit `quantity`, `price`, `fee` fields for `buy`/`sell`. The importer does **not** parse or claim compatibility with native LEAN report schemas. Splits require `instrument_id`, `numerator`, `denominator`; dividends require `instrument_id`, `amount`. Original exporter bytes/provenance need their own evidence capture: this ledger preserves canonical accepted event bodies, not the original report envelope. Source references are caller declarations, not evidence verification or automatic baseline-intent matching. No engine package is installed or invoked.

## Comparison and example

`reconcile(expected_currency=..., expected_cash="...", expected_positions={instrument_id:"quantity"}, cash_tolerance="...", quantity_tolerance="...")` compares the current journal with an explicitly supplied external snapshot. Both tolerances are mandatory decimal strings. Missing instruments count as zero; extra positions fail outside tolerance. Currency disagreement and cash/position mismatches raise `ContractError`. A matching report is a numerical comparison of supplied values, not independent broker reconciliation or acceptance of its source. Reports are returned, not persisted as authoritative snapshots.

`cash_ledger_demo(directory)` imports synthetic opening cash, buy with fee, split and dividend; reopens/retries the journal; checks cash `803` and quantity `4`; demonstrates changed-ID-content and reconciliation failures. Its result explicitly retains synthetic origin, `orders_sent=0`, `lean_executed=False`, `broker_verified=False`.

Verification: `PYTHONPATH=src python3 -m unittest discover -s tests -p test_cash_ledger.py -q`. Tests cover restart, immutability, fees/splits/dividends/sells, precision, chronology, origin isolation, negative cash/short rejection, atomic imports, currency/tolerance comparisons, registration cutoffs, caller transactions and corruption detection, backwards-clock writes and same-time event reordering. Synthetic tests are not real broker/data quality evidence.
