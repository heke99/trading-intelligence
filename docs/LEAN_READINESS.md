# Four practical prerequisites for the first LEAN trial

The masterplan requires an admitted Phase 1b slice before the first authoritative engine trial. This delivery advances four separate prerequisites while that real-data dependency remains blocked:

| Capability | Runnable result | Acceptance boundary |
| --- | --- | --- |
| Verified dataset export | Deterministic CSV/replay manifest, temporal lineage and an own-data reader bridge | Synthetic-only; genuine admission/export binding and LEAN runtime execution remain unverified |
| Frozen baseline and experiment | Locked simple price rule, exit/cost assumptions, chronological partitions and target/abstention decisions | Targets are not fills; no return or profitability claim |
| Cash/position reconciliation | Append-only externally declared simulated fill/action journal, fees and cash/position comparison | An audit calculator, not an order or fill engine; no broker statement verification |
| Read-only readiness diagnostic | Credential-presence, declared source rights, capture counts and runtime blockers | Does not print keys, connect to providers, install software or verify entitlements |

Run all four without a network or credentials:

```sh
PYTHONPATH=src python -m trading_intelligence lean-readiness-demo --out /tmp/ti-lean-readiness
```

The examples use invented source records and fixed injected clocks. A historical bar's date does not make its value available at that time: decisions respect receipt/processing availability, and an intended next-session action is omitted when information arrives too late. Cost parameters are frozen assumptions until a real engine applies them. The ledger consumes separate externally declared events; the baseline does not dispatch those events automatically.

The diagnostic can also inspect explicitly supplied local configuration:

```sh
PYTHONPATH=src python -m trading_intelligence readiness
PYTHONPATH=src python -m trading_intelligence readiness --database /path/to/research.sqlite3 --source-id configured-provider
```

See [export and reader contract](LEAN_EXPORT.md), [baseline/experiment contract](BASELINE.md), [cash ledger](CASH_LEDGER.md) and [diagnostic](READINESS.md) for exact APIs and limits.

## Reverification of the preceding delivery

PR #20 main `182d9bbe0e461a7f4adcf87e3d0144f96297ba7d` was checked again against the remote before this work. Its 386 synthetic tests passed, including negative source-origin, current-permission, incident and outcome-cutoff cases. The four-part research-foundations CLI produced equal semantic results after a fresh-process restart. A JSON field-order difference on first import versus archive reread was found and fixed by canonical CLI key ordering, with a process-level regression test.

No configured Alpaca paper credentials or SEC contact were present. There is no evidence of genuine external access, authenticated account identity, admitted historical data or model training from that verification. Local behavior and external source verification remain separate.

## Remaining engine acceptance

Before a meaningful full Phase 2 trial, configure source access and independently establish rights, authoritative sessions, raw prices, corporate actions and historical availability for a bounded admitted slice. Bind that admission to the exported artifact. Select and execute the documented pinned LEAN runtime route, connect its own-data reader and event reports, apply fees/spread/slippage/arrival/session rules and reconcile fills, positions, split/dividend effects and cash. Neither the offline custom-data contract nor a simulated ledger fixture establishes that this engine trial has run.

The first engine remains LEAN. No second authoritative order engine, paid CLI subscription, account change or live order is introduced here.
