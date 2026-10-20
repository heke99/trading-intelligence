# Read-only broker reference import, version 0.5.0

This implements the first vendor-specific reader: Alpaca Trading API paper-account and asset reference GETs. It also provides normalization and an immutable raw/processed import store. No authenticated account or vendor entitlement has been verified in this delivery. Tests use invented responses and injected HTTP fakes, never a real key or account.

## Implemented path

`AlpacaReferenceReader` accepts credentials at runtime and exposes only `read("account")` and `read("assets")`. It constructs exact HTTPS GET URLs on paper-api.alpaca.markets; callers cannot supply an arbitrary path, host or method. Redirects are refused, TLS certificate validation remains enabled, responses must be JSON with HTTP 200, timeout is bounded and body size is capped at 20 MB. Errors omit response bodies and credential values. There is no retry/failover, live-host selection or order endpoint.

These restrictions are software behavior, not read-only vendor credential permissions or an isolation sandbox. Injected transport/clock objects are for trusted local testing. Keep credentials outside the repository and outside AI research tools. The reader does not obtain credentials, sign in, modify accounts or activate paper/live order submission.

`BrokerImportStore.sync_alpaca` checks an existing account route and declared storage/research rights before fetching account and asset responses. Import compares the expected account UUID and account number; a mismatch quarantines the entire normalized bundle. A source or expected-account change cannot reuse a completed batch ID. Completed retries read their original batch without repeating HTTP requests; use a new import ID for a new observation.

The normalization rules follow the reviewed wire/model fields but do not establish complete API-schema coverage. Account status, blocking flags and reported balances are recorded; absent fields stay null, not false/zero. Native US-equity asset IDs, symbols, exchanges and reference flags are retained without guessing a canonical target, stock-versus-ETF classification, MIC, account capability or default tick/lot. Other asset classes and malformed rows are quarantined. Duplicate IDs or symbol/exchange identities quarantine all ambiguous members. Non-finite decimals, invalid UUIDs, string booleans, conflicting class aliases and duplicate JSON keys are rejected.

The normalized state may be normalized_reference, review_required or quarantined. Every report keeps training_ready=false and trading_authorized=false. Missing/inactive/blocking flags are review findings, not permission decisions. Imported balances are observations, not available/reserved capital for routing. No NativeBinding or BrokerCapabilities is created, so import success cannot enable a draft or order.

## Raw archive and temporal integrity

Original bytes are hashed and stored in the existing raw_objects archive. New additive broker_reference_imports rows bind account, source, batch, expected native account, normalizer version, raw response hashes, endpoint provenance and receipt times to the normalized result. The input envelope and result are hashed and verified alongside original bytes on reads. Cross-account envelope copies and altered receipts/parameters are rejected.

The processed available_at is captured after normalization, never before either receipt. Queries before this time return no normalized result, even if the raw response has arrived. Provider publication/economic timestamps are null because these endpoints do not establish them. We do not fabricate them from response receipt or HTTP Date, and do not insert these captures into the older event-evidence table that requires a known publication time.

BrokerRead(source_url=None) marks supplied/local bytes rather than a verified HTTP capture. Supplied receipt times and injected clocks are caller assertions; importing an old-looking file cannot independently prove historical availability. Production still needs controlled operational clocks, receipt logging, current entitlement enforcement, access controls, retention and backup. Hashes/append-only APIs are not a security boundary against an actor rewriting the database.

A failed HTTP request publishes no complete batch. Partial fetches and transport failures do not yet have a durable attempt log; a first successful response is not archived if the second GET fails. This implementation archives successful two-response captures, including malformed payloads that normalize to quarantine. It is not a continuous synchronization daemon or a complete historical broker catalogue. No market/calendar data, orders, fills or positions are fetched.

## Run without credentials

```bash
PYTHONPATH=src python3 -m trading_intelligence reference-import-demo --out data/reference-demo
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The invented demo normalizes one asset, quarantines an unsupported asset and shows that receipt does not backdate processing availability. Rerunning/reopening preserves the same result.

## Configure an actual paper read locally

Only use a private database and explicitly permitted source. Register the exact paper route and source before invoking sync. For example, adapt this setup in local Python using your real account number, connection ID and the source-use rights you have reviewed:

```python
from datetime import datetime, timezone
from pathlib import Path
from trading_intelligence.broker_imports import BrokerImportStore
from trading_intelligence.brokers import BrokerAccount, Environment
from trading_intelligence.contracts import DataOrigin, Use

Path("data").mkdir(exist_ok=True)
with BrokerImportStore("data/broker-reference.sqlite3") as store:
    store.register_account(BrokerAccount("alpaca", "my-paper", "YOUR_ACCOUNT_NUMBER", Environment.PAPER))
    store.register_source("my-permitted-alpaca-reference", DataOrigin.PROVIDER)
    store.set_permissions("my-permitted-alpaca-reference", known_at=datetime.now(timezone.utc),
                          uses={Use.STORAGE, Use.RESEARCH})
```

Set ALPACA_PAPER_API_KEY and ALPACA_PAPER_SECRET_KEY in your local secret environment. Do not put them in command arguments, source, fixtures or chat. The CLI then reads only the paper reference endpoints:

```bash
PYTHONPATH=src python3 -m trading_intelligence alpaca-sync \
  --database data/broker-reference.sqlite3 \
  --connection-id my-paper \
  --account-number YOUR_ACCOUNT_NUMBER \
  --expected-account-id YOUR_ACCOUNT_UUID \
  --source-id my-permitted-alpaca-reference \
  --import-id UNIQUE_CAPTURE_ID
```

CLI output is a summary without balances or raw account data. This command has not been executed against an authenticated account during development. Credentials/API access, user eligibility and dataset training rights remain unverified.

## Next work

Add durable failed/partial-attempt receipts and access-controlled admission into independently verified canonical mappings/capabilities. Then implement a second vendor reader through the same route/evidence contracts, licensed market data, authoritative sessions and portfolio/risk/reconciliation before order transport. Futures remain on their separate expiry/margin/settlement path; this reader does not claim futures support from a US-equity catalogue.

Primary documentation reviewed 20 October 2026:

- [Alpaca account GET](https://docs.alpaca.markets/us/reference/getaccount-1)
- [Alpaca asset GET](https://docs.alpaca.markets/us/reference/get-v2-assets-1)
- [Alpaca authentication and environments](https://docs.alpaca.markets/us/docs/authentication)
- [Alpaca account/asset models](https://alpaca.markets/sdks/python/api_reference/trading/models.html)

No upstream SDK code is copied or installed; runtime dependencies remain Python standard library only.
