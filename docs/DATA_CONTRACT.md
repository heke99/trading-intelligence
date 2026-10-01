# Data contract v1

This contract's original sections describe the C2 namespace. Version 0.2 adds
a separate publisher namespace; see its contract below and
[the Swedish publisher guide](PUBLISHER_DATA_SV.md).

## Raw evidence

Successful API response bodies and supplied local JSON/CSV files are archived without
rewriting bytes, named by SHA-256. Invalid local file envelopes remain available for
review in the private raw archive. API error bodies, headers containing authentication
and keys are not archived. A reflected API key in a success response aborts acquisition.
Raw JSON schema errors may abort an API page before that invalid page is archived;
already accepted pages and the failed run manifest remain available.

## Identity and revisions

Identity is `(strategy_id, kind, source_id, data_origin)`.
Closed-trade identity uses `TradeId`, falling back to `Id` with a quality flag.
Orders use `Id`, falling back to `SignalId`. Numbers are validated as positive int64
IDs, never first converted through floating point.

Every unique source row + normalization-context fingerprint has its own version.
All versions are retained. Identical repeated observations do not insert another
version. No automatically chosen "latest truth" is exported when a source revises
history. Revisions must be reviewed before building any training dataset.
An API fetch and a later import of that exact saved API response share the same
normalization context and business version. Their separate run observations remain.

## Numeric and instrument semantics

Price/quantity/P&L values are parsed with Decimal and represented as strings in
normalized JSON. NaN and infinity are refused, including in optional monetary fields.
Quantities must be positive where required; fills may be zero. Price positivity is
not enforced universally because contract rules differ.

C2 symbols and exchange symbol objects are preserved, including option/future identity
fields. `instrument_currency` is NOT assumed to equal P&L/account currency. A multiplier,
lot-size conversion or fee formula is not inferred. `profit_loss_reported` and
`commission_reported` are separate; `net_pnl` and `pnl_currency` remain null.

## Time and causal separation

Original datetime strings are retained alongside converted UTC values. Ambiguous or
nonexistent DST wall times are quarantined. Timezone-less trade timestamps without
evidence remain unknown. API `PostedDate` is UTC according to the documented DTO,
but is not a fill time. CSV timestamps have their own explicit policy.

Closed-trade VWAPs, P&L and final order states are retrospective observations. They
must not become features at entry/posting time. These records are NOT a reconstructed
point-in-time order book or event stream. No claimed reasoning or initial stop is
invented from a final outcome.

## Completion and failure

`status` is `in_progress`, `completed`, `completed_with_quarantine` or `failed`.
`completed` means the requested import operation completed; it does not mean a
history is complete or a model is approved. API traversal follows `next_cursor`,
not page length. Empty local/remote data never proves no historical trades occurred.

A local order page with `next_cursor` is marked incomplete. Even a local terminal
page cannot prove the earlier pages exist. Missing/default permission scope,
truncation at source, archived periods and onset dates require external reconciliation.
Partial API failures remain failed, with accepted raw pages preserved. Failed and
in-progress runs are excluded from `completed_run_records`. A SIGKILL/power loss may
leave a run in progress; that also remains excluded. No automatic resume cursor is
persisted for future requests; use a fresh fetch and idempotent ingestion.

SQLite is the authoritative observation/version store. JSON manifests and JSONL are
human-readable exports, not a transactional distributed database. Protect the local
directory against unauthorized modification. This package is not designed as a
multi-user, tenant-isolated web service or an encrypted secrets vault.

## Training admission

Every run remains `training_ready=false`. Rights, source reconciliation, point-in-time
market data, execution costs, sample-selection policy and chronological evaluation
are unresolved. No CLI flag can enable trading or train a model. A future training
pipeline needs its own reviewed admission check; do not read the audit tables directly
as a finished model dataset.

## Publisher namespace (software v0.2)

Publisher evidence never enters C2 `record_versions`, `observations` or
`completed_run_records`. Its own sources, snapshots, record versions and run
occurrences are stored in `publisher_*` tables and `publisher-runs/` exports.
`completed_publisher_records` includes completed historical versions, including
quarantined observations; it is not a training-admitted or latest-version view.

Identity is `(source_id, data_origin, record_kind, source_row_identity)`.
XLSX identity is a source/sheet/physical-row locator, not a stable broker trade ID.
Image identity uses the publisher image ID, visible row and rectangle; journal
identity uses the reported post ID; teaching identity uses the source card ID.
Reordered rows are not automatically reconciled. Distinct identical physical
rows and exit legs are retained. No cross-source trade deduplication is inferred.

Raw hash identifies immutable XLSX/JSON/JSONL/PNG bytes. XLSX semantic hashes
include raw cell values, XML types, formulas/attributes and date system, excluding
ZIP packaging and styles. Version fingerprints include adapter version and
normalization context, excluding download/import clocks and byte receipts.
Per-run occurrences preserve current snapshot provenance even when a version
is reused; version JSON retains its first occurrence's provenance.

Only documented layouts and explicit reviewed evidence schemas are accepted.
Selection policy and unselected nonempty row locators are exported per sheet.
Originals remain archived; omitted rows are not silently represented as trades.
Excel formulas are not evaluated; cached numeric values remain publisher values.
1900 fictional leap-day serials and invalid chronologies are flagged/quarantined.
Local minute clocks, transaction dates and publication/download clocks do not
become UTC execution events. Download clocks require explicit hash-matched receipts.

Record types distinguish transaction ledgers, reported day exit legs, swing
positions, journal position summaries and educational strategy cards. Cash values,
signed quantities, stake, rounded journal P&L and displayed prices retain their
reported meaning. Unknown P&L currency stays null. Strategy cards retain unknown
parameters; they do not become learned policies or claimed historical signals.

All publisher runs remain `training_ready=false`, `full_history_verified=false`,
`market_history_joined=false`, `trading_enabled=false` and rights unverified.
Completed acquisition/import means only the requested operation completed.
Failures preserve raw/partial evidence and failed receipts/manifests. The public
downloader follows only allowed Google export redirects, never retries access
denials, and does not authenticate or select alternate routes.
