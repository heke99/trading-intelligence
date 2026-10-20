# Trading Intelligence

Rebuild for equities, ETFs and ordinary mutual funds with source-backed AI analysis, reproducible research and independently controlled execution.

**Current status: first offline slice of Phase 1.** The package implements explicit identities, versioned evidence, declared source-use permissions and historical identifier lookup. It has no external data feeds, AI models, backtester, UI, broker connection or order submission.

Read the [Swedish masterplan](docs/MASTERPLAN_SV.md), [implemented contracts and limitations](docs/FOUNDATION.md) and [rebuild status](docs/REBUILD_STATUS.md).

## Run the offline example

Use Python 3.11 or later from the repository root. No runtime dependencies, API keys or network calls are needed.

```bash
PYTHONPATH=src python3 -m trading_intelligence demo --out data/demo
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The example writes an ignored local SQLite database with invented records. A later source correction changes the resolved listing while the earlier historical query still returns its original answer. Rerunning the example preserves the same versions and counts. `training_implemented` and `live_trading` remain false.

`pyproject.toml` also defines an installable package and the `trading-intelligence` CLI. Building the package requires the pinned build backend; the source commands above require only Python's standard library.

## Product boundaries

- Keep entity, share class and exchange listing identities separate; ambiguous symbols raise an error.
- Keep original bytes and revision lineage; old publication dates never backdate first receipt.
- Deny undeclared data uses. Permission and provenance declarations still require independent verification before real datasets are admitted.
- Keep ordinary mutual funds on a separate NAV subscription/redemption model. Their dealing engine is not implemented.
- Separate intraday, event/swing and long-term books, with deterministic aggregate risk control in later phases.

Masterplan 1.1 specifies locked predictions, delayed validated outcomes, incident classification, bounded retraining, challenger evaluation and controlled promotion. **Self-learning is planned and has not been implemented.**

## Recovery point

The previous Collective2 application remains at commit `8c5056112721345540ea1cfbbca1f4c41fa816e8` and branch `archive/collective2-v0.1-before-equities-2026-10-20`. The clean reset was merged in PR #10. Git history is preserved; no external datasets or accounts were deleted.

## Next build steps

Complete Phase 1 with exchange calendars, an auditable SEC adapter, licensed price/news imports, corporate actions and a separate NAV contract. Add artifact lineage, an outcome queue and incident records before any predictive model is trained. Demonstrate replay and data-quality acceptance checks before strategy work.

See [project instructions](AGENTS.md) before implementation. Test success on synthetic fixtures establishes these local contracts, not investment performance or production readiness.
