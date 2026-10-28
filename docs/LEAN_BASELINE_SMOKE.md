# Synthetic LEAN rule, fills and cash reconciliation

This engineering trial connects the existing frozen baseline registry to LEAN order/fill callbacks and the independent `CashLedgerStore`. It uses only authored synthetic prices and a synthetic custom-data security. It is not a real-data baseline acceptance, native-equity trading certification, forward paper order session or profitability test.

## One Mac command

With Docker running and the project virtual environment active:

```sh
git pull --ff-only &&
PYTHONPATH=src python3 -m trading_intelligence.lean_baseline_smoke prepare-run \
  --out "$HOME/ti-baseline-smoke-$(date -u +%Y%m%dT%H%M%SZ)" \
  --timeout 300
```

No keys, source database, account files or existing forward-pilot directory are needed or mounted. A fresh dedicated directory is mandatory. The same pinned ARM64 LEAN image is used with Docker networking disabled, dedicated read-only input and writable output. The existing observer's zero-order contract stays unchanged; this is a separate synthetic execution algorithm. There is no broker transport or order-engine alternative.

`--prepare-only` creates the files without Docker and returns `engine_execution_verified=false`. Only accepted engine output can return `status=passed`, `scope=synthetic_engine_accounting_only`, `simulated_order_count=4` and `cash_and_positions_reconciled=true`. Even a pass leaves real admission, training, statistical evaluation, profitability verification and live trading false, with `orders_sent_to_broker=0`.

## Frozen trial and information flow

The authored fixture has ten sessions in January 2026 and twenty explicit open/close availability events. Separate open and close values make pricing a next-open order from the previous close fail the acceptance checks. `BaselineStore` freezes `close_gt_sma`, lookback two, next-explicit-session timing and commission/spread/slippage/latency assumptions. It registers a synthetic experiment/trial and evaluates only its validation partition for expected decisions. The registry timestamps in this fixture are injected synthetic times; they do not prove real preregistration. All fixture outcomes are known in advance and no final period is claimed untouched.

The LEAN algorithm computes signals using only the closes already delivered to its callback, sharing the exact Decimal numerical rule with the registry. It uses the separately declared known session timetable for the immediate next-session opening. A pending intention cannot move to a later session. The next open must follow the frozen latency, and stream order/availability is checked before a submission.

The binary target is clipped by an explicit **two-whole-unit engineering position cap**. This is not a full-portfolio 100% allocation performance test. Custom-data prices are authored tradable fixture prices, not late captured AAPL observations; the original captured-data stream remains nontradable. The synthetic security uses default 24/7 custom exchange hours with the authored event timetable, not an independently verified XNAS exchange calendar. Synthetic corporate-action coverage is authored as none; no real-action handling is certified.

Only fully filled immediate orders are supported by this fixture. Rejections, partial fills, unresolved tickets, unexpected symbols, wrong quantities and early or delayed callback timestamps fail acceptance. General execution lifecycle/reconciliation remains a separate production dependency.

## Costs and independent accounting

Frozen assumptions are one USD commission per order, two basis points **full** spread and one basis point additional slippage. The adverse per-side price movement is half the spread plus slippage, or two basis points. LEAN applies `ConstantFeeModel` and `ConstantSlippageModel` with its `ImmediateFillModel`; these assumptions are not verified Alpaca fees, quotes, liquidity or execution behavior.

Expected engine fills are independently derived from the frozen intentions and authored next-open prices. The hand-checked fill sequence is:

| Date | Units | Fill price | Fee |
| --- | ---: | ---: | ---: |
| 8 January | +2 | 102.0204 | 1 |
| 9 January | -2 | 94.981 | 1 |
| 13 January | +2 | 105.021 | 1 |
| 14 January | -2 | 103.9792 | 1 |

Two round trips leave zero units. Starting cash 1,000 yields final cash **979.8376**, commissions 4, half-spread cost 0.0812 and additional slippage cost 0.0812. This deliberately losing artificial example tests accounting, not strategy quality.

The host checks engine exit/log/final Completed state and order count, exact rule decisions, complete stream, unique order IDs, exact intended time/quantity, expected adverse prices/fees and zero final position. It translates actual engine callback records into the existing declared cash-event contract with explicit `synthetic_fixture` origin. `CashLedgerStore` replays those events independently and reconciles to LEAN cash/positions, then also checks the separate hand-calculated golden cash. Cash tolerance is 0.000001 USD and quantity tolerance is zero; fill-price tolerance is 0.00000001. Stale output, preexisting ledger files, changed inputs and fabricated real-data flags fail.

Output includes engine artifacts, `baseline-evidence.json`, `cash-events.json`, `cash-ledger.sqlite3` and `accounting-evidence.json`, plus hashes in `run-result.json`. Callback JSON is our own frozen algorithm report, not a parser for arbitrary native LEAN export formats. The ledger's comparison snapshot remains engine-simulation state, not brokerage state. Hash binding is not an authentication or external timestamp service.

## Development verification and remaining work

Development has no Docker. The local suite exercises fixture preparation, actual algorithm methods with synchronous broker test doubles, mocked engine artifacts, the real host cash-ledger importer, and rejection paths. These tests do not establish a real LEAN run. Actual pinned-engine acceptance is pending the fresh Mac command above. A failed engine attempt remains failed even if offline math agrees.

The real forward pilot continues unchanged. Source-use reviews, corporate-action coverage, actual admitted-slice binding, native equity sessions/prices and realistic fill/cost assumptions still precede real-data strategy evaluation. A successful synthetic engineering run cannot clear those requirements.

Primary references checked 28 October 2026:

- [Order callback UTC, fill and fee fields](https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/order-events).
- [Constant fee model](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/transaction-fees/supported-models).
- [Constant percentage slippage](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/supported-models).
- [Custom-data properties and default exchange hours](https://www.quantconnect.com/docs/v2/writing-algorithms/importing-data/streaming-data/key-concepts).
- [Pinned immediate market-fill implementation](https://github.com/QuantConnect/Lean/blob/f3d841e60dfd010ee5fc293ea893e56952484108/Common/Orders/Fills/FillModel.cs).
