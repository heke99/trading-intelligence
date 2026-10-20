# Trading Intelligence

Rebuild for equities, ETFs, ordinary mutual funds and futures with source-backed AI analysis, reproducible research and independently controlled execution.

**Current status: identity/evidence, futures, multi-broker drafts and a read-only broker reference importer in Phase 1.** The package implements explicit identities, versioned evidence, declared source-use permissions and historical identifier lookup, versioned futures reference snapshots and offline opening-intent previews and persistent broker-specific drafts. The Alpaca paper reference reader is implemented but has not been tested against an authenticated account. Market feeds, AI models, backtesting, UI and broker order submission remain unimplemented.

Read the [Swedish masterplan](docs/MASTERPLAN_SV.md), [implemented contracts and limitations](docs/FOUNDATION.md) and [rebuild status](docs/REBUILD_STATUS.md).

## Run the offline example

Use Python 3.11 or later from the repository root. The four demos and tests need no runtime dependencies, API keys or network calls. The separate alpaca-sync command requires configured paper credentials and an explicitly permitted source.

```bash
PYTHONPATH=src python3 -m trading_intelligence demo --out data/demo
PYTHONPATH=src python3 -m trading_intelligence futures-demo --out data/futures-demo
PYTHONPATH=src python3 -m trading_intelligence brokers-demo --out data/brokers-demo
PYTHONPATH=src python3 -m trading_intelligence reference-import-demo --out data/reference-demo
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The example writes an ignored local SQLite database with invented records. A later source correction changes the resolved listing while the earlier historical query still returns its original answer. Rerunning the example preserves the same versions and counts. `training_implemented` and `live_trading` remain false.

`pyproject.toml` also defines an installable package and the `trading-intelligence` CLI. Building the package requires the pinned build backend; the source commands above require only Python's standard library.

## Product boundaries

- Keep entity, share class and exchange listing identities separate; ambiguous symbols raise an error.
- Keep original bytes and revision lineage; old publication dates never backdate first receipt.
- Deny undeclared data uses. Permission and provenance declarations still require independent verification before real datasets are admitted.
- Keep ordinary mutual funds on a separate NAV subscription/redemption model. Their dealing engine is not implemented.
- Futures have separate product/expiry/broker identities, raw prices, tick/multiplier, dated sessions and account margin snapshots. Physical delivery is excluded from the opening-intent pilot.
- Separate intraday, event/swing and long-term books, with deterministic aggregate risk control in later phases.

Masterplan 1.3 specifies locked predictions, delayed validated outcomes, incident classification, bounded retraining, challenger evaluation and controlled promotion. **Self-learning is planned and has not been implemented.**

The futures example uses invented contract terms, margin and sessions. It checks an opening scenario and demonstrates blocked invalid inputs. No orders, fills, margin reservations or actual exchange calendar are produced. See [futures contracts and limits](docs/FUTURES.md).

The broker demo prepares one canonical instrument in two invented native formats with separate account/environment namespaces. Retries and reopening reuse stored drafts. These are test adapters, not IBKR/Alpaca integrations, and no orders are sent. See [multi-broker contracts](docs/BROKERS.md).

The read-only import keeps raw bytes and receipt/processing times, verifies expected account identity and quarantines invalid/ambiguous rows. It never creates instrument bindings, account trading capabilities or training approval. See [reference import configuration and limits](docs/BROKER_IMPORTS.md).

## Recovery point

The previous Collective2 application remains at commit `8c5056112721345540ea1cfbbca1f4c41fa816e8` and branch `archive/collective2-v0.1-before-equities-2026-10-20`. The clean reset was merged in PR #10 and the first offline data foundation in PR #11. Futures reference support was merged in PR #12 and the multi-broker draft foundation in PR #13. Git history is preserved; no external datasets or accounts were deleted.

## Next build steps

Complete Phase 1 with exchange calendars, authoritative session imports, an auditable SEC adapter, licensed contract-level and equity price/news imports, corporate actions and a separate NAV contract. Add artifact lineage, an outcome queue and incident records before any predictive model is trained. Demonstrate replay and data-quality acceptance checks before strategy work.

See [project instructions](AGENTS.md) before implementation. Test success on synthetic fixtures establishes these local contracts, not investment performance or production readiness.
