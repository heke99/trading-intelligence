# Rebuild status

Documentation updated: 2026-10-25. Masterplan: 1.4. Package: 0.5.0.

The earlier implementation sections and their verification evidence retain the recorded 2026-10-20 state. Masterplan 1.4 was a documentation-only update. The subsequent 2026-10-25 market-record slice below adds offline functionality; authenticated data access remains unverified.

## Normalized daily market records — 2026-10-25

`MarketDataStore` now imports supplied normalized daily sessions, raw OHLCV, split and cash-dividend observations using existing raw evidence plus a new immutable market snapshot table. Replay uses processing availability, correction lineage and explicit listing/source identity. Missing or mismatched records block replay. See [MARKET_DATA.md](MARKET_DATA.md).

This is partial Phase 1b, verified with synthetic fixtures only. Vendor transport, authoritative calendar imports, admitted real prices, durable quarantine and corporate-action accounting remain unimplemented. Splits/dividends are preserved as observations; no adjusted returns, cash ledger or strategy readiness is claimed. The complete local suite passes 176 tests, including 18 new market-record tests.

## Supplied vendor capture and multi-day replay — 2026-10-25

`AlpacaMarketStore` now stages supplied daily-bar response pages with immutable raw capture, explicit listing bindings, exact decimals, receipt/processing availability and durable quarantine. Unknown publication/session timestamps remain unknown and no staged candidate is admitted to market snapshots. `replay_dates` creates a bounded gap report and hashed manifest for an explicit date list; ambiguity, permissions and integrity failures block replay. See [MARKET_PIPELINE.md](MARKET_PIPELINE.md).

The new repeatable `market-pipeline-demo` runs offline and is included in CI. All fixtures remain synthetic. Transport, authenticated data access, authoritative calendar import, real-data admission, corporate-action accounting and complete Phase 1b acceptance remain pending. The earlier 176-test result above belongs to the preceding slice; the current integrated verification is recorded below.

## Corporate-action and identity replay proofs — 2026-10-25

A bounded hypothetical corporate-action proof now values a fixed opening long holding through raw prices, splits, ordinary cash-dividend receivables and supplied payment dates. The policy explicitly declares dividend share basis and exact decimal arithmetic. Known omitted events, price/session gaps and unsupported timing block valuation. No real cash, holdings or orders are written.

`resolve_schedule` now demonstrates exact temporal symbol changes with mapping/evidence/listing/instrument lineage and verified raw hashes. Fixed-cutoff corrected snapshots are distinguished from per-request decision cutoffs. The repeatable `corporate-replay-demo` is in CI. See [CORPORATE_REPLAY.md](CORPORATE_REPLAY.md). Real event/calendar admission, complete action coverage, actual broker accounting and LEAN remain pending.

## Calendar adapter and declared admission gate — 2026-10-25

A bounded paper Trading `/v2/calendar` GET reader and `calendar-sync` CLI now preserve raw response bytes and explicit route/query provenance. The strict legacy-calendar importer preserves DST/early-close instants, request bounds, unknown publication and durable quarantine. No paper credentials are configured here; authenticated response access and account identity remain unverified.

Persistent reviews now bind rights, provenance, temporal basis and coverage to exact capture hashes and scope. The gate checks both historical and operational current state; a later denial or revoked permission cannot be bypassed with an old `as_of`. Unknown publication, incomplete pages, quarantined rows, mismatched scopes and bars captured before session close remain blocking. Reports perform no promotion and confer no training/live rights. See [CALENDAR_ADMISSION.md](CALENDAR_ADMISSION.md).

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
| Authoritative exchange calendars and corporate actions | Calendar GET/legacy-format adapter implemented; authenticated source/calendar admission and real action data not verified |
| Normalized daily price records and as-of replay | Implemented offline with synthetic tests; vendor imports and full Phase 1b acceptance remain pending |
| Futures roll, daily/final settlement and aggregate margin engine | Not implemented |
| Multi-broker canonical intents, account isolation and persisted drafts | Implemented offline |
| Two synthetic broker format encoders and explicit adapter registry | Implemented offline; no external connection |
| Alpaca paper reference GET reader and vendor-field normalization | Implemented; authenticated API access not verified |
| Raw response archive, processed availability and immutable reference batches | Implemented and tested with synthetic responses |
| Real order transport, positions/fill reconciliation and second vendor reader | Not implemented |
| Supplied Alpaca daily-bar normalization and quarantine | Implemented with bounded read-only GET pagination and durable partial captures; authenticated access/historical admission unverified |
| Bounded multi-day replay and gap manifests | Implemented for explicit expected-date scopes; not calendar/coverage certification |
| Split/dividend valuation and symbol-rename proofs | Implemented offline for explicit hypothetical scope; no actual broker accounting or action completeness |
| Paper calendar GET transport and legacy capture staging | Implemented with offline transport/format tests; authenticated account access unverified |
| Scoped rights/provenance/temporal/coverage review gate | Implemented as declared eligibility reports; no actual dataset promotion or independent certification |
| SEC submissions and raw daily-price GET transport | Implemented with injected-response tests; genuine source access not verified |
| News and NAV adapters | Not implemented |
| Artifact dependencies and append-only incident lineage | Implemented offline with source/hash/cutoff checks and downstream impact |
| Locked predictions and matured outcome revisions | Implemented offline for declared evaluation labels; no training authorization |
| Real equity/fund data entitlement | Not verified |
| Trader-history completeness or verification | Not implemented or verified |
| New datasets approved for training | None |
| AI analysis, predictive models and self-learning | Not implemented; evaluation queue is an offline foundation only |
| Pre-outcome human decision journal and intervention attribution | Required by masterplan 1.4; not implemented |
| Exposure-linked hedge policy, lifecycle and risk/result attribution | Required by masterplan 1.4; not implemented |
| Frozen numerical baseline and chronological experiment register | Implemented offline for synthetic target/abstention evaluation; no fills or performance |
| LEAN own-data export/reader bridge | Synthetic bundle and parser/API mechanics implemented; real admission binding/runtime trial pending |
| Supplied-simulation cash/position ledger | Implemented offline with fees/actions/reconciliation; no broker/LEAN event verification |
| Read-only readiness diagnostic | Implemented; configuration presence is not credential/source verification |
| Full LEAN replay and reconciled engine acceptance | Not executed |
| Backtesting and strategy profitability | Not implemented or established |
| UI, broker or fund order adapters | Not implemented |
| Simulated or live orders | Not executed |

## Four source and research foundations

The current delivery adds four distinct capabilities: bounded read-only price GET pagination with persistent raw pages and partial-run reports; public SEC recent-submissions capture/normalization; immutable artifact dependencies and append-only incident/correction lineage; and locked pre-horizon predictions with matured, validated, revision-aware outcome selection. See [RESEARCH_FOUNDATIONS.md](RESEARCH_FOUNDATIONS.md) and its source-specific documents. All four have a runnable combined synthetic CLI example.

Source configuration was checked without exposing values: Alpaca paper credentials and an identified SEC_USER_AGENT were absent. No external GET was performed. Provider rights, real feed/calendar quality, historical publication/vintage and authenticated account identity remain unverified. SEC acceptance time remains distinct from unknown publication. Artifact/outcome availability includes operational registration time; current revocations and confirmed data incidents cannot be bypassed by selecting an older cutoff. No admitted real dataset, training job, LEAN baseline, fills or orders were produced.

## Verification of PR #20 and four further readiness prerequisites

On 26 October, remote main `182d9bbe0e461a7f4adcf87e3d0144f96297ba7d` and tree `d216310c7130f4c987b0e24ea38fbaf20b3c6de4` were checked. An independent isolated copy passed all 386 tests, including negative rights, origin, cutoff and incident cases. The preceding four-part CLI reproduced its semantic results across a process restart; CLI key ordering was subsequently stabilized and covered by a byte-level restart regression.

Four additional distinct capabilities now prepare the Phase 2 trial: verified synthetic export/custom-data reader, a frozen baseline/experiment journal, supplied-simulation cash/position reconciliation, and read-only operational configuration diagnostics. See [LEAN_READINESS.md](LEAN_READINESS.md). The actual diagnostic found no Alpaca paper credentials, no SEC contact and no LEAN executable. It performed no network call or executable launch. Real admission/export binding and genuine engine execution remain pending. Neither target generation nor a ledger fixture completes Phase 2.

## Verification

Current local verification for the four LEAN-readiness prerequisites: **441 synthetic tests passed**, adding 55 to the preceding 386 (10 export/reader, 16 baseline/experiment, 17 cash-ledger, nine diagnostic, two prior-CLI verification regressions and one combined-demo case). Both the old and new four-part demos pass fresh-process restart checks; the new combined CLI, actual read-only diagnostic, compileall, link checks and git diff --check passed. Parallel code work and independent cross-review resolved current-rights, clock/sequence, late-action, next-session timing and concurrent final-consumption findings. No external source or LEAN runtime was exercised. Remote CI is verified separately on the delivery PR.

Previous local verification for the four source/research foundations: **386 synthetic tests passed**, adding 83 cases to the previous 303 (20 price transport/pagination, 22 SEC, 20 artifact/incident, 20 prediction/outcome and one combined restart/demo case). The combined four-part CLI demo, compileall, git diff --check and independent code/docs review passed. External source access was not tested because credentials/contact configuration was absent. Remote CI is verified separately on the delivery PR.

Previous local verification for the calendar/admission slice: **303 synthetic tests passed**, adding 58 cases to the preceding 245 (24 calendar-format, 10 bounded transport, 19 admission-gate, four synchronization and one integrated demo cases). CLI admission-demo, compileall, git diff --check and independent code/docs review passed. No authenticated API call was made; tests use injected transport and clocks. Remote CI is verified separately on the delivery PR.


Previous local verification for the corporate-action/identity slice: **245 synthetic tests passed**, adding 38 cases to the preceding 207 (21 corporate-action cases, 16 identity cases and one combined demo). The CLI corporate-replay demo, compileall, git diff --check and independent code review passed. Opening-to-scope event gaps and actions after session open have explicit rejecting regression tests. Remote CI is verified separately on the delivery PR.


Previous local verification for the supplied-capture/multi-day slice: **207 synthetic tests passed**, including 31 additions to the preceding 176-test suite (18 vendor staging/quarantine cases, 11 multi-day replay cases, one pipeline-demo case and one structured-input regression). The CLI pipeline demonstration, compileall and git diff --check also passed. Remote CI results are verified separately on the delivery PR; no real-data or market-performance conclusion follows from these checks.


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

## SEC relative-document compatibility fix

A subsequent permitted public SEC GET on 26 October succeeded with an identified User-Agent. Its raw hash matched the user's Mac capture exactly. The previous basename validator reproduced 328 accepted/674 quarantined rows; all 674 rejected indices corresponded to nested primary-document paths. Normalizer v2 preserves safe relative segments and accepts all 1,002 rows on those exact bytes, retaining unknown publication and existing admission limits. Row diagnostics now identify fields and all independently found issues. Existing capture versions are not rewritten; a new import ID is required to obtain v2 normalization. See [SEC rerun instructions](SEC_FILINGS.md).

Actual source access in this narrow permitted test supersedes the earlier statement that SEC access had not been exercised; it does not establish complete history, source/filing quality, dissemination timestamps or training permission. Original user/capture files remain outside the repository.

SEC-fix validation: all 446 synthetic tests passed, including 27 SEC cases and five new path/diagnostic/legacy-version regressions. Independent review, compileall and git diff --check passed. The separate real-response comparison was performed outside committed test fixtures.
