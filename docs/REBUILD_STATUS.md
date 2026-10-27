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

## Pinned isolated LEAN observer harness

A single `python -m trading_intelligence.lean_smoke prepare-run` command now prepares two synthetic observations and runs the pinned ARM64 Docker image with network disabled, read-only dedicated input and writable dedicated output. Input hashes, algorithm callback observations, engine UTC times, zero orders, container exit/log and LEAN final Completed/error state must all agree. Fresh output and scoped timeout cleanup prevent stale evidence or an abandoned container from being treated as success. See [LEAN_SMOKE.md](LEAN_SMOKE.md).

Development validation: 464 synthetic tests passed (13 harness mechanics and five algorithm/config cases added to 446), plus compileall, diff checks and independent code review. Docker is absent here; preparation/mocked artifacts do not verify an engine run. The user-provided pinned-image/runtime installation facts are prerequisites, not an accepted smoke result. Actual Mac log/result acceptance remains pending. This observation-only smoke does not implement a full strategy backtest, native equity fill/accounting model or profitability proof.

## Actual Mac smoke failure and UTC-boundary correction

The first Mac LEAN attempt started the pinned engine and loaded the local custom-data file, then failed on the first observation with an offset-naive/aware datetime comparison. It is recorded as failed, not a passed motor trial. The observer now converts the engine ISO representation into a native UTC Python datetime, preserving aware offsets and the explicit naive-engine-UTC convention; comparison and serialization share that normalized value. Container/log/final-state failures precede missing observer-file diagnostics. Only timeouts invoke scoped cleanup, and already-removed containers are reported separately without altering engine logs.

Validation: 470 synthetic tests pass, including six new native/wrapper-time, no-early, failure-precedence and cleanup regressions. Docker is unavailable here; the corrected fresh Mac attempt `ti-lean-smoke-002` remains pending actual output acceptance. See [LEAN_SMOKE.md](LEAN_SMOKE.md).

## Captured prices/calendar to grouped LEAN inspection

The user reported a passed Mac synthetic smoke002: two observations, zero orders, pinned ARM64 image and input-manifest SHA256 `8b3dd050dadf3f134282a2579f3e675c72075a772f42b6cd4815739e8968e6b9`. Its files have not been independently copied/reverified here; this is user-reported synthetic engine evidence, not provider-data admission.

A new single captured_smoke prepare-run path reads an explicit price synchronization job and a separate calendar capture from the existing read-only database. Current storage/research declarations, raw/journal/provenance hashes, receipt timing, identity, pagination and exact date join are verified independently per source. A hash-bound inspection-only report preserves raw OHLCV, unknown publication, separate calendar/listing venues and original availability. Equal-availability observations are one custom-data event with an ordered row group; no fake time offsets or historical trading availability are introduced. It reuses the pinned isolated observer harness and never mounts the database or sends orders.

Validation: 486 synthetic tests pass, including ten capture-inspection and six grouped integration cases. Compileall/diff checks and independent code review passed. The actual 17-row Mac capture-inspection engine run remains pending; no new runtime success, historical backtest, admitted real dataset or training readiness is claimed. See [CAPTURED_OBSERVATIONS.md](CAPTURED_OBSERVATIONS.md) for the single command and scope.

## Captured observer001 completed-day blocker

Actual Mac captured observer001 failed: LEAN ran only through 25 October, excluding all observations known on 26 October. Pinned public SetEndDate clamps backtests to the previous algorithm day; its overload/config paths do not provide a supported same-day bypass. New preflight blocks Docker with NOT_YET_REPLAYABLE and the next eligible UTC midnight. Initialize independently validates actual engine end coverage and writes window evidence. Original observations/timestamps, no-order and acceptance checks remain unchanged.

The existing 26 October captures become eligible on 27 October 2026 at00:00 UTC (01:00 Stockholm). They must be reused without a new fetch. The next directory is ti-captured-observer-002. No private-field, clock, timezone or live-mode bypass is introduced, and no successful captured engine run is claimed.

Validation:491 synthetic tests passed, including five exact-boundary/no-Docker/public-setter-clamp regressions. Independent primary-source/code review, compileall and diff checks passed; corrected captured engine acceptance remains pending the eligible Mac run.

## Captured observer transport precision — 27 October 2026

The user-reported eligible Mac run `ti-captured-observer-20261027T074754Z` failed with `Future information emitted early`. Upstream Python.NET's Python-to-CLR conversion truncates sub-millisecond microseconds. Custom-data delivery now conservatively ceils to a millisecond while keeping original source availability and strict callback/host checks exact. Distinct groups that would collide are rejected; original ties remain one group. Completed-day and actual engine-window checks include transport rollover. Both compared timestamps are included in future early-delivery errors. See [CAPTURED_OBSERVATIONS.md](CAPTURED_OBSERVATIONS.md).

Validation: 497 synthetic tests pass, including six precision regressions modeling the lossy boundary, exact source preservation, 17 tied rows, collisions, midnight rollover and every microsecond remainder. Docker is unavailable here; successful corrected Mac capture observation remains unverified. No dataset admission, training readiness, profitability or live-trading claim changes.

## Reported Mac captured inspection passed — 27 October 2026

After pulling PR #27 (`d18bf7354992546a984e05cf7015a77c68a35500`), the user supplied a fresh Mac result with `status=passed`, `engine_observation_verified=true`, `observed_count=17`, `observed_group_count=1` and `orders_sent=0`. The reported scope is `captured_data_inspection_only`, using the pinned ARM64 image `quantconnect/lean@sha256:afc3a126d3ba294784a3f11dff38cdfed020672f021e02df7b24f7e2335ba0ca`. This supersedes the pending actual-run result above as user-reported runtime evidence. The underlying Mac files have not been independently copied or hash-reverified here.

Reported SHA256 evidence identifiers:

- Input manifest: `53418847e69a57110f482c386f244c8461a865be873890b87ba9c8b4fd513472`.
- Inspection report: `074c9f2d4c71c35d3a3bec366d4931117db34bf2ca1a48b754a6006d2b89f373`.
- Observer evidence: `27cd5b693ac0450e59dcbff3b08f81b321055249d19c486cefa5497b238d6db1`.
- Engine log: `26eef2498fd1a87fef56eca426546aed2a4798760e2814803a62c7d73c1d354a`.
- Window evidence: `1d89e677d52e3bf9d1e99a0cfad2c3542e0c48921e01aa8286e0d1d9783564c2`.

Preserve the successful local run directory and original database/captures. This verifies the reported propagation of 17 captured observations through the observer, with exact source/time/count and zero-order acceptance checks; it does not establish provider publication times, historical strategy replay, source entitlements, dataset admission, training readiness or profitability. All of `dataset_admitted`, `real_dataset_admitted`, `publication_verified`, `training_ready`, `strategy_profitability_verified` and `live_trading` remain false in the supplied result.

The next masterplan dependency is an explicit admitted slice: resolve source-use rights, provenance, listing/calendar applicability, publication/availability basis, coverage and corporate-action evidence for a bounded intended use. Unknown historical publication must remain unknown. Only after that gate passes should the frozen simple numerical baseline be exported and evaluated through LEAN with its cash/cost accounting. Successful observer inspection alone cannot authorize either step. This entry changes documentation only; no new code or engine run was performed.

## Two-source captured admission assessment — 27 October 2026

`captured_admission assess` now creates a read-only, private assessment/review packet for the actual shape of the Mac captures: separate price/calendar sources and a complete synchronization job with all pages. A stable version-2 review scope binds full observation/identity/route/page provenance without changing merely because the assessment clock advances. The immutable review store accepts this scope for each source's rights, provenance, temporal basis and coverage assertions. The legacy single-source API remains available and explicitly refuses to misinterpret a new job scope.

No approvals are fabricated: missing review tables yield missing reviews, templates contain no allow decisions, and unknown publication hard-blocks historical replay even with every declared allow review. Current source revocation, denial/expiry, wrong-source evidence, scope substitution, venue mismatch and corrupted pages remain blocking. Forward declared-purpose eligibility is separate from real admission and baseline readiness; corporate-action coverage, executable price/cost assumptions and experiment binding remain unresolved. See [Mac command and exact limits](CAPTURED_ADMISSION.md).

Validation: 512 synthetic tests pass, including 15 new two-source/pagination/review/readonly/CLI cases. Compileall and diff checks pass. The local CLI was executed against invented fixture captures; actual Mac assessment output remains pending. No provider requests, new LEAN run, market promotion, strategy performance, dataset admission, training readiness or live orders were produced by this delivery.

## Mac admission result and forward observation preparation — 27 October 2026

The user supplied the actual Mac assessment for 17 rows: scope SHA256 `1f2a4288a5c17bfda5de740423e2cb47b9adcee3c64d7e296d8637660a8ed4f9`, assessment-file SHA256 `ab96501e6120cc0d5d6a4aadf077b119e41d50b0d159102bd09bf6f164038550`, all source reviews absent, unknown historical publication and zero rows available by their original session close. Every row's known-at was `2026-10-26T13:37:46.748682Z`. No venue mismatch was reported. This is user-reported assessment evidence; the Mac files were not independently copied/reverified here. The user clarified that the account is paper; that is not a verified market-data plan or usage-rights finding.

A new `forward_pilot` prepares a private operationally timestamped protocol from those existing captures without changing the source database. It reuses `BaselineStore` to freeze the rule/lookback/cost assumptions and binds seed/route/source/listing identity. Explicit `collect` performs GET-only account matching, bounded calendar and raw-price capture, a new scoped forward assessment and immutable abstention logging. Current permissions and original seed integrity are checked before networking. Old dates newly fetched do not become prospective outcomes. Current New York dates are excluded; publication remains unknown. Terminal retries never refetch, interrupted attempts require new IDs, and transactional reservation prevents concurrent duplicate collection.

Validation: 532 synthetic tests pass, including 20 new protocol/reader/journal/CLI/race/chronology cases, plus compileall and diff checks. Collection was exercised with invented source bytes and injected readers; real Mac collection remains pending. Source rights, corporate-action coverage and actual dataset admission remain unresolved. No real-data rule evaluation, paper/live order, simulated fill, strategy profitability, training readiness or new LEAN execution is claimed. See [Mac prepare/collect/status commands and limits](FORWARD_PILOT.md).

## Reported first Mac forward collection — 27 October 2026

The user supplied successful preparation and first collection output for `apple-forward-001` in `ti-forward-20261027T095324Z`. Registration was `2026-10-27T09:53:24.721195Z`; frozen plan SHA256 was `23d5eaf09c6734ab0e776842de5e2094d60ddd9e4c8500da36380870b26f048a`. The first collection recorded at `2026-10-27T09:53:26.146190Z` matched the paper account, captured 18 observations through `2026-10-26`, and preserved packet SHA256 `3dc27bd311f3bb24d27f7cc83ba8b8413a5b454993b7ca84b00c7a569f8294ea`. Exact new import IDs are `apple-forward-001:first:prices` and `apple-forward-001:first:calendar`.

`post_registration_rows=0` is expected: all included sessions closed before registration. This is successful account/capture orchestration reported by the user, not a prospective strategy outcome. Eight source-specific scoped reviews remain missing. Dataset admission stays false; the saved decision is abstain and orders remain zero. The forward assessment's absence of a historical-publication reason does not establish historical availability or publication verification. Raw Mac files have not been independently copied/hash-reverified in development.

Reuse this same frozen pilot and directory. The earliest policy boundary for collecting the 27 October session is 28 October 2026 at 00:00 New York, 04:00 UTC / 05:00 Stockholm. A later capture uses a new collection ID; do not prepare a replacement pilot or reuse terminal ID `first` expecting a new fetch. The boundary permits a new observed revision, not proof of final or original provider publication. No background scheduler or additional engine/strategy execution was installed. Remaining admission, corporate-action and cash/cost dependencies still apply. This entry records reported runtime evidence only; no code or new test execution changes.
