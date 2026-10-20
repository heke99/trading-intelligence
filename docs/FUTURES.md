# Futures foundation 0.3.0

Masterplan 1.2 includes futures as a separate asset flow. This delivery implements reference contracts and an offline single-opening-intent preview. It does not place orders or simulate fills.

## Implemented contracts

| Object | Responsibility |
| --- | --- |
| FutureProduct | Product root, venue MIC, underlying instrument, quote/PnL currency and explicit price unit |
| FutureContract | Immutable expiry identity and YYYY-MM contract month; no inferred last-trade date |
| FutureTerms | Fixed tick/multiplier, settlement type, exact last-trade/entry-cutoff instants, notice boundary, explicit negative-price support |
| TradingSchedule | Ordered absolute-time session segments and source IANA timezone; empty schedule means closed |
| FuturesMargin | Full initial/maintenance requirements, keyed by broker/account/contract |
| CollateralSnapshot | Caller-declared available collateral, currency, observation and expiry |
| FuturesResearchLimits | Per-intent quantity/notional limits, margin buffer and explicit short permission |
| FuturesPreview | Scenario calculation with the four reference snapshot IDs and live_trading=false |

Cash securities retain their entity/instrument/listing model. Futures use separate products and expiry contracts rather than inventing an issuer/share class. A product references the underlying cash/index instrument. Instrument(kind=FUTURE) is rejected in favor of FutureContract. Exact broker bindings reference an explicit expiry and broker contract ID. Roots and continuous series have no inferred executable mapping; actual broker identity and eligibility still require independent verification.

Multiple products can reference one index, so micro/standard size cannot be guessed from the underlying name. The multiplier is quote-currency units per one price-unit movement for one contract. Only linear, fixed-multiplier, fixed-tick products with quote and PnL currency equal fit this model. Options, perpetuals, inverse contracts, variable tick tables and special bond/rate quote conventions are unsupported.

## Historical snapshots and storage

FuturesStore extends EvidenceStore through additive tables only. Opening an existing 0.2 database preserves cash-asset records. No external database migration or service is run.

Terms, schedules, broker bindings and margins carry valid_from, exclusive valid_to, known_at and backing evidence. Knowledge time cannot precede evidence receipt. Reads verify the normalized snapshot hash and raw evidence hash, and check declared research permission at the cutoff.

For each kind/target/valid-from interval, later-known versions are corrections. Retrieval picks the latest version known at the cutoff for each interval, then requires exactly one interval covering the economic instant. Missing, expired or overlapping snapshots block the preview. New effective intervals require shortening the previous interval through a versioned correction. There is no arbitrary overlap winner or stale fallback.

Source times, classifications and fields are caller assertions. They require trusted operational receipt/processing logs and independent data admission before production use. Hashes are integrity checks, not a security boundary against direct database editing. Historical rights metadata does not replace enforcement of current entitlements.

## Preview behavior

The opening-intent preview checks whole signed quantity, raw-price declaration, matching fresh collateral, exact broker binding, usable terms, entry/last-trade boundary, cash settlement, tick grid, negative-price permission, session state, current margin snapshot, currency compatibility, short permission and per-intent quantity/notional/collateral limits.

Tick value is tick_size times multiplier. Gross mark-to-mark PnL is (exit minus entry) times multiplier times signed quantity. Notional is the absolute value of price times multiplier times quantity. Initial margin is the per-contract full requirement times absolute quantity times the configured buffer. Maintenance is reported separately. Decimal inputs and bounded high-precision calculations avoid float rounding; off-grid prices are rejected. Gross PnL excludes fees, slippage, FX and settlement cash flows.

A preview has no position book, pending orders, collateral reservations, validated live quote, aggregate risk, stress model, account eligibility, broker-owner lease or send API. Price and collateral are caller inputs. Passing it never authorizes a live order. Repeated previews do not reserve capital. No SPAN or portfolio-offset calculation exists. Zero/negative prices also require independent production stress/exposure controls because notional alone is insufficient.

Entry cutoff applies to new opening previews. This function must not gate exits, reducing orders, cancellations or late broker events. Physical contracts need an explicit notice boundary to be represented but all physical openings are excluded from this pilot. Rollover planning/legs, daily variation margin, final settlement and delivery handling are unimplemented.

## Session limits

UTC instants are compared in half-open intervals. Segments can span midnight, represent an early close or holiday and leave maintenance gaps. The timezone label does not generate a calendar. This delivery does not download authoritative exchange sessions, assign exchange trading dates, parse ambiguous/nonexistent local source timestamps or verify calendar completeness. Real adapters must preserve offsets and prove coverage. DST tests compare explicit instants, including both folds of a repeated hour.

The demo contract, venue, margin, dates and sessions are invented. They are not current MNQ/NQ settings or a feed. No licensed data or private trader exports are committed.

```bash
PYTHONPATH=src python3 -m trading_intelligence futures-demo --out data/futures-demo
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Next implementation

1. Import authoritative dated contract/session and broker-capability data, with processing availability and current entitlement controls.
2. Add licensed raw expiry-contract market snapshots and quality checks. Feed and broker selection remain explicit decisions.
3. Build deterministic replay, fees, margin reservation, variation/final settlement and separate roll legs with aggregate positions and pending orders.
4. Verify partial fills, failed second roll leg, restart and reconciliation in paper mode before a separately configured live pilot.

## Primary references reviewed 20 October 2026

These inform the design. No upstream source code was copied.

- [CME MNQ properties](https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html)
- [CME expiration and roll](https://www.cmegroup.com/education/courses/introduction-to-futures/understanding-futures-expiration-contract-roll)
- [CME margins](https://www.cmegroup.com/solutions/risk-management/performance-bonds-margins.html)
- [CME delivery](https://www.cmegroup.com/articles/brochures-and-handbooks/101-overview-delivery.html)
- [LEAN futures data and symbol changes](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/futures/handling-data)
