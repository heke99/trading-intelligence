# Calendar adapter and declared data-admission gate

This delivery implements a bounded Alpaca paper calendar GET reader, a strict legacy-calendar format importer, and persistent purpose/scoped review checks. It does not establish authenticated account access, actual source entitlement, historical availability or an admitted dataset. The current environment has no configured Alpaca paper credentials; live response format has not been tested against an authenticated account.

## Runnable read-only calendar adapter

`AlpacaCalendarReader(route, key_id, secret_key).read(start_date, end_date)` exposes only `GET https://paper-api.alpaca.markets/v2/calendar` with explicit canonical inclusive dates, `date_type=TRADING` and at most 366 days in the documented legacy 1970–2029 range. The route must be an explicit Alpaca paper broker/connection/account namespace. Runtime keys are never included in repr/errors. Redirects, unexpected endpoints, compressed/non-JSON responses, oversized bodies and invalid HTTP status are rejected. No order endpoint or broker failover is implemented.

`sync_calendar(...)` checks the declared provider source's current storage/research permissions before requesting data. It preserves raw response bytes, receipt/processing times and endpoint/query/route metadata through `AlpacaCalendarStore.import_calendar(...)`. A completed capture retry reuses its original result without refetching; changed route/query/venue is a conflict. `declared_http_get` records request context, not proof that the keys belong to the declared account. Calendar responses do not verify account identity.

Configure runtime credentials locally as `ALPACA_PAPER_API_KEY` and `ALPACA_PAPER_SECRET_KEY`. Create the source and its approved use declarations separately; the CLI never enables them automatically. Then the bounded adapter is runnable:

```bash
PYTHONPATH=src python3 -m trading_intelligence calendar-sync \
  --database /private/path/research.sqlite3 \
  --source-id approved-calendar-source --import-id calendar-capture-001 \
  --connection-id paper-connection --account-number declared-paper-account \
  --start-date 2026-10-01 --end-date 2026-10-25 --venue XNYS
```

The example is a command template, not a claim that the source/account above exists or that a request was made. Keys stay in the local environment. Source review, data terms and account identity checks remain separate requirements.

## Explicit legacy calendar format

The importer accepts supplied original JSON bytes containing a legacy array of `date`, `open` and `close` fields. HH:MM open/close fields are explicitly interpreted in America/New_York; UTC instants preserve daylight-saving changes and early closes. Declared venues are limited to supported US equity calendars. TRADING and SETTLEMENT calendars are not interchangeable. Newer `/v3/calendar/{market}` UTC/multi-market response shapes require another normalizer and are rejected here.

Each capture retains request bounds, raw SHA-256, format/version, staged candidates and durable quarantine. Duplicate/out-of-range/invalid dates, malformed response shapes and invalid or ambiguous local times are not silently accepted. Retries and reads verify raw/result/quarantine integrity. Neither missing dates nor an empty list certifies holidays or coverage. `calendar_complete` remains false. The provider publication time is unknown and remains `None`; receipt is not relabelled as publication.

## Persistent review gate

For separate real price/calendar sources and synchronization jobs with multiple pages, use the [captured admission assessment](CAPTURED_ADMISSION.md). It binds an exact version-2 inspection scope and reuses the immutable review records without treating a declared review as dataset promotion. The legacy single-source `assess` contract below remains unchanged.

`DataAdmissionStore` inherits both price and calendar capture stores. `record_review(...)` appends immutable, evidence-linked assertions for four separate axes: rights, provenance, temporal basis and coverage. Each review binds purpose, reviewer, operational recording time, expiry and an exact scope: bar/calendar import IDs and raw hashes, listing, venue, date range and feed. Corrections use a new review ID and later recording time. A review cannot be backdated or written in a caller transaction.

`assess(source_id=..., scope=..., intended_use=..., as_of=...)` evaluates the historical snapshot and a separate current operational clock. Current storage/research declarations and the latest nonexpired reviews are required as well as historically appropriate ones. A later denial, expired review or revoked source permission cannot be bypassed with an old dataset cutoff. Production must protect review identities, clock and write permissions; this offline store does not independently certify a reviewer or legal entitlement.

Supported purposes:

| Purpose | Gate meaning and limits |
| --- | --- |
| synthetic_validation | Only explicit synthetic origins, for validating the contract; never real-data admission |
| forward_observation | Declared provider origin, four applicable reviews and receipt/processing basis; eligibility is still a caller-declared policy report |
| historical_replay | Unknown publication/vintage is a hard denial, even if a temporal review says allow |

Quarantined rows, incomplete/unknown price pages, capture hash mismatch, listing/feed/venue mismatch and price/calendar date mismatch cannot be approved away by review flags. A daily bar captured before the supplied regular session closes is denied even if processing or assessment occurs later. This is a necessary timing screen, not independent certification of the feed's complete aggregation window or revision semantics; those still require the scoped reviews.

The output is an eligibility report with independent axes and explicit reasons. It performs **no promotion** into market snapshots, grants no training/order rights and leaves training/full-history/live flags false. A provider-origin declaration and filled review fields alone are not evidence of genuine data quality.

## Offline demonstration and verification

```bash
PYTHONPATH=src python3 -m trading_intelligence admission-demo --out data/admission-demo
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The repeatable demo stages invented daily bars and an invented early-close calendar. It shows missing reviews denied, synthetic validation allowed only within its explicit purpose, historical replay denied for unknown publication, and a current denial blocking an earlier cutoff. The operational clock is injected for this labelled fixture. No real source is approved and no market snapshots/orders are created. CI runs the demo on Python 3.11–3.13.

Current acceptance work still includes real authenticated calendar capture, account matching where required, independently reviewed source terms, proven provider timestamp/vintage semantics, actual historical universe/action coverage, controlled record promotion and the first LEAN baseline. These checks are not replaced by additional synthetic tests.

Official references checked for this implementation:

- Legacy Trading calendar endpoint and request semantics: https://docs.alpaca.markets/us/v1.4.2/reference/getcalendar-1
- Calendar field/time and early-close description: https://alpaca.markets/sdks/python/api_reference/trading/calendar.html
- Legacy field schema: https://github.com/alpacahq/bkdocs/blob/master/assets/openapi.yaml
- New separate multi-market calendar endpoint: https://docs.alpaca.markets/us/reference/calendar-2
