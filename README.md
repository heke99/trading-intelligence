# Trading Intelligence

Rebuild for equities, ETFs, ordinary mutual funds and futures with source-backed AI analysis, reproducible research and independently controlled execution.

**Current status: identity/evidence, futures, multi-broker drafts and a read-only broker reference importer in Phase 1.** The package implements explicit identities, versioned evidence, declared source-use permissions and historical identifier lookup, versioned futures reference snapshots and offline opening-intent previews and persistent broker-specific drafts. The Alpaca paper reference reader is implemented but has not been tested against an authenticated account. Market feeds, AI models, backtesting, UI and broker order submission remain unimplemented.

Read the [Swedish masterplan](docs/MASTERPLAN_SV.md), [implemented contracts and limitations](docs/FOUNDATION.md) and [rebuild status](docs/REBUILD_STATUS.md).

## Run the offline example

Use Python 3.11 or later from the repository root. The offline demos and tests need no runtime dependencies, API keys or network calls. The separate alpaca-sync command requires configured paper credentials and an explicitly permitted source.

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

Masterplan 1.4 specifies locked predictions, delayed validated outcomes, incident classification, bounded retraining, challenger evaluation and controlled promotion. **Self-learning is planned and has not been implemented.**

Version 1.4 also requires a pre-outcome human decision journal, exposure-linked hedge policies, hedge lifecycle controls and separate risk/result attribution for the unhedged portfolio, hedge and combination. These are documented requirements, not implemented features. A new hedge requires its own mandate and risk checks; lower portfolio exposure does not make it an instrument-level reduce-only order or permit it to bypass stops.

The futures example uses invented contract terms, margin and sessions. It checks an opening scenario and demonstrates blocked invalid inputs. No orders, fills, margin reservations or actual exchange calendar are produced. See [futures contracts and limits](docs/FUTURES.md).

The broker demo prepares one canonical instrument in two invented native formats with separate account/environment namespaces. Retries and reopening reuse stored drafts. These are test adapters, not IBKR/Alpaca integrations, and no orders are sent. See [multi-broker contracts](docs/BROKERS.md).

The read-only import keeps raw bytes and receipt/processing times, verifies expected account identity and quarantines invalid/ambiguous rows. It never creates instrument bindings, account trading capabilities or training approval. See [reference import configuration and limits](docs/BROKER_IMPORTS.md).

## Recovery point

The previous Collective2 application remains at commit `8c5056112721345540ea1cfbbca1f4c41fa816e8` and branch `archive/collective2-v0.1-before-equities-2026-10-20`. The clean reset was merged in PR #10 and the first offline data foundation in PR #11. Futures reference support was merged in PR #12 and the multi-broker draft foundation in PR #13. Git history is preserved; no external datasets or accounts were deleted.

## Normalized daily market records

A new offline Phase 1b slice imports supplied daily sessions, raw OHLCV bars, split ratios and cash-dividend observations with evidence lineage and processing availability. Historical replay requires matching known session/bar records and never invents a missing day. See [market-data contracts and limits](docs/MARKET_DATA.md). This is not a live feed, authoritative calendar import, corporate-action cash ledger or completed Phase 1b.

## Supplied vendor captures and bounded replay

Alpaca-shaped daily-bar responses can now be staged with raw bytes, explicit listing mappings and durable quarantine. Unknown publication/session times stay unknown; staging does not admit a price to historical replay. Multi-day replay over an explicit date list produces a gap report and hashed snapshot manifest. See [market pipeline scope and limits](docs/MARKET_PIPELINE.md).

```bash
PYTHONPATH=src python3 -m trading_intelligence market-pipeline-demo --out data/market-demo
```

## Corporate-action and identity replay proofs

Bounded offline proofs now cover temporal identifier schedules and raw-price corporate-action valuation with explicit opening inputs. Rename mappings preserve listing/instrument lineage, and later corrections stay separate from earlier knowledge snapshots. See [corporate replay scope and limits](docs/CORPORATE_REPLAY.md). These proofs do not establish real-data admission or a broker cash ledger.

```bash
PYTHONPATH=src python3 -m trading_intelligence corporate-replay-demo --out data/corporate-demo
```

## Next build steps

Complete the first bounded Phase 1 data slice with authoritative calendars/reference imports, admitted equity prices and corporate actions, and reproducible data-quality/replay checks. Continue the auditable SEC, news, contract-level futures and separate NAV contracts according to their own source admission requirements. Add artifact lineage, an outcome queue and incident records before any predictive model is trained.

Phase 2 runs a frozen simple numerical baseline through LEAN with reconciled fills, positions, cash and costs before a larger AI/graph build. LEAN remains the first engine trial; NautilusTrader is an alternative and Qlib a later research option. Phase 3 adds futures settlement, rolling and exposure-linked hedge simulation. Phase 4 adds source-backed analysis and the human journal, then compares AI, graph and human contributions chronologically against the frozen baseline. New contracts may be specified earlier; executable features require their phase's acceptance evidence. Later shadow/paper operation and a second broker adapter must establish operational behavior before separately authorized live trading.

See [project instructions](AGENTS.md) before implementation. Test success on synthetic fixtures establishes these local contracts, not investment performance or production readiness.
