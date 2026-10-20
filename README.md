# Trading Intelligence

Rebuild plan for an equities, ETF and mutual-fund research platform with source-backed AI analysis, reproducible quantitative research and independently controlled execution.

**Current status: planning foundation.** The new ingestion services, UI, models, backtester and broker connections have not been implemented. There is no live-trading capability in this branch.

Read the complete [Swedish masterplan](docs/MASTERPLAN_SV.md). It covers the architecture, data contracts, open-source choices, analyses, strategy hypotheses, trader-history workflow, fund pricing, validation, portfolio controls and phased implementation.

## Rebuild scope

- Start with liquid equities and eligible ETFs, excluding leveraged, inverse and single-stock products in the pilot.
- Separate intraday, event/swing and long-term strategy books.
- Treat ordinary mutual funds as NAV subscription/redemption instruments with fund- and distributor-specific dealing rules.
- Use timestamped immutable evidence and historical instrument identities.
- Keep AI research tools separate from deterministic risk checks and broker order submission.
- Validate simple baselines before adding machine learning or human-trader demonstrations.

## Previous foundation

The prior read-only Collective2 importer remains at commit `8c5056112721345540ea1cfbbca1f4c41fa816e8` and branch `archive/collective2-v0.1-before-equities-2026-10-20`.

Its application code, examples, tests and importer-specific documentation are intentionally removed from this rebuild branch. The parent Git history remains intact. No private datasets or external storage are deleted by this change.

Useful data-integrity concepts may be reintroduced after review. Collective2 is an optional data adapter in the new product, not its core architecture. Prior synthetic tests and published test counts do not verify the new platform.

## Next implementation milestone

Phase 1: instrument identities, market calendars, source rights and versioned raw-data ingestion. Deliver replay and data-quality evidence before adding predictive models. Broker choice, market-data contracts and live risk settings remain explicit later decisions.

See [rebuild status](docs/REBUILD_STATUS.md) and [project instructions](AGENTS.md).
