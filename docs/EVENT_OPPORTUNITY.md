# Event price and exposure sensitivity

`EventOpportunityStore` extends the existing event-analysis database. It binds an
available, immutable scenario card to an original evidence document containing
supplied quotes, explicit cost assumptions, scenario exit prices and a dated
broker/connection/account/environment position snapshot. The assessment records
both dependencies, hashes, calculation version, input cutoff and actual completion
availability. Reuse returns the original; corrections need new IDs. Reads verify
raw integrity and current research/storage rights. Writes/read snapshots use the
same transaction boundaries as the analysis store.

This is a **hypothetical sensitivity calculation**, not a calibrated forecast,
expected return, executable quote feed, portfolio risk approval or order draft.
Scenario exit mids are supplied unvalidated assumptions. The LLM's qualitative
mechanism never creates a numeric target or probability here. Every assessment
retains `recommended_action=abstain` and `orders_sent=0`, even if all supplied
price cases show a profit. No OpenAI call, training or new dependency is needed.

## Arithmetic

For quantity q, entry bid B, ask A, terminal midpoint T, entry/exit fees f1/f2,
slippage per leg s, exit half spread h and total horizon borrowing cost b:

- Long incremental PnL: q × (T − A − f1 − f2 − 2s − h).
- Short incremental PnL: q × (B − T − f1 − f2 − 2s − h − b).
- Long/short break-even terminal mids follow the same equations at zero PnL.
- Reducing an existing long compares its immediate sale with holding marked to
  terminal mid: q × (B − T − f1 − s). Covering an existing short compares
  q × (T − A − f1 − s). These use only the immediate closing cost: the reduced
  quantity has no later exit trade. The hold baseline is marked to mid without
  liquidation. These are incremental differences, not realized tax PnL.
- Hold makes no incremental trade and retains existing position risk.

Entry spread is already in ask/bid and is not deducted again. Exit half spread
is separate because targets are mids. Borrowing is the supplied total per unit
for the scenario horizon, not a daily annual rate. Unknown borrowing leaves short
PnL unknown. Availability of a borrow is never inferred from its cost. Taxes,
market impact beyond supplied slippage, funding, FX, dividends, margin and future
borrowing savings from covering remain unassessed. All monetary arithmetic uses
bounded decimal strings and an internal fixed precision independent of the
caller's Decimal context.

A supplied reference mid strictly before event occurrence can show the observed
percentage price change to the current mid. This is not causal attribution or a
measurement of how much information the market has priced in.

## Required evidence and timing

The original evidence JSON has these exact top-level keys:

`listing_id`, `currency`, `quote_at`, `valid_until`, `bid`, `ask`, `quantity`,
`entry_fee_per_unit`, `exit_fee_per_unit`, `slippage_per_unit_per_leg`,
`exit_half_spread`, `borrow_cost_per_unit`, `scenario_exit_mids`, `scenario_exit_at`, `portfolio`,
`pre_event_reference`.

All prices, quantities and costs are decimal **strings**; borrowing may be null.
`scenario_exit_mids` maps exactly the selected canonical listing's scenario IDs
to hypothetical nonnegative exit midpoint strings. `scenario_exit_at` maps the same
IDs to explicit future exit timestamps. Exit spread must not imply a negative bid. `pre_event_reference` is null or
`{mid, observed_at}`. All times are timezone-aware ISO strings. Currency must
match the registered equity/ETF listing; funds and futures do not enter this
intraday equity calculation.

`portfolio` has exact keys `broker`, `connection`, `account`, `environment`
(`paper` or `live`), `observed_at`, `valid_until`, signed `position_units`,
`pending_buy_units`, `pending_sell_units`. Pending quantities may be null to
represent unknown state, which blocks usable comparison. Position-after-fill
figures explicitly exclude pending orders. A reduction is blocked if pending
orders are nonzero/unknown, or quantity would cross or exceed the position.
Reduced single-instrument quantity is not a claim of lower portfolio risk.

Evidence must be available at the chosen cutoff. Future quotes/positions,
crossed quotes, mismatched scenario IDs, currencies and malformed costs are
rejected. Expired analyses/quotes/positions produce blocked records; the versioned
policy also blocks quotes older than 60 seconds and positions older than 300
seconds regardless of declared expiry. These are freshness checks on supplied
timestamps, not certification of provider clocks, market sessions, liquidity or
account completeness. Historical inputs follow the foundation's trusted supplied
evidence receipt contract; this does not certify an admitted historical dataset.

## Run

```sh
PYTHONPATH=src python -m trading_intelligence event-opportunity-demo --out data/opportunity-demo
```

The invented end-to-end proof seeds a scenario card, supplies quote/cost/account
inputs and compares long, short, reduction and hold. A fresh process reproduces
the same report. No network requests, broker calls or real prices are used.

For supplied registered evidence in an existing database:

```sh
PYTHONPATH=src python -m trading_intelligence event-opportunity \
  --database data/events.sqlite3 --assessment-id UNIQUE_ASSESSMENT \
  --analysis-id EXISTING_ANALYSIS --evidence-id EXISTING_INPUT_EVIDENCE \
  --as-of TIMEZONE_AWARE_CUTOFF
```

Register the original JSON through `EvidenceStore.ingest`, preserving its real
publication/receipt times and usage declarations. This slice does not supply a
live quote/position transport or independently validate scenario valuation inputs.
Next integrations need verified quotes and broker reconciliation, evaluated
outcome/valuation models and aggregate portfolio risk before trade selection.
The frozen baseline/forward pilot and all execution mandates remain unchanged.
