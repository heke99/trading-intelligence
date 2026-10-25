# Bounded SEC submissions adapter

This slice adds public read-only `GET https://data.sec.gov/submissions/CIK##########.json`, an immutable raw-response store and recent-filing metadata normalization. SEC states that its data APIs require no API key. Runtime requests still require an identified User-Agent/contact and compliance with fair access. No real request is made unless an operator configures the contact and explicitly runs the adapter.

`SecSubmissionsReader(user_agent).read(cik)` accepts an explicit nonzero ten-digit CIK. The endpoint is fixed; no provider-selected URL, query, redirect, write request or fallback is supported. Timeout is bounded, responses require uncompressed JSON and original bytes are limited to 10 MB. HTTP errors, including 429, fail without automatic retries or exposing response details. The default process-wide limiter permits at most five request starts per second; multiple processes/deployments require a shared external limiter. An injected opener/clock/limiter exists for labelled offline tests and is not proof of actual SEC access.

`SecFilingsStore.import_submissions(source_id=..., import_id=..., captured=SecRead(...), processed_at=...)` requires declared storage and research permissions, retains raw bytes and separate receipt/processing availability, and persists an integrity-protected result. Quarantined envelope/row errors remain in that archived result. Changed bytes/times under the same import ID conflict. Restart/retry returns the verified original capture; imports reject a caller transaction rather than committing unrelated work.

`submissions_as_of(source_id, import_id, as_of=...)` exposes a capture only once processing is complete and verifies raw/manifest hashes. Historical source declarations are checked at that cutoff for audit, as in the existing evidence prototype. Current entitlement and data-admission gates still apply before operational reuse; this reader does not grant training rights or independent source certification.

`sync_sec(store, source_id=..., import_id=..., cik=..., reader=..., clock=...)` requires an explicitly declared provider source and checks current permissions before network or retry. It never enables source permissions automatically. The fixed source URL, CIK and capture origin are recorded. Constructed fixtures default to `supplied_bytes`; the bounded reader marks `declared_http_get`. Synchronization rejects a supplied capture masquerading as an HTTP retry. These tags declare request context, not independently authenticated transport attestation.

## Metadata and time

The documented recent-submissions array is columnar. All columns must be arrays with matching lengths. The response CIK must match the explicit request; an accession is validated as an accession identifier, **not** assumed to identify the issuer by its prefix (a filing agent can have a different CIK).

Each staged row preserves accession number, form, primary document name, filing date, report date and raw acceptance datetime. A report date is an economic period, not publication. A filing date has day precision and is not expanded into an invented time. Empty report dates remain unknown. Acceptance timestamps require an explicit timezone/offset and normalize to UTC; naive/ambiguous values and acceptance after capture receipt are quarantined rather than assigned an assumed zone.

**SEC acceptance is not treated as independently verified dissemination/publication.** `published_at` stays `None`. SEC documents that some accepted filings are disseminated the following business day. No `evidence_versions` publication is manufactured from acceptance, filing date or receipt. Historical availability/vintage remains unverified.

Additional historical submissions files are inventoried by their constrained names, matching CIK and ordered date ranges, never automatically fetched. Their presence or absence does not certify full history. Amendments remain separate accession rows; this does not merge document versions or infer which original filing they supersede. Filing-document download, XBRL extraction, complete historical ingestion, deletions/corrections, issuer/listing mapping, signals and trading are separate work.

## Runnable fixtures and verification

The `sec_demo(directory)` helper creates invented response bytes for a synthetic source and makes zero network requests. The combined `research-foundations-demo` CLI runs that helper; `sec-sync` is the separate configured source command. Runtime User-Agent configuration must use the operator's actual organization/contact; no identity is supplied or inferred by the demo.

Tests cover exact endpoint/CIK, contact validation, request limit invocation, response bounds/redirect/header errors, HTTP/connection failure, strict column alignment, naive/future acceptance times, invalid document paths, duplicate accessions, unknown publication, raw/manifest persistence, permissions, processing order, retry/restart and caller transactions. All test fixtures are invented; passing them is not proof of network access, complete filings or historical admissibility.

Official references consulted:

- SEC data API endpoint, CIK padding and recent/archive structure: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC fair access, identified User-Agent, rate ceiling, dissemination and corrections: https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data

## Configured CLI

Preconfigure a provider source with explicit storage/research permission, and set `SEC_USER_AGENT` locally to the application/organization name and an actual contact email. The command does not infer an identity or create source permission:

```sh
PYTHONPATH=src python -m trading_intelligence sec-sync \
  --database /path/to/research.sqlite3 --source-id configured-sec \
  --import-id submissions-001 --cik 0000320193
```

This command fetches only the bounded recent-submissions response and inventories any archive references. It does not follow those references or download filing documents.
