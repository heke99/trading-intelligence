# Captured price/calendar observation inspection

`inspect_captures(store, price_source_id=..., price_import_id=..., calendar_source_id=..., calendar_import_id=..., listing_id=..., expected_dates=None, clock=None)` joins an explicit terminal price **job** to a separately identified calendar capture. The sources must be distinct; both require current declared storage and research permissions at the operational clock. There is no historical permission-cutoff override.

The read is performed within a SQLite savepoint and leaves caller writes untouched. It verifies original capture hashes, request/page/result journal hashes, source identities, exact listing/USD bindings, raw daily IEX/SIP semantics, ascending price order, complete known pagination and common paper connection/account provenance. No direct-capture fallback occurs when the price job ID is missing. Quarantined or incomplete inputs, date gaps, inconsistent routes and daily aggregates received before the matched calendar close block inspection.

Dates are either explicitly supplied or taken from the declared calendar candidates within the price job's New York date window. In either case the price/calendar date sets must match exactly. This `observed_dates_only` policy does not infer holidays, omitted sessions, complete price history or authoritative exchange coverage. The calendar venue and listing MIC are preserved separately; a mismatch is visible, and `calendar_applies_to_listing_verified` always remains false. Joining dates does not certify that a vendor daily aggregate represents exactly the regular exchange session.

Output observations preserve source order as explicit `index`, `economic_date`, raw OHLCV strings/currency, declared listing, provider timestamp, calendar boundaries, receipt and processing times, and `published_at=None`. Each `available_at` is the maximum price/calendar processing availability. Tied observations remain distinct and are represented by one `observation_groups` entry with an ordered index list. The observer must emit the group at that availability time, never backdate each price to its economic date.

`verify_inspection(report)` checks frozen report hash, flags, observation shape/timing and grouping. It cannot recheck current database rights, authenticate a provider/account or certify source accuracy. The inspection hash detects changes against the recorded artifact; it is not a signature against a person who can replace the entire report and its hash.

All outputs are marked `inspection_only=True`, `dataset_admitted=False`, `historical_availability_verified=False`, `publication_verified=False`, `training_ready=False`, `full_history_verified=False` and `live_trading=False`. Source origins remain separately reported metadata. No market snapshots, admission decisions, strategy results or training records are created. The source database and full raw responses remain outside any observation-only runtime artifact.

## One-command pinned LEAN inspection

Use the same existing database that contains the successful price job and calendar import. No credentials or downloads are needed for this local capture replay:

```sh
git pull --ff-only
PYTHONPATH=src python3 -m trading_intelligence.captured_smoke prepare-run \
  --database "$EVIDENCE_DATABASE" \
  --price-source alpaca-prices --price-import apple-october-prices-001 \
  --calendar-source alpaca-calendar --calendar-import calendar-october-001 \
  --listing apple-xnas --out "$HOME/ti-captured-observer-001" --timeout 300
```

`EVIDENCE_DATABASE` denotes the existing database path, not a new empty database. The explicit price ID is the synchronization **job** ID; raw page capture IDs are resolved from its verified journal. The exact calendar/price date set is derived from those captured request scopes and compared without a handwritten date list or invented holiday calendar.

This reuses the pinned smoke image, disabled networking, dedicated read-only input/writable output, UTC normalization, final-state checks and zero-order assertions from [LEAN_SMOKE.md](LEAN_SMOKE.md). The existing database is opened read-only and never mounted into Docker. Only normalized inspection observations and their provenance/hash report are copied. Source-use declarations are checked at preparation; they are not independent entitlement certification. The frozen bundle cannot discover a later database permission change by itself.

All rows with the exact same recorded availability are delivered as **one custom-data event containing an ordered observation group**. The algorithm expands the original rows without inventing epsilon timestamps, treating historic bar dates as current information or collapsing rows that share symbol/time. The custom point's placeholder value is not an executable market price. Economic dates, raw OHLCV, distinct source/capture IDs, receipt/processing times, unknown publication and declared calendar/listing venues remain inspectable. A venue mismatch is reported as unverified applicability, never converted into an execution calendar.

The result requires exact expanded observations and group count, no early engine clock, fresh artifacts, unchanged inputs, no orders and a clean LEAN final Completed state. Even a passed result has `inspection_only=true`, `dataset_admitted=false`, `real_dataset_admitted=false`, `training_ready=false` and `publication_verified=false`. This is a technical observation-propagation proof, **not** historical strategy evaluation, data admission or model-training approval.

## Prior engine evidence and this delivery's limits

The user reported that the Mac synthetic smoke `ti-lean-smoke-002` passed with two observations, zero orders, the pinned ARM64 image and input-manifest SHA256 `8b3dd050dadf3f134282a2579f3e675c72075a772f42b6cd4815739e8968e6b9`. These are user-reported runtime results; the Mac files were not independently copied/reverified in this development environment. That synthetic success does not certify the provider captures.

This new capture-inspection path has offline mocked/invented regression coverage. Docker is unavailable here. Acceptance of the actual 17-row capture run remains pending its own Mac result and logs. Full real-data admission still needs independent source rights/provenance/coverage/temporal review and must not fabricate publication from bar timestamps or receipt.

## LEAN's completed-day limit: captured observer001

The actual Mac captured observer001 started LEAN and loaded its local file, but its effective backtest ended on 25 October while every captured observation arrived on 26 October. It processed no observation group and failed acceptance. This is not a passed capture run or a missing-row repair opportunity.

The pinned upstream public `QCAlgorithm.SetEndDate` overloads clamp the end to the previous day in the algorithm's timezone. This observer deliberately uses UTC. There is no supported same-day override in that contract. The harness now checks before Docker: latest observation UTC day must be strictly earlier than the operational UTC day. Otherwise it writes `run-result.json` with `status=not_yet_replayable`, `container_started=false` and `backtest_window.earliest_eligible_utc`. The algorithm independently verifies the actual end returned by LEAN and saves `output/window-evidence.json`, detecting a host/container clock mismatch before subscribing.

For the existing captures known on **26 October**, earliest eligibility is **27 October 2026 at 00:00 UTC (01:00 Stockholm)**. Do not fetch new prices/calendar first: a new capture would move availability to the new day and restart this completed-day restriction. Preserve directory001. At or after that boundary, run the same existing captures in a fresh directory:

```sh
git pull --ff-only
PYTHONPATH=src python3 -m trading_intelligence.captured_smoke prepare-run \
  --database "$EVIDENCE_DATABASE" \
  --price-source alpaca-prices --price-import apple-october-prices-001 \
  --calendar-source alpaca-calendar --calendar-import calendar-october-001 \
  --listing apple-xnas --out "$HOME/ti-captured-observer-002" --timeout 300
```

No observation is backdated, no epsilon is added, and no private field, fake clock, timezone workaround or live-mode bypass is used. The requested end is the original latest availability date; actual engine coverage is checked. If a premature invocation already created a blocked directory, use another new dedicated directory rather than overwriting evidence.

Primary contract: https://github.com/QuantConnect/Lean/blob/f3d841e60dfd010ee5fc293ea893e56952484108/Algorithm/QCAlgorithm.cs (`SetEndDate(DateTime)` and its integer wrapper). Tests simulate the real yesterday clamp, exact UTC midnight eligibility and clock skew. Docker remains unavailable here; the next Mac acceptance remains unverified.
