# Verification — v0.1.0, 2026-09-28

## Actually executed

- Runtime: Python 3.13.5, Linux development container.
- `python -m unittest discover -s tests -v`: **60 tests passed**.
- `python -m compileall -q trading_intelligence tests`: passed.
- Offline CLI demo: two synthetic closed trades and two synthetic order snapshots.
- Repeating the demo: **zero new record versions**, not duplicated history.
- Mapped synthetic CSV import: two rows, zero quarantine; `synthetic_fixture` origin.
- CSV inspection: headers/count only; no private trade values printed.
- Wheel build with `--no-deps --no-build-isolation`: passed.
- Built wheel installed into a separate target with `--no-index --no-deps`.
- Installed-wheel demo run outside the source directory: four synthetic versions,
  network not used, training not enabled.

## Important tested behavior

Cursor pagination, URL decoding, short pages with further cursors, cursor loops,
page caps, non-paginated schema changes, Pascal/camel-case envelopes, API permission
errors inside HTTP 200, HTTP 401/403, redirect refusal, bounded 429/503 retries,
Retry-After handling, reflected-key refusal, invalid/ambiguous JSON, missing Results,
unknown endpoints, strategy mismatches, duplicate observations, source revisions,
quarantine, immutable raw hashes, partial-run failure, synthetic/provider separation,
explicit CSV mapping, duplicate headers, decimal preservation, no invented net P&L,
unknown timezone flags, timezone evidence, DST ambiguity, closed-before-open errors,
order-posted time versus fill time, option identity and completed-run filtering.

Tests use made-up records and fake network transports. They are NOT evidence that
Collective2 has granted an account access or that a strategy is profitable.

## Not executed / not claimed

- Authenticated Collective2 requests or a successful live data download.
- Parsing a verified real Collective2 CSV export.
- Complete strategy-history reconciliation or legal/license approval.
- Market-data joins, feature generation, model training or backtesting.
- Live trading or broker connectivity.
- Native execution on the user's Mac or on Windows.
- GitHub Actions: a workflow is supplied, but no remote run occurred.
- GitHub publication: repository read succeeded; file creation returned HTTP 403
  `Resource not accessible by integration`. No remote branch, commit or PR was created.

All manifests remain `training_ready=false` and `full_history_verified=false`.
GitHub repository visibility was public when checked. No real trader data or API key
has been added to the source package.
