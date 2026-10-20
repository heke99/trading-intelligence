# Rebuild status

Date: 2026-10-20

## Scope of this change

This is a clean planning foundation for a rebuild of Trading Intelligence. It replaces the prior Collective2-focused code tree with a new product direction and implementation plan. It does not implement the replacement product.

## Recovery point

- Repository: heke99/trading-intelligence
- Previous default-branch commit: 8c5056112721345540ea1cfbbca1f4c41fa816e8
- Archive branch: archive/collective2-v0.1-before-equities-2026-10-20
- Parent history is preserved. Original exports, database storage and external accounts are outside this repository cleanup.

## Current capability status

| Capability | Status |
| --- | --- |
| Masterplan and build sequence | Documented |
| New application implementation | Not implemented |
| Equity or fund data entitlement | Not verified |
| Real trader-history completeness | Not verified |
| New datasets approved for training | No |
| Strategy profitability | Not established |
| Broker or fund order adapter | Not implemented |
| Simulated or live orders | Not executed |

## Validation for this change

Documentation consistency, source references, file inventory and the proposed tree are reviewed for this planning change. Old runtime tests are removed with the old application and do not certify the replacement. This change must not be described as a passing end-to-end test of a trading platform.

## Next phase

Implement Phase 1 from docs/MASTERPLAN_SV.md: identity contracts, calendars, source registry, immutable evidence and first ingestion adapters. Demonstrate temporal replay and data-quality checks before progressing to models or execution.
