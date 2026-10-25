# Corporate-action and identifier replay proofs

This delivery adds bounded offline proofs for split/dividend valuation and temporal identifier changes. It uses the existing evidence-backed normalized records and explicit opening inputs. It does not create an admitted historical dataset, a broker cash ledger, a trading strategy or a LEAN integration.

## Identity schedule

`resolve_schedule(store, requests, provider=..., as_of=...)` resolves an explicit identifier for each declared date. A request supplies `date`, `identifier`, timezone-aware `effective_at` and an optional `decision_at`. Exact provider/identifier matching uses existing temporal identifier versions; fuzzy symbol selection and automatic broker routing are not allowed.

Without `decision_at`, the fixed `as_of` represents a retrospective knowledge snapshot. With `decision_at`, the per-request cutoff must satisfy `effective_at <= decision_at <= as_of`. This distinguishes a corrected snapshot from a simulated decision that cannot see later corrections. The request date must match the supplied effective timestamp's own timezone; no listing timezone or exchange calendar is inferred.

The returned manifest includes selected mapping versions, backing evidence/raw hashes and listing/instrument identities. Raw corruption, temporal inconsistency, research-use denial, unknown identifiers and conflicting listings block replay. Multiple supporting mappings to the same listing are retained in lineage. SQL read savepoints preserve the caller's transaction.

A symbol rename can keep the same listing and instrument. A new listing or reorganized instrument is not silently treated as the same holding. Mapping content and known-at times remain caller assertions. Hashing the current mapping row in a manifest is not proof that a manually modified database row was historically correct; direct database writes remain outside the API integrity boundary.

## Corporate-action valuation scope

The proof begins with explicit nonnegative cash and shares in the listing currency, held before the declared scope. There are no trades, external cash flows, short positions, FX conversions, taxes, reinvestment or broker settlement. All bars remain raw. A split changes the quantity; it does not multiply an already adjusted total-return series. Ordinary cash distributions create an entitlement/receivable and then transfer it to cash on the supplied payment date, rather than counting both as new wealth.

Supplied ex/effective dates and payment dates are used as data. The code does not infer an ex-date from a record date, calculate due-bill entitlement or authorize payments. Special distributions, stock dividends, cash-in-lieu and complex reorganizations remain outside this proof. Same-day split/dividend ordering and share basis must be explicit in the calculation policy. Fractional calculations are mathematical examples, not a promise that a broker credits fractional holdings.

A fixed-cutoff corrected replay is labelled hypothetical. It does not rewrite external trades or claim the system knew a later correction at an earlier decision. Missing sessions/prices, unsupported identity/currency or inconsistent action scope block valuation. Explicit date lists still do not certify authoritative calendar or corporate-action completeness.

## Runnable synthetic demonstration

```bash
PYTHONPATH=src python3 -m trading_intelligence corporate-replay-demo --out data/corporate-demo
```

The repeatable demo holds 10 invented shares at raw price 100 with 100 cash. A 2-for-1 split changes this to 20 shares at 50. A later one-unit ordinary cash dividend creates 20 receivable while the fixture price falls to 49; payment transfers that receivable into cash. Total fixture wealth remains 1100. OLD then NEW resolve to the same listing and instrument. This arithmetic example is not a market result.

The calculation API is `corporate_action_replay(store, source_id, listing_id, expected_dates, as_of=..., opening_at=..., initial_cash=Decimal(...), initial_shares=Decimal(...), currency=..., dividend_share_basis="post_split", dividend_policy="ordinary_cash_no_withholding")`. Both dividend policy arguments are explicit assertions. Exact arithmetic uses precision 50 with an Inexact trap; unsupported rounding or a nonterminating split ratio is rejected. Known omitted events after the opening holding and before the first valuation, or inside the valuation range, must not be skipped. Under the daily action-before-valuation policy, actions later than session open are rejected. Payment events retain both their supplied payment date and the valuation date when cash is next displayed.

## References and remaining acceptance

Official concepts checked for this narrow proof:

- SEC Investor.gov, stock split: https://www.investor.gov/introduction-investing/investing-basics/glossary/stock-split
- SEC Investor.gov, ex-dividend dates: https://www.investor.gov/introduction-investing/investing-basics/glossary/ex-dividend-dates-when-are-you-entitled-stock-and

The supplied-event ordering, decimal policy and deterministic replay design are project decisions. Real event admission, authoritative calendar access, full historical membership/delisting coverage, broker-specific fraction/settlement treatment, actual accounting and the first LEAN baseline remain separate acceptance work.
