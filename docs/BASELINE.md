# Frozen numerical baseline and chronological trial registry

This bounded offline slice freezes a simple rule and records its experiment/trial protocol. It produces **target intentions and abstentions only**. It does not execute LEAN, simulate fills, maintain a position/cash ledger, apply fees or compute returns/profitability. Costs and benchmarks are frozen assumptions for the later engine trial.

## Contract and data binding

`BaselineStore.freeze_baseline` freezes one explicit listing (the pilot universe), `close_gt_sma`, integer lookback, bar-availability decision timing, zero-target exit policy, commission/spread/slippage/latency parameters, cash/buy-and-hold benchmark, and corporate-action window-reset policy. IDs are immutable; retries with the same semantic inputs reuse their original registration. A new configuration requires a new ID.

`register_experiment` binds that contract to a verified synthetic export bundle's **complete manifest fingerprint**, explicit train/validation/final-test date intervals, primary metric and optional calendar-day label horizon. Each partition must contain observations, intervals must be ordered/nonoverlapping, and a label horizon extending into the next partition is rejected. These are protocol checks, not statistical certification. The registry cannot prove the user never inspected historical files before registration.

`register_trial` records a candidate identifier before `evaluate_trial` can run. Candidate identifiers do not permit parameter changes: each trial still uses the registered immutable contract and dataset. Modifying even an internally rehashed bundle changes its registered fingerprint and is blocked. File hashes protect integrity/binding; they are not provider authentication or a tamper-proof security boundary.

## Deterministic rule and timing

At each raw bar's explicit `available_at`, the rule compares the close with the arithmetic mean of the last N available closes. The comparison uses `close * N > sum(closes)` in a fixed 80-digit Decimal context; inexact/invalid/overflow arithmetic is rejected. Above the mean proposes target weight one; otherwise target zero. These are proposals, not actual holdings or executed entries/exits.

Warmup and unavailable lookback observations cause abstention. A known split or cash-dividend record truncates any window crossing its economic date, including when that record first becomes known on a later bar date. This avoids silently comparing known incompatible raw prices across the action; no adjusted-price model is implied. Newer already-available bars supersede stale delayed bars.

The only allowed intention time is the **immediate next explicitly bundled session open**. The next session's calendar must already be known at the decision. Its open must not precede decision time plus frozen latency. If that open was missed, the rule abstains; it never rolls the old decision silently to a later opening. Intents outside the chosen evaluation partition are also withheld. No future bar close is used to price or justify an intention, and no intention counts as a fill/order authorization.

The bundle's expected session list is explicit synthetic scope, not an authoritative full exchange calendar. Missing omitted holidays/sessions and unknown corporate-action coverage are not certified by this baseline. Actual calendars, corporate-action handling and source admission remain prerequisites for real-data engine evaluation.

## Final-test consumption

The first final-test evaluation persistently consumes its canonical instrument/date range. The overlap check and consumption insert share a SQLite `BEGIN IMMEDIATE` transaction, so two workers with different trial IDs cannot both consume it. Consumption is committed **before** strategy outputs are produced and remains even if evaluation subsequently fails.

Within the retained registry, new baseline/experiment/trial/candidate IDs, source identifiers or dataset hashes cannot reset an overlapping consumed final period for the same canonical instrument. Renaming listings that still identify that same canonical instrument also does not reset it. A successful exact retry returns its saved report; a different trial must use new evidence or an independently specified evaluation protocol. Deleting/replacing the registry or falsifying canonical identities is outside these local API guarantees and must be prevented operationally.

## Example and validation

`baseline_demo(directory)` creates an invented market bundle, freezes the rule, registers a chronological experiment and trial, evaluates target intentions, and demonstrates that a renamed trial cannot reuse the consumed final test. Its injected clock is synthetic and does not demonstrate real-time preregistration before historical market outcomes. It is repeatable after reopening its local files and reports `lean_runtime_verified=False`, `performance_computed=False`, `costs_applied=False`, `training_implemented=False`, and `live_trading=False`.

The synthetic tests cover frozen inputs, chronology/label overlap, operational registration clocks, dataset fingerprint binding, current Decimal-context independence, delayed arrival, latency, late-known corporate actions, consumed final periods across IDs/restarts/overlapping boundaries, concurrent consumption, failed evaluation consumption, saved retries and the repeatable demo. A green protocol test does not demonstrate an economic trading edge.
