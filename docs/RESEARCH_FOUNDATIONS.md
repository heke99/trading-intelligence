# Four bounded source and research foundations

This delivery adds four distinct capabilities while the project remains in Phase 1. They are callable offline with invented responses; source access, dataset admission and model training are separate acceptance steps.

| Capability | Concrete behavior | Scope boundary |
| --- | --- | --- |
| Daily price GET capture | Explicit Alpaca paper route, bounded symbols/dates/pages, raw daily IEX/SIP responses and durable partial-page capture | Provider publication, account identity, rights and historical completeness are not inferred |
| SEC submissions adapter | Identified read-only public submissions reader, original response preservation and distinct filing/acceptance/observation fields | Recent submissions are not a complete filing archive; acceptance is not asserted as public availability |
| Artifact and incident lineage | Immutable artifact payload/dependency manifests and append-only incident history with downstream impact | Dependency integrity is not model quality or independent source certification |
| Prediction and outcome queue | Predictions locked before a positive horizon, validated mature labels, cutoff selection and immutable corrections | No predictive model, fitting, automatic learning or promotion |

Run all four without network or credentials:

```sh
PYTHONPATH=src python -m trading_intelligence research-foundations-demo --out /tmp/ti-research-foundations
```

The output contains four separate result objects and explicitly reports no authenticated access, training, LEAN replay or orders. The examples preserve the synthetic source class even when exercising an injected HTTP transport. They are tests of the contracts, not evidence of genuine feed quality or a genuine market session.

Live read-only source commands require preconfigured source permissions and their explicit runtime environment. They do not create entitlements or source permission records. Do not put keys or private raw captures into this repository. See the source-specific documents for bounds and provenance.

This foundation must precede model training. A future training job still needs an independently admitted dataset, explicit training rights, frozen label definitions, chronological partitions, overlap controls, registered trials and a compatible immutable bundle. Evaluation labels supplied by this prototype are not a training authorization. The next engine acceptance remains an admitted data slice followed by a frozen numerical baseline through LEAN and a reconciled cash ledger; this delivery does not execute that step.
