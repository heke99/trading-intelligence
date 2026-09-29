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

## Follow-up verification — 2026-09-29

The original ZIP SHA-256 matched
`c94956f6047d776a6da25bf693837dcaf8bda4843adbac83d9b34f5c12b25ebc`.
All 22 archive entries were checked for absolute paths, parent traversal, and
symlinks before extraction. The original package was committed separately from
the changes below.

- Runtime: Python 3.12.14 on Linux; 3.11 and 3.13 were not installed locally.
- Before the fixes, two new regression tests reproduced escaped-key reflection
  and duplicate versions across a live-style fetch and saved-JSON reimport.
- `python3 -m unittest discover -s tests -v`: **62 tests passed** after the fixes.
- `python3 -m trading_intelligence --help`: passed.
- `demo`, `status`, and the repeat demo: four first-run versions, zero second-run
  versions, eight observations across four completed run manifests.
- `inspect-csv` on the synthetic example: eleven headers, two rows, no row values.
- `import-csv` with the synthetic mapping: two versions, zero quarantined rows.
- Wheel build: `python3 -m pip wheel --no-index --no-deps --no-build-isolation -w dist .`.
  Wheel installed with `--no-index --no-deps` into a fresh virtual environment;
  its CLI help and offline demo worked from a directory outside the source tree.
- `git diff --check`: passed. The GitHub Actions matrix specifies 3.11, 3.12,
  and 3.13 and uses only synthetic offline data; the remote workflow has not run.

No authenticated Collective2 call, real export, original CSV mapping, license,
complete historical coverage, brokerage execution, training, or trade was tested.
`training_ready=false` and `full_history_verified=false` remain fixed.
The repository was empty and public at the start of this follow-up. GitHub's
contents write endpoint returned HTTP 403 `Resource not accessible by integration`;
an HTTPS `git push` also failed because no terminal GitHub credentials were available.
This local verification must not be presented as a successful remote CI run or PR.
