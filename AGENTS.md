# Project instructions

The user's approved direction is a rebuild for equities, ETFs, ordinary mutual funds and a separate futures flow. Read docs/MASTERPLAN_SV.md and docs/REBUILD_STATUS.md before implementing a phase. Masterplan 1.5 also includes docs/QUANT_COMPETITIVE_PLAN_SV.md; its A–H packages clarify dependencies and acceptance, not completed capabilities.

- This branch implements early Phase 1 identity/evidence, offline broker/futures contracts and an explicit read-only paper reference reader. Do not claim services, strategies, trader-history access, model training or live trading are implemented until they are independently verified.
- Preserve the archive branch and parent history. Never force-push the default branch or delete private source evidence as part of cleanup.
- Broker routes include broker, connection, account and paper/live environment. Never infer account-level capability from a broker name or automatically fail over after an ambiguous order outcome. Offline drafts are audit records, not risk approvals; revalidate before any later real transport.
- Keep entity, share class, listing and broker instrument identity separate. Ambiguous symbol matches block order routing.
- Broker reference imports preserve original bytes, route/source lineage and distinct receipt/processed availability. Do not fabricate provider publication/economic time, promote imported flags into trading permissions or call authenticated access verified without an actual permitted account test.
- Store immutable raw evidence, revisions, known-at times, timezones, source classes and usage rights. Unknown values remain unknown.
- Separate synthetic fixtures, hypothetical strategy history, paper fills and verified brokerage fills. Gate research datasets per intended use and do not silently enable training_ready or full_history_verified.
- Keep the AI reader unable to place orders or access broker secrets. Deterministic portfolio/risk/execution controls own order submission.
- Record human hypotheses and interventions before their outcomes, with actor, original model proposal, action, sources, decision time, expiry and immutable revisions. Evaluate model-only and model-plus-human decisions on the same opportunities, risk and costs; keep simulated counterfactual results separate from actual fills.
- Futures use separate products and explicit expiry contracts. Keep continuous series out of execution prices. Version tick/multiplier/price-unit, expiry, delivery boundaries, sessions, broker bindings and account-specific margin evidence. The first futures preview supports linear fixed-tick cash settlement only and cannot authorize live orders. Aggregate risk, variation margin, rolling and reconciliation remain required before execution.
- A hedge requires a versioned policy linking it to verified exposure, a residual-risk target, instrument selection, rebalancing/exit rules and its own mandate. Track hedge and protected exposure through partial fills, rejections, sales and rolls. Broker reduce_only and reduced portfolio risk are different: a new hedge can increase gross exposure and cash requirements and must not bypass pause rules, account limits or hard order stops. Evaluate unhedged portfolio, hedge and combination separately, including basis risk and account-specific liquidity.
- Ordinary funds require their own cutoff, forward NAV, subscription/redemption and settlement logic. Do not reuse intraday equity fills for funds.
- Keep intraday, event/swing and long-term books separate while aggregating account exposure and reconciling with the broker.
- Complete an admitted data slice, then run a frozen simple numerical baseline through the LEAN replay and cash ledger before a larger AI/graph build. LEAN remains the first engine trial; NautilusTrader is an alternative and Qlib a later research option. Do not install parallel authoritative order engines.
- Build artifact dependencies, outcome definitions/queue and incident lineage before predictive model training. The human journal and hedge contracts are requirements in masterplan 1.4, not evidence of implemented capabilities.
- Record all model trials, use chronological evaluation, prevent label overlap and fit preprocessing only on training data. Register source snapshots, model/prompt/code versions and execution assumptions.
- Log predictions before outcomes; learn only from matured validated labels known before the training cutoff. Corrected labels get their own availability time and must not be double-counted.
- Distinguish data, extraction, execution and policy defects from ordinary forecast losses. Preserve append-only incidents, corrections and affected-artifact lineage; AI postmortems are hypotheses rather than training truth.
- Evaluate the complete adaptive process against a frozen baseline. A final test period consumed by selection is no longer untouched for subsequent candidates.
- Keep automatic model promotion within a versioned preconfigured policy; start in paper_only. Candidates cannot increase risk mandates, rewrite evaluation gates or deploy code freely.
- Deploy compatible immutable bundles of model, features, calibration and policies. Rollback preserves external trades and account state; keep executable exit-handler versions for open positions.
- Hard order stops override strategy modes. Pauses for risk increase may allow separately permitted reducing actions only with verified exposure and pending-order state. Always process late fills and status events.
- Use current official documentation and pinned dependencies. Retain upstream licenses/NOTICE. Review external skills before adoption and install only components used in the current phase.
- Tests and CI use synthetic or explicitly permitted non-sensitive fixtures. Never commit API keys, real trader exports, generated databases, model artifacts or licensed raw datasets.
- Run checks appropriate to the changed phase. Add regression coverage for meaningful defects; do not fabricate product tests for documentation-only changes.
- Paid subscriptions, data purchases, account modifications and live order activation require explicit scope and configuration; do not perform them as incidental verification.
- Report implemented, tested, simulated and planned work separately, with concrete evidence and remaining limitations.

## Competitive quant evidence requirements

- Register model/checkpoint and possible parametric look-ahead contamination. Historical document cutoffs alone do not establish uncontaminated LLM forecasts. Use prospective locked outcomes or a verified point-in-time model protocol for confirmatory claims.
- Bind confirmatory family statistics to the complete registered campaign and verified aligned losses. Free arrays, omitted failed candidates or unknown family completeness cannot authorize promotion.
- Keep relation evidence, economic mechanism and forecast separate. Common ownership is not proof of supply-chain dependence or causal impact; grounded text spans are not truth certificates.
- Map connection aliases to canonical external accounts before aggregate reservation or sending. A namespace is not proof that two routes represent different economic accounts.
