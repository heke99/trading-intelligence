# Rebuild status

Documentation updated: 2026-10-25. Masterplan: 1.4. Package: 0.5.0.

The implementation and verification evidence below remains the recorded 2026-10-20 Phase 1 state. The 2026-10-25 change updates planning documents only; it does not add runtime functionality, verify authenticated access or report a new test run.

## Masterplan 1.4 changes

- Require an immutable pre-outcome journal of human hypotheses/interventions, linked to the original model proposal, actor, rationale, sources, decision time and expiry. Compare model-only and model-plus-human contributions on the same opportunities, risk and costs.
- Define exposure-linked hedge policies with residual-risk targets, instrument selection, rebalancing, expiry/exit rules and dedicated mandates. Track the protected exposure and hedge together through partial fills, rejected legs, sales and rolls; instrument reduce_only is distinct from reduced portfolio risk and does not authorize a new hedge or bypass a stop.
- Evaluate unhedged portfolio, hedge and combination separately, including costs, remaining risk, simultaneous adverse moves, higher margin requirements and account-specific cash needs.
- Put a frozen simple numerical baseline and LEAN replay in Phase 2, futures settlement/hedge simulation in Phase 3, and larger source-backed AI/human/graph comparisons in Phase 4. LEAN remains the first engine trial, with NautilusTrader an alternative and Qlib a later research option.
- Retain artifact dependencies, outcome definitions/queue and incident lineage before predictive model training. All new human/hedge requirements remain unimplemented.

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
| Pre-outcome human decision journal and intervention attribution | Required by masterplan 1.4; not implemented |
| Exposure-linked hedge policy, lifecycle and risk/result attribution | Required by masterplan 1.4; not implemented |
| Frozen numerical baseline and LEAN replay | Planned Phase 2; not implemented |
| Backtesting and strategy profitability | Not implemented or established |
| UI, broker or fund order adapters | Not implemented |
| Simulated or live orders | Not executed |

## Verification

The 2026-10-20 record reports 158 offline synthetic regression tests passing locally on Python 3.12.14, including all 115 previous foundation/futures/broker tests. That earlier suite covers HTTP endpoint/method limits, headers/redirect failures, account identity, unknown flags/values, decimal normalization, malformed/duplicate JSON, quarantine, processed availability, import retries/restarts, permissions, partial fetch and integrity failures. Broker cases cover per-account isolation, strict capabilities, native mapping, raw prices/lots, stale/missing references, stable retries, changed-input conflicts, restart persistence, live-route rejection and corrupt archives. Futures cases cover expiry identity, fixed-tick Decimal calculations, raw/adjusted prices, temporal corrections, missing/expired margin, account/currency mismatch, physical exclusion, limits, session breaks, overnight/DST instants, overlapping references and corruption. Existing cash databases remain readable with the additive futures tables. This historical test count is not a new 2026-10-25 verification result and does not cover the newly documented human/hedge requirements.

The original foundation, futures and multi-broker slices passed remote CI on Python 3.11, 3.12 and 3.13. The reference-import slice defines the same matrix with all four offline CLI examples; check its associated PR for remote results. Tests do not establish investment performance or end-to-end production readiness.

## Next milestones and acceptance

1. Complete a bounded Phase 1 equity data slice: authoritative calendar/reference imports, processing-availability timestamps, immutable receipt observations, admitted prices and corporate actions. Select the feed against coverage, timestamps, delisted securities and storage rights. Prove idempotent imports, quarantine, split/rename and timezone replay before consuming that slice in a strategy. First real ingestion remains gated on source terms and operational configuration.
2. Continue the auditable SEC and news adapters, article-revision replay, raw futures-expiry data, broker-capability imports and a separate NAV contract with per-source acceptance. Add artifact dependencies, outcome definitions/queue and incident lineage before predictive model training. Human/hedge schemas can be specified now without claiming their workflows work. Public access does not establish model-training permission.
3. Phase 2: run a frozen simple numerical baseline through the first LEAN engine trial using admitted normalized data. Model fees, spread, delay and sessions; reconcile fills, positions and cash; demonstrate deterministic replay and compare with a risk-comparable reference. Larger AI/graph development follows this baseline rather than blocking it.
4. Phase 3: add futures contract-level fees, margin reservation, variation/final settlement, roll legs and aggregate exposure before hedge simulation. Verify exposure-linked hedge sizing/lifecycle, partial or rejected legs, sale of the protected holding, simultaneous losses, increased margin and unavailable cash at another broker. Report unhedged portfolio, hedge and combination separately. No hedge can bypass configured mandates or stops.
5. Phase 4: add source-backed analysis and the immutable human journal, then compare direct events, graph information and model-plus-human decisions against the frozen baseline on the same opportunities, risk and costs. Preserve chronological evaluation, trial registration and untouched final tests. Introduce candidate learning only after its outcome/incident data foundation and evaluation gates are verified.
6. Keep trader-history admission as the optional Phase 5 stream. Phase 6 verifies forward shadow/paper operation, portfolio risk, restart/failure cases and reconciliation; a second verified broker adapter then demonstrates broker independence under the same contracts. Phase 7 retains the separate fund/NAV flow.
7. Phase 8 live trading still requires separately configured scope, account/data entitlements, strategy evidence, risk budget and verified broker behavior. Documentation, synthetic fixtures and paper access alone do not authorize live orders.

Masterplan 1.4 retains the learning cycle, incident categories, adaptive evaluation, model-promotion bounds and state-preserving rollback as requirements for those later phases. The planning update does not change implemented capability status.
