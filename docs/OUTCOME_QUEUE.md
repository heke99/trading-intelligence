# Locked predictions and delayed outcomes

`OutcomeQueueStore` extends `ArtifactRegistryStore` with an offline prediction/outcome queue. It does not train models, approve datasets or submit orders. All added tests and the demo use invented source material.

## Frozen definition and prediction

`record_definition` creates an immutable `(definition_id, version_id)` with an explicit target, unit, benchmark, price/cost convention, permitted outcome origin and a positive `horizon_seconds`. This bounded implementation uses elapsed UTC seconds, **not trading-day calendars**. A five-calendar-day fixture is not evidence of correct five-session handling.

`record_prediction` binds the definition version, strategy/policy versions, feature artifact ID/hash, and either a finite `Decimal` forecast or explicit `action='abstain', value=None`. The operational clock assigns `decision_at`, availability and `label_end`; callers cannot supply a historical decision timestamp. The definition and feature artifact must already be available. Reusing a prediction ID returns the original locked record only if its semantic inputs match. Changing a prediction requires a new ID.

Artifact links verify original bytes, dependency hashes, cutoff availability and source-use declarations. Confirmed current lineage invalidation blocks use even for an old cutoff. Ordinary forecast losses and unconfirmed hypotheses do not invalidate a prediction automatically. Original audit records are retained.

## Delayed labels and corrections

`record_outcome` takes an outcome ID, prediction ID, explicit `status` (`validated`, `unavailable` or `quarantined`), origin, validation artifact ID/hash, reviewer and reason. A validated value must be a finite `Decimal`, and may be recorded only once the frozen horizon has elapsed. Unavailable/quarantined outcomes use `None`; missing data is never replaced with zero.

Availability is assigned by the operational clock. A correction receives a new outcome ID and its own availability, and must reference the latest outcome with `correction_of`. Same-time corrections and branching replacements are rejected. Correction of invalidated label material can reference the old immutable outcome record while providing clean new validation lineage; the invalidated material is not restored or reused as eligible data.

`queue_as_of(as_of=...)` returns locked predictions available at the cutoff, with pending/awaiting-outcome or explicit outcome states. `evaluation_labels(as_of=...)` returns at most one latest matured validated revision per prediction. A later unavailable/quarantined correction removes that prediction from eligible evaluation labels instead of falling back to its old valid label. Earlier cutoff queries retain the earlier revision, subject to current rights and confirmed lineage invalidation. Reads use a savepoint and do not commit the caller's transaction.

The label's origin must match its frozen definition, and its validation artifact's complete dependency lineage must support that origin. Synthetic evidence cannot become provider, paper or verified-broker outcomes through an outcome flag or nested artifact wrapper. Hypothetical market outcomes may use provider or hypothetical evidence; synthetic fixtures must remain explicitly synthetic.

**`validated` is an audited reviewer assertion supported by linked material, not an automatic proof of economic correctness or independently authenticated fills.** The source-origin and permission declarations still need independent admission review. Neither queue inclusion nor `eligible_for_evaluation` grants model-training permission; `training_ready` stays false. No model, adaptive strategy or realized trading-performance claim is implemented.

## Callable synthetic example

```python
from trading_intelligence.outcome_queue import outcomes_demo
report = outcomes_demo("data/outcomes-demo")
```

The repeatable example writes an ignored local SQLite database and report: prediction at day zero, no eligible label after one day, a matured synthetic label after five elapsed days and a corrected revision one day later. Both final and earlier cutoffs contain a single eligible revision, not two independent observations. The report states `training_implemented=False`, `training_ready=False` and `live_trading=False`.

Production still requires authoritative horizon calendars when appropriate, actual observation/validation pipelines, independent provenance/admission, trusted clock operations, access controls, retention, scheduling, and statistical evaluation before any model can consume labels. Direct SQLite mutation can bypass append-only APIs and is not a security boundary.
