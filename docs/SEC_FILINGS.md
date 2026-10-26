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

## Relative document-path correction (normalizer v2)

`sec-submissions-recent-2` preserves legitimate relative primary-document paths such as `xslF345X05/ownership.xml` and `xslF345X06/form4.xml`. SEC itself publishes ownership documents under these subdirectories, for example https://www.sec.gov/Archives/edgar/data/1792580/000191567226000011/xslF345X05/ownership.xml . The previous basename-only restriction incorrectly quarantined such rows.

Each ASCII segment permits letters, digits, underscore, hyphen and dot, with no empty, `.` or `..` segments. The path is bounded to 1,024 characters, 16 segments and 255 characters per segment. Absolute paths, URLs, backslashes, percent encodings, query/fragment syntax and unsupported characters remain quarantined. This is a metadata validator; it does not download, decode, resolve or open the selected document path.

Rejected rows now retain `row_index`, a fixed first `reason`/`field`, and `issues` listing all independently detected field errors. Invalid document paths no longer hide invalid dates or acceptance times. No rejected raw value is copied into diagnostic messages. Duplicate accessions retain their own cause. Envelope errors remain distinct from row errors.

Old capture IDs retain their original normalizer version, bytes and normalized report. An unchanged direct retry or `sec-sync` retry returns that archived result; upgrading the code does not repair or overwrite old reports. Use a **new import ID** to normalize another capture with v2. Changed immutable inputs under an existing ID still conflict.

### Actual public-response verification

On 26 October 2026, a permitted identified read-only SEC submissions GET succeeded. Its raw SHA-256 was `5891cf875f690e38f26ca628f7091184c9d73ca34ca7646b9cecd5013aeac4ab`, exactly matching the user's Mac capture. On these identical bytes and the original receipt cutoff, v1 produced 328 accepted rows and 674 quarantined rows. Every quarantined index matched a nested document path. V2 produced 1,002 accepted rows and zero quarantined rows. The original response and user report were not committed to the repository. This verifies the identified compatibility bug for that response; it does not certify future responses, filing completeness, economic correctness, publication/vintage or training eligibility.

### Rerun and inspect a compact summary

After `git pull --ff-only`, keep the existing permitted database and configured `SEC_USER_AGENT`; select a new import ID:

```sh
PYTHONPATH=src python3 -m trading_intelligence sec-sync \
  --database "$SEC_DATABASE" --source-id sec-edgar \
  --import-id apple-submissions-002-v2 --cik 0000320193 \
  > apple-submissions-002-v2.json
python3 - <<'PY'
import json
from collections import Counter
r = json.load(open('apple-submissions-002-v2.json'))
p = r['report']
print({'version': r['version'], 'import_id': r['import_id'], 'raw_sha': r['raw_sha'],
       'accepted': len(p['filings']), 'quarantined': len(p['quarantined']),
       'reasons': dict(Counter(x['reason'] for x in p['quarantined']))})
print('first_issues:', p['quarantined'][:5])
PY
```

Set `SEC_DATABASE` to the same database path used for the first import. The summary deliberately shows any remaining quarantine rather than promising zero errors on a newly fetched response.
