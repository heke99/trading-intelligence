# Rebuild status

Date: 2026-10-20. Masterplan: 1.1. Package: 0.2.0.

## Reset completed

PR #10 merged the reviewed clean planning foundation into `main`, replacing the prior Collective2 application. The recovery point remains:

- Repository: heke99/trading-intelligence
- Previous default-branch commit: `8c5056112721345540ea1cfbbca1f4c41fa816e8`
- Archive branch: `archive/collective2-v0.1-before-equities-2026-10-20`
- Reset merge commit: `b8537c234eacebfd1156ca432739e308b5d9de46`

Parent history is preserved. Original exports, external databases and accounts were outside the cleanup scope.

## First implementation slice

The Python package implements explicit issuer/instrument/listing contracts, exact historical listing mappings, versioned original-byte evidence, correction references, repeatable ingestion and default-denied declared source uses. The CLI demonstrates one synthetic correction in an offline SQLite store. See [contract details](FOUNDATION.md).

This is partial Phase 1. It does not complete the masterplan's data ingestion or replay acceptance requirements.

| Capability | Status |
| --- | --- |
| Masterplan, analysis scope and build sequence | Documented |
| Issuer, share-class/instrument and equity/ETF listing contracts | Implemented locally |
| Versioned raw evidence and historical identifier queries | Implemented locally |
| Declared storage/research/training permissions | Implemented as metadata; independent entitlement review required |
| Offline synthetic correction demo | Implemented and checked |
| Exchange calendars and corporate actions | Not implemented |
| SEC, price, news and NAV adapters | Not implemented |
| Real equity/fund data entitlement | Not verified |
| Trader-history completeness or verification | Not implemented or verified |
| New datasets approved for training | None |
| AI analysis, forecasts, labels and self-learning | Not implemented |
| Backtesting and strategy profitability | Not implemented or established |
| UI, broker or fund order adapters | Not implemented |
| Simulated or live orders | Not executed |

## Verification

32 offline synthetic regression tests passed locally on Python 3.12.14. They test the new foundation, not the old importer or the replacement trading platform end to end. An offline CI workflow is configured for Python 3.11, 3.12 and 3.13; configured jobs are not evidence that remote CI has passed.

## Next milestones and acceptance

1. Add calendar contracts, processing-availability timestamps, immutable receipt observations and a SEC adapter with synthetic replay fixtures. First real ingestion remains gated on source terms and operational configuration.
2. Select a market-data feed against coverage, timestamps, corporate actions, delisted securities and storage rights. Add price/news adapters and a separate NAV contract. Do not assume that public access permits model training.
3. Demonstrate split, rename, article-revision and timezone replay. Add artifact dependencies, an outcome queue and incident lineage before the first model.
4. Implement source-backed analysis and simple frozen strategy baselines; then evaluate chronologically with costs before introducing candidate learning.
5. Add shadow/paper operation, portfolio risk and reconciliation. Live trading requires the separate scope and evidence in the masterplan.

Masterplan 1.1's learning cycle, incident categories, adaptive evaluation, model-promotion bounds and state-preserving rollback remain requirements for those later phases.
