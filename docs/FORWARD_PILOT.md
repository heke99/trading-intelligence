# Frozen forward observation pilot

This prepares a future observation protocol and collects account-matched raw captures while real-data admission remains unresolved. It does **not** execute the baseline rule against real data, simulate fills, compute strategy returns, place Alpaca paper/live orders or enable training. No second order engine is introduced. A paper brokerage account is not certification of a market-data plan or usage rights.

## Prepare once on the Mac

In the project with its virtual environment active:

```sh
git pull --ff-only
source .env
TI_FORWARD_DIR="$HOME/ti-forward-$(date -u +%Y%m%dT%H%M%SZ)"
PYTHONPATH=src python3 -m trading_intelligence.forward_pilot prepare \
  --database data/research.sqlite3 --out "$TI_FORWARD_DIR" --pilot apple-forward-001 \
  --price-source alpaca-prices --price-import apple-october-prices-001 \
  --calendar-source alpaca-calendar --calendar-import calendar-october-001 \
  --listing apple-xnas --lookback 5
```

Preparation reads the existing evidence database read-only. It does not fetch new data or modify earlier captures. The new private directory contains `protocol.sqlite3`, `plan.json`, `seed-inspection.json` and `initial-assessment.json`. Keep it outside the repository. Directory/file modes are 700/600. A fresh directory is required; do not overwrite an earlier pilot.

The existing `BaselineStore` freezes `close_gt_sma`, five-bar lookback, zero-target exit, benchmark and next-explicit-session policy. Initial commission `$1`, spread `2` bps, slippage `1` bp and latency `1` second are frozen **test assumptions**, not verified Alpaca costs and not yet applied. The Python API accepts explicit alternative assumptions at preparation; later changes require a new protocol. No risk mandate or order authorization is created.

The plan binds the existing seed's complete two-source snapshot, canonical listing, symbol, feed, paper route and declared calendar venue. The seed is marked warmup-only and not admitted. The 60-day collection window begins at actual operational registration, which cannot be backdated through the CLI. This is preparation for a future experiment, not a claim that a final-test period has been independently preregistered or untouched.

## Collect one new observation

After preparation succeeds, use the same directory and existing locally exported keys:

```sh
PYTHONPATH=src python3 -m trading_intelligence.forward_pilot collect \
  --database data/research.sqlite3 --out "$TI_FORWARD_DIR" \
  --pilot apple-forward-001 --collection first
```

This is an explicit provider GET capture. Unlike `prepare`, it appends immutable captures to the existing evidence database and private pilot files. It preserves the old October imports. The collector:

1. Verifies frozen files, journal, original seed in the selected database, listing and current declared storage/research uses before networking.
2. Reserves the collection ID transactionally so concurrent calls cannot both fetch.
3. Reads the fixed **paper** `/v2/account` endpoint and requires `account_number` to match the frozen route. The response must have been received within this attempt. The original response is archived privately; credentials are never archived or printed.
4. Captures the source calendar through 14 days ahead, preserving the originally declared venue. It selects the latest session on a date **before the current New York date**, with a declared close already passed. Even after regular close, today's date is excluded; this is a conservative capture policy, not a claim of final provider publication or revision completeness.
5. Fetches daily raw prices through that date with the frozen symbol/feed, retaining bounded pagination, raw bytes and true receipt/processing times. It does not fall back to another feed/account.
6. Reassesses the exact new two-source captures for `forward_observation`, archives the packet and records an **abstention** because real dataset admission is not established. Declared review eligibility cannot turn on strategy execution.

`collection_recorded` means account matching and capture mechanics completed. It is not a passed trading simulation. `post_registration_rows=0` is expected if every fetched session closed before preparation; a new receipt of old prices cannot become a prospective outcome. Even positive `post_registration_rows` counts only chronology; it does not verify data admission or independence.

Repeat collections explicitly with new IDs, for example `--collection "daily-$(date -u +%Y%m%d)"`. No background schedule is installed by these commands. Reusing a terminal ID returns its saved result without fetching again. An interrupted attempt remains incomplete and requires inspection and a new ID. A recorded failure also remains immutable; changing keys and retrying its ID does not silently create a different capture.

## Verify status and failures

```sh
PYTHONPATH=src python3 -m trading_intelligence.forward_pilot status \
  --out "$TI_FORWARD_DIR" --pilot apple-forward-001
```

The status command verifies baseline/plan/seed/initial-assessment bindings, the event hash chain and referenced account/capture-packet files. It shows completed, failed and incomplete attempts. A failed collection reports a sanitized stage/type, not credential headers, raw account data or arbitrary exception text. Partial source captures and proof files are preserved for review. Hashes detect changes relative to the saved journal; they do not replace protected write access, source certification or an external timestamp authority.

Only terminal JSON summaries should be shared. Raw account proof files and inspection packets remain local. `account_match_verified` describes the successful GET comparison at that attempt, not current credentials, market-data entitlements or independent certification.

All current paths retain zero orders, `strategy_execution_enabled=false`, `dataset_admitted=false`, `training_ready=false` and `live_trading=false`. Source-specific rights/reviews, corporate-action coverage, an admitted forward slice, frozen-rule execution in LEAN and reconciled cash/cost accounting still precede strategy evaluation. Do not switch these flags manually. The complete trading robot is not finished by preparing or collecting this pilot.

## Verification

Twenty synthetic regressions cover immutable configuration, unchanged source bytes on prepare, prospective chronology, current New York day exclusion, account matching/freshness, revoked uses, seed corruption, failure redaction/partial captures, interrupted and terminal retries, concurrent reservation, expiry/clocks, journal/proof corruption, private files, default local credential wiring and an actual prepare/status CLI subprocess. API readers are injected test doubles; no real account or new LEAN engine run was exercised in development.
