# Evidence-bound hedge research and monitoring

This layer extends the event opportunity and canonical futures foundations on the
same SQLite connection. It compares a supplied protected equity/ETF book with
one new expiry-specific cash-settled index futures hedge at a time, pro-rata reduction
of a declared long-only book, and holding unchanged. It ranks bounded alternatives
under a frozen supplied policy. **It never creates real positions or grants order
approval.** No broker, price feed, training or OpenAI call is made by this layer.

## What “opposite direction” means

The aim is to reduce a specified portfolio risk, not to ensure one leg always wins.
A hedge can lose while the protected holdings lose, and it can sacrifice gains in
a rally. Simply duplicating the same instrument long and short is not supported as
an invented new source of protection; cash reduction is an explicit comparison.
The first hedge candidate here is a separate canonical expiry-specific future.

[CME's discussion](https://www.cmegroup.com/education/whitepapers/hedging-with-e-mini-sp-500-future)
explains portfolio beta, futures notional, cash variation margin and cases where
both positions lose. Our implementation uses supplied scenario stress and factor
exposures, not a fitted beta/correlation model or a minimum-variance backtest.
It does not copy the article's historical example or assume its past prices apply.

## Search arithmetic and tradeoffs

For signed integer contract quantity q and each supplied scenario s:

- Hedge PnL = q × long-contract gross PnL(s) − |q| × full roundtrip cost.
- Combined PnL = protected-book PnL(s) + hedge PnL(s).
- Gross exposure increases by |q| × contract notional, even if net factor falls.
- Residual factor exposure = book factor exposure + q × long-contract factor.
- Stress loss = max(0, −minimum combined PnL across the supplied scenarios).
- Reduction fraction f of the long-only book has PnL (1−f) × book PnL(s) minus
  immediate closing costs. The comparator holds the book marked to terminal mid;
  no later closing trade is charged to the sold fraction.

Search enumerates both contract directions within the fixed integer limit. A
feasible hedge must reduce absolute factor exposure without reversing its sign,
meet residual-factor and stress-loss targets, improve downside after costs, and
fit gross/notional/cash limits. It must include an explicit basis-break scenario
where both the protected book and that hedge direction lose. Missing stress cases
cannot silently certify a hedge.

The policy also caps **upside sacrificed** relative to positive book scenarios.
This prevents a cash-all alternative from automatically winning a worst-loss
comparison while concealing what was given up. Alternatives rank by worst stress
loss, then lower cost, lower cash requirement and stable size/ID tie breaks. Both
the best overall alternative and best feasible futures alternative are reported;
they can differ. No scenario probabilities, expected returns, VaR confidence
levels or guaranteed real-world risk reductions are inferred.

## Cash and margin

Available cash means supplied **free unreserved cash** for the exact broker,
connection, account, environment and currency of the candidate. Cash at another
broker/account is not pooled. Reserved margin must already have been excluded
by the supplier; this module does not reconcile a broker ledger.

Required hedge liquidity is stressed margin + worst adverse path VM debit +
roundtrip costs + policy buffer. Stressed margin cannot be below initial margin;
the adverse path debit cannot omit a terminal loss. This is a conservative bound,
not a daily settlement cash ledger. The same VM price movement is counted once
in economic PnL; the liquidity constraint is not a second expense. Cash reduction
must prefund immediate costs and does not assume sale proceeds are immediately
settled/available. Borrowing, cross-currency funding and margin offsets between
positions are not assumed.

## Evidence, references and operational controls

`HedgeResearchStore.search(search_id, opportunity_id, evidence_id, as_of=...)` binds:

1. An available immutable event opportunity, its analysis and source dependencies.
2. Original JSON containing `inputs`, `policy`, `controls`, `market_references`.
3. Canonical contract, terms, session, broker identifier and account margin snapshots.
4. Actual completion availability and an immutable result hash.

The protected listing set must contain the event listing. Supplied holding
allocations specify canonical listing, signed units, midpoint and factor loading.
Their marked absolute value/gross and signed factor sum must reconcile to the book.
The linked holding's quantity and mark must match the original exposure evidence;
a zero holding cannot seed a new hedge. All amounts share one currency and an
explicit common `risk_factor_id`; a factor loading is still a supplied unvalidated
assumption. The marked capital is not account NAV. A mixed/short book may enter
futures research, but pro-rata cash reduction is restricted to long-only books.

The new evidence uses full routes. Legacy futures references omit connection and
environment, so matching them is **not** verified full-route account eligibility.
Results explicitly retain this limitation. Current and historical source rights,
raw hashes and reference manifests are verified independently, including a later
revocation when reading an old result. Legacy reference known-at values remain
trusted supplied timestamps, not independently measured processing availability.

Raw futures entry/exit prices must respect the exact expiry's tick and multiplier;
terminal scenario PnL is recomputed from them. Notional and initial margin must
match canonical references. Physical settlement, wrong currency, continuous
series, closed sessions, off-tick prices and horizons reaching expiry are rejected.
All scenarios use a common future horizon; rolling/settlement is not simulated.
Quotes must be at most 60 seconds old and within 30 seconds of supplied state
and the linked underlying quote. Expiry during processing blocks a reviewable hedge.
Holdings/state and frozen policy require explicit timestamps/validity.

`controls` also freezes the hedge mandate declaration, order mode, rebalance band,
minimum wait and `revalidate_then_unwind` rule. Missing mandates, pause/hard stop,
old state, blocked opportunity, existing candidate hedge positions or pending/
unknown hedge orders block a reviewable new hedge. These checks do not promote
any supplied assertion into actual risk/order approval. Search covers at most
one new hedge instrument per alternative; it does not jointly optimize multiple
hedges or prevent double allocation across independent books in an execution ledger.

## Monitoring supplied filled exposure

`monitor(monitor_id, search_id, evidence_id, as_of=...)` archives a new supplied
snapshot linked to a feasible hedge alternative and exact policy version/route.
The first monitor slice supports one protected listing; multi-asset books require
a new search rather than a scalar monitoring shortcut. Nonzero changes in protected
quantity require a resized search and clear the old delta. The declared target must match that alternative; it cannot be increased because
a position lost money. Filled/allocated quantity, rather than requested quantity,
determines the remaining research delta.

- Unknown order status requires reconciliation; pending status waits without
  duplicating an order.
- A late supplied fill changes only the remaining difference on the next snapshot.
- If protected units become zero, the effective target becomes zero and an orphan
  alert persists until the situation is resolved.
- A hard stop blocks even an orphan unwind while retaining its alert. Pause does
  not authorize a new hedge under a `reduce_only` label.
- Expired state/policy requires review. Rebalance bands and cooldowns limit churn.
- Completion after state or policy expiry clears the research delta.

All next steps are symbolic reviews requiring revalidation. These are not verified
broker fills, an active daemon, actual fill reconciliation or executable recovery
orders. Monitoring results, source snapshots and corrections remain append-only.
It cannot extend the original policy's expiry or rewrite its exit/rebalance rules.

## Repeatable proof and commands

```sh
PYTHONPATH=src python -m trading_intelligence hedge-research-demo --out data/hedge-demo
```

The entirely fictional proof connects event analysis, supplied held shares,
canonical futures references, bounded hedge search, a partial hedge and an orphan
under hard stop. Under its supplied cases, reducing half the book ranks above the
best futures alternative; that alternative shorts three invented contracts.
This is a demonstration of comparisons, not investment performance. The same
report is reproduced in a fresh process. CI uses only synthetic fixtures.

For already registered original JSON evidence:

```sh
PYTHONPATH=src python -m trading_intelligence hedge-search \
  --database data/events.sqlite3 --search-id UNIQUE_SEARCH \
  --opportunity-id EXISTING_OPPORTUNITY --evidence-id ORIGINAL_HEDGE_PACKET \
  --as-of TIMEZONE_AWARE_CUTOFF

PYTHONPATH=src python -m trading_intelligence hedge-monitor \
  --database data/events.sqlite3 --search-id EXISTING_SEARCH \
  --monitor-id UNIQUE_MONITOR --evidence-id ORIGINAL_MONITOR_PACKET \
  --as-of TIMEZONE_AWARE_CUTOFF
```

The strict schemas are implemented in `hedge_math.py`, `hedge_research.py` and
`hedge_monitor.py`; the demo supplies a complete synthetic packet. New corrections
require new evidence/search/monitor IDs. Reuse returns the original record and
changed inputs under the same ID are rejected.

Real hedge selection/execution still requires verified positions, pending orders,
quotes, account permissions, statistically evaluated exposure models, complete
cash/variation-margin/roll simulation and aggregate risk/lifecycle acceptance.
The frozen forward pilot, LEAN engine boundary and live mandates are unchanged.
