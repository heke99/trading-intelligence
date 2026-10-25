# Artifact dependencies and incident lineage

`ArtifactRegistryStore` extends the offline evidence foundation. It stores immutable nonempty artifact bytes and typed dependency bindings. It does not execute artifact content, train models, validate investment results or authorize orders.

## Registration and availability

```python
artifact = store.register_artifact(
    artifact_id="features-v1", kind="features", payload=b'{"fixture":1}',
    known_at=declared_time,
    dependencies=[{"kind":"evidence", "id":evidence_id}],
)
```

Use a new artifact ID for every changed version. `kind` is a required descriptive type label, not proof of a valid trained model. At least one dependency is required. Supported references are existing evidence (`kind/evidence,id`), raw bytes with explicit backing evidence (`kind/raw,id=<sha256>,evidence_id`) and an existing artifact (`kind/artifact,id`). Missing, future, duplicate and cyclic bindings are rejected. Raw references require evidence to establish source/use metadata; mere byte existence is insufficient.

Original bytes are content-hashed. The artifact manifest binds type, declared knowledge time, operational registration/availability time and dependency hashes/metadata. Dependencies must be available at the declared knowledge time. The registry samples its operational clock; an old caller-supplied `known_at` never backdates `available_at`. Clock injection supports synthetic tests. Supplied `current_at` must match the operational clock exactly and cannot override current-use checks.

`get_artifact(id, as_of=...)` verifies the manifest, original bytes, recursive dependency bindings and research permissions both at the historical dependency cutoff and at current operational time. It is an **audit read**, not approval to train or deploy. `require_usable_artifact(id, as_of=...)` additionally blocks artifacts with confirmed current invalidation even when the requested audit cutoff predates the incident. Queue/evaluation consumers should use that method when accepting material. Source permission declarations remain metadata; independent entitlement/admission checks are still required.

## Append-only incidents and corrections

`record_incident(...)` requires an ID, description, declared knowledge time, explicit affected typed references, category and confirmation flag. Categories are `data`, `extraction`, `execution`, `policy` and `forecast_loss`. An unconfirmed report is a hypothesis. Ordinary forecast loss never automatically invalidates a model. Confirmed non-loss incidents identify affected lineage without rewriting artifacts.

`impact_as_of(as_of=...)` verifies registered artifacts/events and returns the transitive affected artifact IDs. Invalidation starts only when the incident was operationally registered, not its possibly older declared discovery time. Original artifact bytes and historical reports remain unchanged. An evidence incident also reaches a raw dependency bound to the same evidence; a raw incident reaches evidence dependencies using those bytes.

`record_correction(correction_id=..., incident_id=..., replacement_artifact_id=..., known_at=..., description=...)` links a new immutable replacement to an available original incident. A replacement that still depends on affected lineage is rejected. The correction does not delete the old incident, clear old artifact invalidation, promote a model or rewrite actual account state. `corrections_as_of(...)` returns the append-only history and verifies replacement bindings. Retry with identical inputs reuses the first registration; changed input under the same ID is a conflict.

Read savepoints preserve caller transactions. Registry writes require an idle connection and do not commit unrelated caller work. SQLite direct modification, deletion or recomputing unkeyed hashes is outside this API integrity boundary: this is not a tamper-proof archive, external access-control service or independently verified historical clock.

## Synthetic demonstration and limits

`artifacts_demo(directory)` in `trading_intelligence.artifacts_demo` creates an invented source, dataset and dependent features. A later confirmed source correction affects both original artifacts; a new dataset version and separate correction record preserve the old history. All examples/tests are synthetic and all training/live flags remain false.

Tests cover immutable hashes, dependency availability, actual registration time, missing/self/cyclic dependencies, recursive corruption, current rights revocation, typed cross-reference impact, confirmed versus hypothetical/loss incidents, correction history, transaction isolation and repeatable demonstration output. Production migrations, concurrent writers, durable operational incident ingestion, independently verified clocks and full training-admission integration remain separate work.
