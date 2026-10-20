# Project instructions

The user's approved direction is a rebuild for equities, ETFs and ordinary mutual funds. Read docs/MASTERPLAN_SV.md and docs/REBUILD_STATUS.md before implementing a phase.

- This branch is a planning foundation. Do not claim services, strategies, trader-history access, model training or live trading are implemented until they are independently verified.
- Preserve the archive branch and parent history. Never force-push the default branch or delete private source evidence as part of cleanup.
- Keep entity, share class, listing and broker instrument identity separate. Ambiguous symbol matches block order routing.
- Store immutable raw evidence, revisions, known-at times, timezones, source classes and usage rights. Unknown values remain unknown.
- Separate synthetic fixtures, hypothetical strategy history, paper fills and verified brokerage fills. Gate research datasets per intended use and do not silently enable training_ready or full_history_verified.
- Keep the AI reader unable to place orders or access broker secrets. Deterministic portfolio/risk/execution controls own order submission.
- Ordinary funds require their own cutoff, forward NAV, subscription/redemption and settlement logic. Do not reuse intraday equity fills for funds.
- Keep intraday, event/swing and long-term books separate while aggregating account exposure and reconciling with the broker.
- Record all model trials, use chronological evaluation, prevent label overlap and fit preprocessing only on training data. Register source snapshots, model/prompt/code versions and execution assumptions.
- Use current official documentation and pinned dependencies. Retain upstream licenses/NOTICE. Review external skills before adoption and install only components used in the current phase.
- Tests and CI use synthetic or explicitly permitted non-sensitive fixtures. Never commit API keys, real trader exports, generated databases, model artifacts or licensed raw datasets.
- Run checks appropriate to the changed phase. Add regression coverage for meaningful defects; do not fabricate product tests for documentation-only changes.
- Paid subscriptions, data purchases, account modifications and live order activation require explicit scope and configuration; do not perform them as incidental verification.
- Report implemented, tested, simulated and planned work separately, with concrete evidence and remaining limitations.
