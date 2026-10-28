# Event intake and facility context

This is the first runnable Phase 1c slice of the [event-intelligence design](EVENT_INTELLIGENCE_SV.md). It connects public disaster observations to the existing source archive and canonical company/listing identities. It is not a predictive model, licensed financial-news integration, economic-impact model or broker order transport.

## What runs

- Public read-only USGS GeoJSON and GDACS RSS adapters, with explicit versioned format dispatch. Original response bytes remain in the existing raw_objects archive. Unknown publication stays unknown.
- Immutable captures, provider revisions, quarantine and actual operational availability. A late old revision cannot overwrite a newer known state. Conflicting revision content remains visible with capture/hash lineage.
- Supplied, evidence-backed facility assertions with separate owner/operator relationships and an optional explicit canonical listing. Economic validity and actual registration availability are distinct. Corrections preserve earlier knowledge snapshots.
- Great-circle proximity under a caller-declared investigation radius, accompanied by provenance and uncertainty. The radius is not an estimated damage footprint. Facility validity is checked at event occurrence; ongoing-event duration/footprint analysis is future work.
- A continuous polling command that saves capture/context reports and can recover on the next poll after an expected source failure. Startup configuration failures are rejected before transport. A malformed feed does not republish cached context as a fresh observation.

There is no hardcoded rule mapping a disaster to long or short, no fixed winner/loser list and no AI confidence threshold. New event types can retain their source identity. New formats need an explicit parser so the system can understand their timestamps and revisions correctly.

## Existing components reused

| Existing component | Connection in this slice |
| --- | --- |
| EvidenceStore | Same SQLite database, sources, declared usage history, original raw_objects, entity/instrument/listing identities and facility backing evidence |
| EventStore | Additive event capture/version/conflict tables, avoiding invented publication dates in the older evidence_versions contract |
| EventContextStore | Dated supplied facility relationships and geographic investigation packets |
| LEAN and frozen price baseline | Kept as the existing future execution/evaluation boundary; no event targets are injected into the forward pilot |
| ArtifactRegistryStore / OutcomeQueueStore | Existing foundations remain available; typed event-capture dependency binding and event prediction/outcome registration are not implemented in this slice |
| Broker/futures contracts | Canonical identities remain separate from broker symbols; there is no submit, cancel, long/short or hedge authority in this event layer |

The intake/context code uses the Python standard library. The additive [scenario analysis layer](EVENT_ANALYSIS.md) can now call OpenAI Responses from an explicitly configured `event-analyze` command; collection alone does not call an LLM. No additional trading engine is installed.

## Offline demonstration

From the repository root:

```sh
PYTHONPATH=src python3 -m trading_intelligence event-intelligence-demo --out data/event-demo
```

The invented event initially lies near an invented company's documented facility. A later source correction moves it away. The current context changes from investigate to observe; an earlier historical query still returns the original version. A USGS tsunami flag remains an unconfirmed source flag. Rerunning the same directory after a process restart reproduces the exact report.

All demo records are synthetic. Geographic proximity does not establish physical damage, production loss, financial exposure or a tradable return.

## Source configuration and one public capture

Use a dedicated event database or the existing research database. Source registration and use declarations are operator configuration, not independent certification of the provider's terms. Only declare uses for which the intended source/product has been reviewed. This example declares storage/research for the selected public feeds; it grants no training, financial-news or live-trading rights.

```sh
PYTHONPATH=src python3 - <<'PY'
from datetime import datetime, timezone
from pathlib import Path
from trading_intelligence.contracts import DataOrigin, Use
from trading_intelligence.event_context import EventContextStore

Path('data').mkdir(exist_ok=True)
with EventContextStore('data/events.sqlite3') as store:
    for source_id in ('usgs-events', 'gdacs-events'):
        store.register_source(source_id, DataOrigin.PROVIDER)
        store.set_permissions(source_id, known_at=datetime.now(timezone.utc),
                              uses={Use.STORAGE, Use.RESEARCH})
PY

PYTHONPATH=src python3 -m trading_intelligence event-sync \
  --database data/events.sqlite3 --source-id usgs-events \
  --import-id usgs-first-capture --feed all_hour

PYTHONPATH=src python3 -m trading_intelligence event-sync \
  --database data/events.sqlite3 --source-id gdacs-events \
  --import-id gdacs-first-capture --feed gdacs
```

Create the data directory first if needed. Use a new import ID for a new capture. Reusing an existing ID returns the archived capture without a network call; changing its feed/provenance is a conflict. Endpoint allowlisting governs this adapter's transport, not the future analysis universe.

USGS choices are all_hour, all_day, all_week and all_month. GDACS uses its official all-event RSS feed. The source namespace is explicit: USGS and GDACS observations about the same physical incident are not automatically clustered or counted as independent confirmations. GDACS preserves aggregation uncertainty and supplied resource-source names; original-source resolution remains incomplete.

## Continuous collection

```sh
PYTHONPATH=src python3 -m trading_intelligence event-watch \
  --database data/events.sqlite3 --source-id usgs-events --feed all_hour \
  --radius-km 100 --poll-seconds 60 --out data/event-watch-usgs

PYTHONPATH=src python3 -m trading_intelligence event-watch \
  --database data/events.sqlite3 --source-id gdacs-events --feed gdacs \
  --radius-km 100 --poll-seconds 360 --out data/event-watch-gdacs
```

An omitted iteration limit means collect until interrupted. Add --iterations 1 for one bounded run. Each poll gets a unique import ID and an exclusive report filename. Ctrl-C preserves already committed captures. Restart creates a new run; previously observed native revisions remain deduplicated. Polling is synchronous, so analysis duration adds to the configured delay. There is no daemon installation, heartbeat service, distributed lease or production availability claim.

Only events observed in the current capture produce fresh context reports. Per-event ambiguity from quarantine is explicit. Failed polls write an unavailable report without stale context or an order proposal. Unexpected programming defects propagate. Loss of an entire feed is not evidence that a disaster has ended. This command does not monitor or exit positions.

## Facility assertions and historical context

Register canonical entities/listings and preserve the supporting original document using the existing evidence API. Then register an explicit relation:

```python
store.put_facility(
    assertion_id='facility-assertion-v1', facility_id='reviewed-facility-id',
    entity_id='existing-canonical-entity', latitude=35.0, longitude=139.0,
    evidence_id='existing-original-document-evidence-id',
    valid_from=effective_time, known_at=knowledge_time,
    relationship='operator', listing_id='existing-canonical-listing')
```

The placeholder identities above must be replaced by registered, reviewed evidence. Facility/ownership claims are supplied assertions; this API does not automatically extract, verify or discover real facility records. A later assertion needs a new ID and supersedes pointing to the preceding version. A corrected assertion replaces that relation's full validity interval; it does not invent a complete ownership schedule. Sources with unknown publication need a future capture-compatible facility-evidence binding; the older document API cannot be filled with a guessed publication time.

```sh
PYTHONPATH=src python3 -m trading_intelligence event-context \
  --database data/events.sqlite3 --source-id usgs-events \
  --event-id ACTUAL_NATIVE_EVENT_ID --as-of ACTUAL_UTC_CUTOFF --radius-km 100
```

This command accepts an actual timezone-aware ISO cutoff. It returns investigate, observe or unavailable with provenance, evidence age and explicit uncertainty. No match can mean missing facility coverage, not absence of economic exposure. Current and historical research permissions are both checked; changing the historical cutoff cannot bypass a current revocation. Original bytes and manifests are hash-verified. No real company map ships with the synthetic example.

## Verification and next integration

Tests cover timestamp separation, first operational availability, old late revisions, conflicts, malformed rows, source scoping, revoked rights, corrupted manifests/raw bytes, facility identity/validity, geographic boundaries, restart repeatability and recovery between polls. CI runs the synthetic demonstration; it never requests live data.

A read-only development probe on 28 October 2026 exercised both real adapters in memory: USGS returned five accepted earthquake observations and GDACS 303 accepted observations, with zero quarantined in those two responses. GDACS included earthquake, wildfire, tropical cyclone and drought records. No downloaded raw responses were written or committed. This verifies access and normalization for those specific responses, not rights review, source completeness, data admission, predictive accuracy or continuous reliability.

The next integration connects a licensed news product and reviewed facility/supply relationships, binds typed event snapshots to artifact/outcome lineage, and adds source-backed hypothesis extraction. Economic scenarios and current executable market prices then feed a separately evaluated model. Only the existing deterministic portfolio/risk/LEAN path can later turn an accepted strategy into orders. Short borrowing, futures settlement/rolling, external paper execution and separately configured live operation retain their own required implementations.
