# Rebuild status

Date: 2026-10-20. Masterplan: 1.3. Package: 0.5.0.

## Reset completed

PR #10 merged the reviewed clean planning foundation into `main`, replacing the prior Collective2 application. The recovery point remains:

- Repository: heke99/trading-intelligence
- Previous default-branch commit: `8c5056112721345540ea1cfbbca1f4c41fa816e8`
- Archive branch: `archive/collective2-v0.1-before-equities-2026-10-20`
- Reset merge commit: `b8537c234eacebfd1156ca432739e308b5d9de46`

Parent history is preserved. Original exports, external databases and accounts were outside the cleanup scope.

## First implementation slice

The Python package implements explicit issuer/instrument/listing contracts, exact historical listing mappings, versioned original-byte evidence, correction references, repeatable ingestion and default-denied declared source uses. The CLI demonstrates one synthetic correction in an offline SQLite store. See [contract details](FOUNDATION.md).

This is partial Phase 1. It does not complete the masterplan's data ingestion or replay acceptance requirements.

PR #11 merged this foundation into main at `96c79fac1ea517804684b90298c58b80b95d831a`.

## Futures and supplied session snapshots

Masterplan 1.2 adds futures as a separate flow. The additive code implements products and expiry identities; evidence-backed terms, sessions, broker bindings and account margins; exact tick/PnL/notional calculations; and a single-opening-intent preview. It supports linear fixed-tick cash-settled opening scenarios. Physical contracts need an explicit notice boundary to be represented, and physical openings remain blocked. See [FUTURES.md](FUTURES.md).

This does not implement contract selection, rolling, daily/final settlement accounting, aggregate risk, a market feed or broker execution. Session segments are synthetic supplied fixtures, not imported exchange calendars. Merge and remote verification evidence are recorded in the associated PR.

## Multi-broker preparation

PR #12 passed remote CI and was merged into main at ff7601cc42b62e4555e20411f35fff2710fc0601. The next slice introduces canonical order intents and broker/connection/account/environment namespaces, evidence-backed account capability and instrument snapshots, two invented offline adapter formats, and persistent idempotent drafts. A retry retrieves the original draft rather than rebuilding a changed request or failing over to another broker.

The temporal reference implementation is now shared between futures and brokers without changing existing futures tables or snapshot identities. Real broker transport, credentials, execution, account risk and reconciliation remain unimplemented. See [BROKERS.md](BROKERS.md).

## Read-only broker reference import

PR #13 passed remote CI and merged into main at bda750c7b47ae0aaea8977935697f87c79b3b2c7. This new slice adds an Alpaca paper account/assets GET reader, strict field normalization, raw-response archive, receipt and post-processing availability, immutable import batches and CLI configuration. It has no authenticated-account verification and no orders/positions/fills transport. Supplied/local records and real GET captures are distinguished by endpoint provenance. See [BROKER_IMPORTS.md](BROKER_IMPORTS.md).

Unknown fields remain unknown. Wrong account identity, malformed rows and ambiguous assets are quarantined. No canonical binding, account trading capability or training approval is inferred. Provider publication/economic time remains null instead of being fabricated from receipt. A failed partial fetch publishes no complete batch; durable failed-attempt journaling remains future work.

## Capability status

| Capability | Status |
| --- | --- |
| Masterplan, analysis scope and build sequence | Documented |
| Issuer, share-class/instrument and equity/ETF listing contracts | Implemented locally |
| Versioned raw evidence and historical identifier queries | Implemented locally |
| Declared storage/research/training permissions | Implemented as metadata; independent entitlement review required |
| Offline synthetic correction demo | Implemented and checked |
| Futures identities and dated reference snapshots | Implemented offline |
| Futures tick/PnL/notional and opening-intent checks | Implemented offline; no live authorization |
| Supplied session segments, breaks and overnight instants | Implemented offline |
| Authoritative exchange calendars and corporate actions | Not imported or implemented |
| Futures roll, daily/final settlement and aggregate margin engine | Not implemented |
| Multi-broker canonical intents, account isolation and persisted drafts | Implemented offline |
| Two synthetic broker format encoders and explicit adapter registry | Implemented offline; no external connection |
| Alpaca paper reference GET reader and vendor-field normalization | Implemented; authenticated API access not verified |
| Raw response archive, processed availability and immutable reference batches | Implemented and tested with synthetic responses |
| Real order transport, positions/fill reconciliation and second vendor reader | Not implemented |
| SEC, price, news and NAV adapters | Not implemented |
| Real equity/fund data entitlement | Not verified |
| Trader-history completeness or verification | Not implemented or verified |
| New datasets approved for training | None |
| AI analysis, forecasts, labels and self-learning | Not implemented |
| Backtesting and strategy profitability | Not implemented or established |
| UI, broker or fund order adapters | Not implemented |
| Simulated or live orders | Not executed |

## Verification

158 offline synthetic regression tests passed locally on Python 3.12.14, including all 115 previous foundation/futures/broker tests. New tests cover HTTP endpoint/method limits, headers/redirect failures, account identity, unknown flags/values, decimal normalization, malformed/duplicate JSON, quarantine, processed availability, import retries/restarts, permissions, partial fetch and integrity failures. Broker cases cover per-account isolation, strict capabilities, native mapping, raw prices/lots, stale/missing references, stable retries, changed-input conflicts, restart persistence, live-route rejection and corrupt archives. New cases cover expiry identity, fixed-tick Decimal calculations, raw/adjusted prices, temporal corrections, missing/expired margin, account/currency mismatch, physical exclusion, limits, session breaks, overnight/DST instants, overlapping references and corruption. Existing cash databases remain readable with the additive futures tables.

The original foundation, futures and multi-broker slices passed remote CI on Python 3.11, 3.12 and 3.13. The reference-import slice defines the same matrix with all four offline CLI examples; check its associated PR for remote results. Tests do not establish investment performance or end-to-end production readiness.

## Next milestones and acceptance

1. Add authoritative calendar/reference imports, broker-capability data, processing-availability timestamps, immutable receipt observations and a SEC adapter with synthetic replay fixtures. First real ingestion remains gated on source terms and operational configuration.
2. Select a market-data feed against coverage, timestamps, corporate actions, delisted securities and storage rights. Add price/news adapters, raw futures-expiry data and a separate NAV contract. Do not assume that public access permits model training.
3. Demonstrate split, rename, article-revision and timezone replay. For futures, add contract-level fees, margin reservation, roll legs, variation/final settlement and aggregate exposure. Add artifact dependencies, an outcome queue and incident lineage before the first model.
4. Implement source-backed analysis and simple frozen strategy baselines; then evaluate chronologically with costs before introducing candidate learning.
5. Add shadow/paper operation, portfolio risk and reconciliation. Live trading requires the separate scope and evidence in the masterplan.

Masterplan 1.3's learning cycle, incident categories, adaptive evaluation, model-promotion bounds and state-preserving rollback remain requirements for those later phases.
