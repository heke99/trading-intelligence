# Captured corporate actions to a conditional holdings preview

`CapturedActionAccountingStore` connects immutable action capture jobs to original
opening-holding and reviewed-rule evidence. It writes only a preview journal.
It does not write actual positions, cash, market snapshots or ledger events and
cannot clear source rights, coverage or data-admission gates.

## Calculation

For a supplied fixed long holding with no intervening trades:

- A supported split changes shares by the source new/old ratio using exact rational
  arithmetic. Fractional results block the preview: no rounding or cash-in-lieu
  price is invented.
- A normal cash dividend uses units at its declared ex-date step. It becomes a
  receivable first and increases cash only at the supplied payment instant.
- Split and dividend at the same instant require an explicit unique step order,
  which determines the declared dividend share basis. Order is not guessed.
- Unknown opening entitlements, unsupported due-bill terms, missing reviews/payment
  time or an unproven no-trade interval block closing totals. Intermediate steps
  remain illustrative diagnostics, not applied transactions.

The result retains `coverage_verified=false`, `accounting_ready=false`,
`dataset_admitted=false`, `historical_predictive_evaluation_valid=false`,
`holdings_or_cash_written=false`, zero orders and no live trading. Even a complete
empty response does not establish absence of effective events. Process-date API
filtering is never interpreted as ex-date coverage.

## Evidence contracts

Opening JSON has exact fields:

- `route`: exact captured broker/connection/account/environment dictionary.
- `listing_id`, `currency`: exact captured listing and trading currency.
- `units`, `cash`: bounded decimal strings; whole positive long shares and
  nonnegative cash in this first slice.
- `at`: timezone-aware opening instant.
- `unchanged_holdings_through`: explicit end of the supplied no-trade assertion.
- `opening_receivables_clear`: explicit boolean assertion about opening entitlements.

Policy JSON has exact fields `version`, `timezone` (IANA market timezone), `rules`,
`dividend_treatment='gross_no_tax_or_fees'`, `fractional_policy='block'`.
Each rule has exact fields `provider_id`, `provider_row_sha256`, `listing_id`,
`currency`, `identity_reviewed`, `terms_reviewed`, `effective_at`, `payment_at`,
`sequence`. Both review flags must be explicit booleans. Payment is null for
splits. Reviewed instants must match source ex/payment dates in the stated market
timezone, with payment not preceding entitlement. The rate applies to units at
that exact step; the reviewer must establish this basis from the actual terms.

Every candidate in the selected capture needs exactly one rule, including those
outside the requested valuation window. Unknown source currency can only be
resolved by an explicit supplied currency/review assertion; original source
unknowns are preserved. A row correction requires new rules bound to its exact
fingerprint and a new preview ID. Review flags are supplied research assertions,
not independent entitlement or accounting certification.

Existing pre-opening dividends whose payment follows opening block the preview;
this slice has no opening receivable import. It also excludes trades, shorts,
withholding, taxes, fees, reinvestment, special/foreign distributions, cash-in-lieu,
cost-basis accounting, mark-to-market PnL and broker reconciliation.

## Run against already registered evidence

```sh
PYTHONPATH=src python -m trading_intelligence.captured_action_accounting \
  --database data/research.sqlite3 --preview-id UNIQUE_PREVIEW \
  --source-id ACTION_SOURCE --import-id EXACT_ACTION_IMPORT \
  --opening-evidence-id ORIGINAL_OPENING_DOCUMENT \
  --policy-evidence-id ORIGINAL_REVIEW_DOCUMENT \
  --as-of TIMEZONE_AWARE_KNOWLEDGE_CUTOFF \
  --valuation-at TIMEZONE_AWARE_VALUATION
```

The database must already exist. Register documents with `EvidenceStore.ingest`
using real receipt/review times and declared uses; do not invent provider
publication times. Opening <= valuation <= knowledge cutoff <= operational time.
Later-captured actions can support a conditional retrospective calculation, never
an assertion that they were known at their historical ex-dates.

A preview binds the exact action manifest, both evidence hashes, input cutoffs and
actual completion time. Reads verify current and historical source rights and
original bytes. Old cutoffs cannot bypass a revocation. ID reuse returns immutable
history; changing inputs under the same ID conflicts. New captures do not overwrite
old preview results. Transactional writes and read snapshots keep dependencies
consistent through creation/restart.

Synthetic tests exercise the actual captured-action pipeline with invented
provider bytes, then review/evaluate it: split quantity, dividend receivable/payment,
explicit same-time ordering, partial/unknown terms, reverse-split fractions, empty
captures, wrong account/currency/revision/date, chronology, precision, restart,
revocation, corruption and the CLI. No provider call or ledger mutation is made.

The next real-data dependency remains verified rights/coverage, actual opening
positions/entitlements and accepted accounting policies. Only after those gates
can a separately implemented application step update a reconciled position ledger.
