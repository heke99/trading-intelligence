# Four-part synthetic hedge lifecycle proof

This delivery connects the existing hedge research/reservations to canonical
broker intent contracts, latest route controls and an immutable callback journal.
It is a fault-injection harness, **not a second strategy/order engine**. LEAN
remains the first strategy-engine boundary. No networking, broker adapter call,
real paper order, live order, account permission or trading result is produced.

## 1. Frozen intent linked to a reservation

`HedgeIntentStore.create_intent(intent_id, reservation_id)` checks fresh research
readiness, the selected alternative, reserved search hash, exact full route and
expiry-specific contract. It reuses `OrderIntent`, `InstrumentTarget`,
`BrokerAccount` and the existing deterministic client-order-ID function. Only
paper routes and synthetic-labelled hedge input packets enter this harness.

One reservation can bind only one intent. Changed IDs cannot duplicate it.
The stored intent freezes signed quantity, raw limit, tick/multiplier, contract
terms snapshot, source search/reservation hashes, client ID and validity window.
Validity includes input/analysis/portfolio expiry, entry cutoff and maximum quote/
state ages. A newer terms version requires new research rather than silent reuse.
Archived intent retries are audit retrievals, not a fresh dispatch check.

## 2. Current supplied route controls before a simulated claim

`HedgeControlStore.record_controls(control_id, evidence_id)` registers original
synthetic JSON with exact keys `route`, `mode`, `observed_at`, `expires_at`,
`max_contracts`, `allowed_contract_ids`, `policy_version`. Routes include broker,
connection, account and paper environment. Modes are active, paused and hard_stop.
New control versions need a later actual processing time; latest versions govern
new claims. Scope and expiry are explicit, not inferred from a broker name.

`dispatch_check(intent_id)` rechecks reservation readiness, current source rights,
intent validity, the latest route controls, quantity/contract limits and current
futures reference versions. A new margin/schedule/binding/terms revision blocks
an old draft. The result binds the checked control and intent hashes. Processing
past its validity boundary blocks the claim. These supplied synthetic controls
are not actual account capabilities, approved strategy mandates or aggregate
portfolio risk authorization. Both `execution_authorized` and broker sends remain
false/zero.

## 3. Durable claim and synthetic callback journal

`HedgeSimulationStore.claim_dispatch(intent_id)` atomically stores exactly one
synthetic claim with unknown status before any authored callback. It has no
transport. Retrying after crash/restart returns that original claim and does not
create another. This is a local transactional proof, not exactly-once delivery to
an external broker. No broker failover exists.

`inject(intent_id, event_id, kind, ...)` accepts accepted/fill/unknown/cancelled/
rejected test callbacks. IDs are globally unique per database; internal dispatch/
abandon ID namespaces cannot be consumed by callbacks. Exact duplicates return
the original record; conflicting duplicates fail. New cumulative filled quantities
must strictly increase and never exceed requested quantity. Prices must satisfy
the pinned tick and limit. Remaining/signed filled quantities derive from those
authored observations, not requested size.

Late fills are recorded even after stop, expiry or source-right revocation. A
late partial fill after cancellation/rejection does not reopen remaining order
quantity. A full cumulative fill ends filled. Delayed acceptance cannot revive a
terminal cancelled/rejected state. Unknown status blocks any new claim by retaining
the original durable claim. Journal sequence, hashes, previous-record links and
operational timestamps are verified across restart and clock rollback.

A bound reservation cannot be released through the ordinary research API. Only
an **unsent** intent can `abandon()`; the simulator may then append an explicit
local research release. Once claimed, even a fully filled/cancelled/rejected
synthetic intent remains locked. A complete execution/position reconciliation and
close-out reservation lifecycle is still future work. No real broker margin is
released by any of these methods.

## 4. End-to-end/restart proof

```sh
PYTHONPATH=src python -m trading_intelligence hedge-simulation-demo --out data/hedge-simulation
```

The offline command builds the existing fictional event/facility/opportunity/hedge
chain, reserves a three-contract short alternative, freezes an intent and supplied
controls, claims once, records acceptance and a partial fill, then unknown status.
A fresh database connection retries the claim, records cancellation and a late
full cumulative fill. Expected final state is filled, signed quantity −3, zero
remaining, one synthetic claim and zero broker orders/network calls. A fresh
process reproduces the exact report. CI runs this command with no secrets or
network. Test callbacks are not verified broker fills, realistic fill models,
exchange-session execution evidence or strategy performance.

Tests additionally cover concurrent claims, stops/missing controls, quantity and
contract restrictions, stale inputs, newer margin revisions, processing expiry,
limit/tick/overfill rejection, duplicate conflicts, rejected/cancelled late fills,
source revocation, abandonment/release, journal corruption and time rollback.

No settlement cash ledger, realized PnL, fees/variation-margin accounting, actual
position import, external paper transport or live eligibility is claimed. Those
requirements and the frozen forward pilot remain unchanged.
