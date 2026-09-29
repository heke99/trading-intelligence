# Data contract v1

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
