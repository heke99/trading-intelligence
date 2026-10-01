# Trading Intelligence — history importers v0.2

A read-only data-acquisition foundation. **Not a trained robot, an execution system,
or a claim of investment performance.** No live trading, subscriptions, payment,
broker login or order-placement methods exist in this package.

The importer reads two documented Collective2 API4 endpoints: closed trades and
historical orders. It also ingests saved API responses and explicitly mapped CSVs.
An authenticated provider run has **not** yet been verified. A real exported CSV's
headers have **not** yet been verified. See [the Swedish data guide](docs/DATA_GUIDE_SV.md).

The separate publisher pipeline imports the eight reviewed Grittani/Hougaard XLSX
layouts, reviewed image transactions, public journal summaries and educational
strategy cards. It preserves source types, unknown clocks and historical revisions;
it does not turn them into authenticated fills or a learned trading policy.
See [publisher commands and the path toward a scalper](docs/PUBLISHER_DATA_SV.md).

## Run without installing dependencies

Python **3.11 or later**. The runtime uses only Python's standard library.
Run these commands from this repository's root directory:

```bash
python3 -m unittest discover -s tests -v
python3 -m trading_intelligence demo --out data/demo
python3 -m trading_intelligence status --out data/demo
```

The demo makes up two closed trades and two order snapshots. It never contacts a
provider. Demo records are labelled `synthetic_fixture`. Repeating an identical
import adds observations, not duplicate record versions. The same saved API response
also reuses the versions created by a prior API fetch with the same normalization policy.

Optional editable installation: `python3 -m pip install -e .`.
This is not necessary for any of the commands above.

## Fetch authorized Collective2 history

Obtain an **API4 developer key**, not a PlatformTransmit/API3 key. Confirm that the
account may retrieve and store the specified strategy's history. Training rights
are a separate question; the access acknowledgement is **not** a training license.

```bash
python3 -m trading_intelligence fetch \
  --strategy-id 134962085 \
  --out data/forex-vix-3 \
  --acknowledge-authorized-access
```

A local interactive terminal prompts for the key with hidden input. Never paste
it into ChatGPT, GitHub, a command-line argument, a notebook or a screenshot.
Noninteractive use requires the `C2_API_KEY` environment variable, supplied through
a local secret manager. The program does not read `.env` files automatically.

A second candidate, not an investment recommendation:

```bash
python3 -m trading_intelligence fetch \
  --strategy-id 146455121 \
  --out data/calicut \
  --acknowledge-authorized-access
```

Each fetch requests closed trades with explicit `CommissionPlan=0`, then follows
historical-order cursors. It does not filter to filled orders only. It uses GETs
to a hardcoded host and two hardcoded paths, refuses redirects, validates TLS,
bounds response size/page count/retries and never logs provider error bodies.
Reflected API keys, including JSON-escaped representations, stop acquisition before
the response can be archived.
Network access was mocked in tests; account permissions remain to be tested live.

`--commission-plan` accepts the documented values 0, 1, 3, 4 or 5. This is source
metadata, **not** an assurance about actual paid costs. The order endpoint does
not take this parameter. We do not subtract `Commission` from `ProfitLoss` until
their precise semantics and currency have been verified.

If an HTTP 401/403 or `API_RESPONSE_ERROR` occurs, contact C2 about data permissions.
Do not enable AutoTrade or grant trading permission simply to fix a research import.
`RETRY_LATER` means the program declined to retry before the server's wait period.
There are at most two retries per request, and no endless polling.

## File imports

An API response may also be imported offline:

```bash
python3 -m trading_intelligence import-json private/closed-trades.json \
  --kind closed_trades --strategy-id 134962085 --out data/forex-vix-3
```

This accepts a `Results`/`ResponseStatus` API envelope, not an arbitrary JSON
journal. A local terminal page does not prove all prior pages were supplied.

For a CSV, inspect its original headers first:

```bash
python3 -m trading_intelligence inspect-csv private/export.csv
```

Then provide a reviewed mapping from CSV column names to the documented C2 fields:

```bash
python3 -m trading_intelligence import-csv private/export.csv \
  --mapping private/csv-mapping.json --strategy-id 134962085 --out data/forex-vix-3
```

**The included mapping is for the synthetic example, not a claimed C2 export format.**
Test that CSV path safely with:

```bash
python3 -m trading_intelligence import-csv examples/synthetic_closed_trades.csv \
  --mapping examples/csv_mapping.synthetic.json --strategy-id 900000001 \
  --out data/synthetic-csv --synthetic-fixture
```

Supported input: UTF-8 CSV, comma/semicolon/tab delimiters. Field names, side values
and any non-ISO datetime format must be explicitly mapped. Numeric strings must
use decimal points and no thousands/currency formatting. Unsupported formats fail
or quarantine; they are not silently guessed. Broker HTML, Excel, PDF and MT5 reports
are not supported by the C2 adapter. The separate publisher adapter accepts only
its reviewed XLSX layouts and evidence schemas, not general broker reports.

## Timestamps and learning safety

`OpenDate`/`CloseDate` without an offset remain unconverted and receive
`TIMEZONE_UNVERIFIED`. A verified timezone can be supplied with both
`--naive-timezone` and a non-secret `--timezone-evidence` reference. Do not invent
that reference. Ambiguous/nonexistent local times at DST changes are quarantined.

The API schema explicitly describes `PostedDate` as UTC; the API normalizer records
that basis. CSV order timestamps do **not** inherit that assumption. Most importantly,
`PostedDate` is not a fill timestamp, and a historical order's final state is not
information necessarily available when it was submitted.

Closed-trade VWAPs are outcomes, not exact individual fills or safe entry-time
features. Their normalized records are labelled `outcome_only_not_features`.
Order snapshots are labelled `historical_snapshot_not_point_in_time_features`.

## Output

```text
data/<dataset>/
  history.sqlite3            # source versions and observation/run relations
  raw/<sha256>.json          # unmodified successful API/local JSON bodies
  raw/<sha256>.csv           # unmodified CSV input
  runs/<run-id>/
    manifest.json            # provenance, counts, gates, endpoint traversal
    normalized.jsonl         # reviewed schema, monetary quantities as strings
    quarantine.jsonl         # only when individual rows could not be normalized
```

Raw bytes are hash-checked and not overwritten. Revisions to an existing source ID
are stored as new versions, not silently substituted. SQL operations are parameterized.
Different strategy IDs, record types and synthetic/provider origins remain separate.
The `completed_run_records` view excludes failed/in-progress runs, but is **not** an
approved training dataset. It may contain multiple historical versions of an ID.

`observed_timestamp_ranges` shows observed minima/maxima, **not** continuous market
coverage. Symbol counts are observation counts and can include duplicate source rows.
A successful API cursor traversal remains `full_history_verified=false` until source
counts, access scope and start/end coverage have been independently reconciled.

Every manifest has `training_ready=false`. This is a workflow marker, not a legal
approval system or a security boundary against a person reading the raw database.
There is no training command, market-data join, model, or execution connection yet.

## Privacy, repository and operation

Keep originals, credentials, license evidence and runtime data out of Git. The
`.gitignore` is defense in depth, not a secret scanner. Inspect `git status` before
committing. Local files use owner-only modes where supported, but this package does
not encrypt your disk. Use an encrypted disk and private backups.

Prefer a private repository. Candidate names/IDs in `examples/candidate_sources.json`
are a research inventory only; no prior headline returns or scraped trade rows are
used as training examples.

The GitHub Actions workflow only runs offline synthetic tests, without any C2 secret.
The runtime does not depend
on Vercel, Supabase, a GPU, a Windows terminal, or a live brokerage account.

Next engineering milestone: run a permitted real export, reconcile source counts,
confirm timestamps/instrument units/costs, then build a point-in-time market-data
adapter and chronological benchmark. Data validation alone cannot prove profitability.

See [source contracts](docs/SOURCES.md), [data contract](docs/DATA_CONTRACT.md), and
[verification record](docs/VERIFICATION.md).
