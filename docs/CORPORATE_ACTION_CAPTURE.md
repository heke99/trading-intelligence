# Corporate-action capture bound to a forward dataset

The normalized split/dividend replay proof already exists, but real event capture and coverage remain separate. This delivery adds a bounded GET reader for Alpaca's current `/v1/corporate-actions` API, immutable page/job staging and an exact binding to the latest successful forward price/calendar capture. It does not promote actions into market snapshots, apply them to holdings or clear data-admission requirements.

## One Mac command

In the project with the virtual environment active:

```sh
git pull --ff-only &&
source .env &&
TI_ACTIONS_RUN="$(date -u +%Y%m%dT%H%M%SZ)" &&
PYTHONPATH=src python3 -m trading_intelligence.corporate_actions sync-pilot \
  --database data/research.sqlite3 \
  --pilot-dir "$HOME/ti-forward-20261027T095324Z" \
  --pilot apple-forward-001 \
  --source alpaca-corporate-actions \
  --import-id "apple-actions-$TI_ACTIONS_RUN" \
  --out "$HOME/ti-actions-$TI_ACTIONS_RUN" \
  --declare-storage-research
```

Docker is not needed. The command uses existing locally exported paper keys, matches a fresh GET `/v2/account` response to the frozen paper route, then performs a bounded action-data GET. It does not submit orders or buy a subscription. Account matching is separate from action-endpoint access and data entitlements. A 401/403 is recorded as a failed attempt with a sanitized code; there is no retry, host/feed fallback, deprecated-endpoint fallback or automatic upgrade.

`--declare-storage-research` records the user-declared storage/research uses **only when this new source is first registered**. It is not an entitlement certificate or an independent rights review. The flag never restores revoked uses on an existing source and grants no training rights. Explicitly requested capture writes add the new source/job/pages to the existing database; older imports, pilot protocol and ledger remain unchanged.

The output folder is fresh/private (700, files 600) and contains `price-calendar-inspection.json`, `corporate-actions.json` and `binding-report.json`. Keep it local; these files include observations and route/account context. Terminal summaries do not print keys, raw account bodies or provider error bodies.

## Request and temporal contract

The query is for one explicitly bound equity/ETF listing and symbol, US region, ascending process dates and `data_quality=all`. Ordinary funds and futures are rejected. No type filter is sent: unsupported types must remain visible. Page size is 1,000, default limit ten pages and 20 MB total, with a 2 MB per-response cap. Original bytes, exact query/route, raw SHA256, receipt and processing availability, pagination tokens and normalization results are retained. Only fixed HTTPS endpoints and GET are used; redirects are disabled.

**Alpaca filters this endpoint by `process_date`. This is not an ex-date window.** By default the requested process interval uses the bound price/calendar date range. `--process-start` and `--process-end` can explicitly change that interval for a new import. Wider process-date queries do not establish complete effective-date coverage. Provider creation/publication timing is not guaranteed by the endpoint; unknown publication stays `None`. Event ex, process, record, payment and due-bill dates remain dates, not invented publication/effective instants.

`complete_pages` means a valid terminal page chain was captured and all returned rows fit the bounded staging contract. A valid empty response can have this state. It never certifies no effective events in the strategy period. Missing pagination metadata, token cycles, limits, incomplete requests, quarantined rows and later-page failures remain explicit. Terminal retries verify/reuse saved evidence without fetching; incomplete attempts require a new explicit import ID.

## Supported staging and preserved unknowns

- Forward/reverse splits preserve exact positive `new_rate`/`old_rate` values and enforce the stated split direction.
- Ordinary, nonforeign, nonspecial cash dividends preserve exact amount, separate ex/payment dates and supplied record date.
- Missing provider currency stays unknown; it is not filled from the listing. Due-bill fields and native CUSIP/ISIN values are retained for review. Explicit symbol/listing binding is a caller assertion, not verified historical identity.
- Unsupported action types, special/foreign/incomplete dividends, invalid dates, wrong symbols, out-of-request process dates, malformed JSON and duplicate action IDs are quarantined rather than dropped. Unknown row fields remain in raw evidence and the row fingerprint.

Every candidate retains native ID, provider row fingerprint and availability lineage. A changed event is captured under a new immutable import, without rewriting earlier snapshots or backdating the new information. Missing events in a later response are not inferred to be cancellations. No continuous event/deletion stream or automatic correction application is implemented.

## Dataset binding and remaining acceptance

The CLI verifies the existing forward journal and files, then checks that the selected database's exact current price/calendar scope matches the archived successful forward packet. The action job binds that full scope, listing, symbol and paper route. Its combined manifest cannot be transferred to another price import. Current declared uses are checked on reads as well as writes, including when an old `as_of` is selected.

Even `complete_pages` retains `effective_date_coverage_verified=false`, `publication_verified=false`, `accounting_ready=false`, `dataset_admitted=false`, training/live false and zero orders. Existing source reviews and corporate-action coverage blockers remain. Review of process-to-effective coverage, identifiers, source rights, incomplete/revised events and supported accounting policies still precedes admitted dataset export and real-data LEAN evaluation. Neither a successful GET nor an empty result approves these.

## Verification and primary references

Twenty-five synthetic tests exercise GET/header/redaction boundaries, account mismatch, pagination/duplicates/partial failure, revision availability, unknown currency/due bills, unsupported events/instruments, raw corruption, rehashed false-admission claims, current revocation, exact binding and process/ex-date separation. The local pipeline uses injected readers and invented bytes. Actual Mac action-endpoint access and responses remain pending; no real actions were admitted or applied.

Schema/API checkpoints checked 28 October 2026:

- [Current corporate-actions endpoint, request scope and timing limitations](https://docs.alpaca.markets/us/reference/corporateactions-1).
- [Deprecated announcements endpoint](https://docs.alpaca.markets/us/reference/get-v2-corporate_actions-announcements-1).
- [Official SDK action models](https://github.com/alpacahq/alpaca-py/blob/master/alpaca/data/models/corporate_actions.py) and [grouped response envelope handling](https://github.com/alpacahq/alpaca-py/blob/master/alpaca/common/rest.py).

No SDK dependency or upstream implementation was copied into the package; the reader/normalizer use the standard library and retain a versioned own-written contract.
