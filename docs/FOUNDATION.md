# Offline foundation: contracts and limits

This is the first bounded implementation of Phase 1. It uses Python's standard library and SQLite so temporal rules can be checked without paid feeds, credentials or a running service. It does not replace the planned Postgres/object-storage architecture.

## Identity

An `Entity` represents an issuer or fund manager. An `Instrument` represents a security or share class and references its entity. A `Listing` represents an equity/ETF venue and trading currency. An instrument may have several listings; symbols are not primary keys.

Entity, instrument and listing records are immutable through the package API. They are not yet a full historical security master: reorganizations, merges, corporate actions, identifier coverage and broker contracts remain future work. MIC and currency fields receive format checks, not authoritative registry verification.

Identifier mappings carry a provider namespace, exact value, listing, economic validity interval `[valid_from, valid_to)`, knowledge time and backing evidence. Versions with the same `mapping_id` describe successive complete assertions about one mapping interval. At a knowledge cutoff, only that mapping's latest known version is eligible. Multiple intervals require separate mapping IDs. Callers must keep mapping IDs stable within their source namespace; the API does not discover equivalent mappings.

Resolution uses both `effective_at` and `as_of`. A later correction may change the answer for the same economic date without changing what an earlier knowledge cutoff returns. No match raises `UnknownIdentifier`; multiple distinct matching listings raise `AmbiguousIdentifier`. There is no fuzzy fallback or order-routing API.

Mutual funds and indices are represented as instrument types but cannot receive exchange listings in this implementation. Fund execution is classified as NAV subscription/redemption. Cutoffs, dealing calendars, forward pricing, settlement and fund identifiers are not implemented.

## Raw evidence and time

`ingest` accepts non-empty original bytes, source/record/revision IDs, `published_at`, `received_at` and optional `correction_of`. Timestamps require explicit timezones and normalize to UTC. Publication after receipt is rejected for investigation. Adapters must not use this publication field for a future economic event date.

Content is stored as SHA-256 addressed raw bytes in SQLite. Evidence versions reference that content; the same revision cannot silently change its bytes, publication time, lineage or first observation. Identical retries reuse the version and record distinct receipt observations. A different revision at the same source/record receipt time is rejected, avoiding arbitrary ordering. Explicit corrections must reference an earlier version of the same source and record.

Historical retrieval selects the latest first-received revision at or before `as_of` and verifies its raw content hash. An article first imported today is unavailable to a historical query yesterday, even if it has an old publication date. Revision IDs are opaque source identifiers, not sortable version numbers; adapters must normalize provider semantics and quarantine out-of-order stale revisions before ingestion. The foundation does not infer which provider payload is authoritative.

All timestamps and source classifications are caller assertions. Importing a file with a historical `received_at` does not prove historical availability. Immutable operational receipt logs, adapter processing completion time, trusted clock controls and independently justified historical vintages are still needed. This prototype cannot certify executable real-time signals or complete market replay.

## Rights and provenance

Sources have one immutable declared origin: synthetic fixture, provider report, verified brokerage fills, hypothetical strategy or paper fills. Selecting `verified_broker_fills` does not verify an account or trade. An adapter and admission review must establish the claim before any real records use it.

Permission snapshots are versioned by knowledge time. Storage, research and training are separate declarations; missing permission denies the requested use. Training access is not granted by a successful import. The training permission flag does not establish `training_ready`, completeness, temporal quality or other dataset admission conditions.

Historical permission queries support audit and replay. They are not a current legal-entitlement or user-authorization service: querying an old cutoff must not be used to bypass a currently revoked license. Production access needs both historical admissibility and a separately enforced current entitlement. No dataset in this repository is approved for real training.

## Operational limits

- Append-only behavior is enforced by the package API. Direct database access can alter records; this is not a tamper-proof archive or access-control boundary.
- SQLite raw BLOBs are for small offline fixtures. Production ingestion needs migrations, concurrency handling, object storage, backups and access separation.
- There are no market adapters, calendars, corporate-action adjustments, numeric financial calculations, portfolio positions, order or fill simulations.
- There are no forecasts, outcome labels, incident workflows, retraining jobs or automated model promotions.
- Nothing runs on a schedule or connects to an external account.

## Verification

The standard-library test suite uses invented data only. It covers temporal corrections, no publication-date lookahead, ambiguity, retry idempotence, raw-read corruption detection, foreign-key integrity, source separation, timezones, fund/equity separation, default-denied uses and permission history. The persistent offline demo is run twice to check that reopening the database preserves results without duplicating versions.

Run `PYTHONPATH=src python3 -m unittest discover -s tests -v`. CI defines the same suite on Python 3.11, 3.12 and 3.13; CI results must be checked separately from local results.
