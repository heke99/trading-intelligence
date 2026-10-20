# Multi-broker preparation, version 0.4.0

The strategy-facing contract now references canonical instruments, not a vendor's symbol. A separate account-scoped adapter formats a persistent offline draft. This delivery has no broker transport, credentials, submit/cancel API, fills or portfolio engine.

## Identity and capabilities

`BrokerAccount` keys include broker, connection, external account and environment. Equal account numbers at different brokers or in paper/live are different routes. Multiple connections to the same *real* account still require one authoritative external account owner before future sending; route namespacing alone is not external-account deduplication or fencing.

`InstrumentTarget` is either an explicit equity/ETF listing or a futures expiry contract. Ordinary funds have no path through this equity order format. `NativeBinding` supplies this account's native ID, symbol, venue, currency, price tick, quantity step and minimum size. Unknown targets, venue/currency substitution, missing/expired bindings and overlapping intervals are blocked. This is supplied reference metadata, not verified vendor discovery. Preparation blocks two active canonical targets sharing a native ID or the same symbol/venue/currency within one account. The small offline catalogue is scanned conservatively; unrelated ambiguous references may also block preparation rather than allowing an arbitrary mapping. Actual native identities still require independent broker discovery.

`BrokerCapabilities` contains exact supported combinations of asset kind, limit-order TIF and session mode, with an explicit fractional-quantity flag. The allowed combinations cannot be inferred by mixing separate supported flags. Preparation is disabled by default. Snapshots are evidence-backed, bitemporal and account-specific; a broker name never grants account-level permission. They are caller assertions requiring independent admission.

Futures and brokers share the temporal reference implementation in `references.py` while retaining their original separate tables. Existing futures snapshot serialization and hashes are preserved. Source permission and original-byte integrity checks apply to both. Historical rights metadata does not enforce current entitlement, and direct DB edits are outside this prototype's security boundary.

## Order intents and drafts

`OrderIntent` records intent/strategy IDs, canonical target, side, Decimal quantity/limit price, raw-price declaration, decision time, validity, TIF and session mode. Only limit orders are represented. `prepare` requires an exact registered paper account and adapter, unexpired intent, usable capability/binding and valid price/quantity grids. It never rounds or switches brokers. Futures additionally require explicit terms, whole-contract quantity, raw price on the exchange tick, cash settlement and an entry time before the configured cutoff.

The result is a serialization draft, not an accepted paper order or a risk approval. It does not validate a live quote, actual current session, buying power, positions, short locate, aggregate exposure, fee budget, futures margin/collateral, pending orders or operational account permissions. A SELL side does not establish a verified reducing position or permission to open a short. The separate futures scenario checker is not automatically an execution gate here. Both paths still need a future unified account/risk/quote/session pipeline before sending.

Drafts persist the canonical input hash, original preparation time, exact adapter ID/version, stable account-scoped client ID, payload and reference snapshot IDs. Reusing one account/intent ID with different parameters raises a conflict. Retrying or reopening returns the original draft, even if current mappings/capabilities have changed or expired. This is audit retrieval, never renewed permission to send. New attempts with new intent IDs use current reference snapshots. The ledger detects accidental payload corruption by hash.

SQLite's unique account/intent key prevents a second local draft row. This is not exactly-once broker execution, an external ID allocator, margin reservation, distributed concurrency/fencing or a status reconciliation service. A future timeout after sending must become unknown status and be reconciled at the original broker. Never resend on a different broker as an automatic fallback.

## Adapter boundary

`BrokerAdapter` is a typed local encoding contract. `AdapterRegistry` requires an exact account match and rejects implicit replacement and live accounts. Only trusted local Python code should be registered; the protocol is not an isolation sandbox.

Two invented formats exercise that boundary:

- `SymbolPaperAdapter` uses symbol/venue and quantity/limit fields.
- `ContractPaperAdapter` uses opaque native contract ID and action/units fields.

Neither is an Alpaca, IBKR, MT5 or other real vendor implementation. No vendor SDK or upstream code is copied, and no account capability or access is inferred. Real connectors will need their own discovery, account/session validation, credentials, request/response normalization, reconciliation and contract tests. A common interface cannot promise identical supported products/order features across brokers.

```bash
PYTHONPATH=src python3 -m trading_intelligence brokers-demo --out data/brokers-demo
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The synthetic demo formats the same canonical listing for two invented brokers, persists two distinct drafts and proves that a retry and a reopened database reuse the originals. It sends zero orders. All three CLI examples require only Python's standard library and use no credentials or network.

## Next implementation

1. Add explicitly selected vendor read-only contract/account import adapters, with actual source receipt/processing time, current entitlement and environment validation.
2. Normalize quotes, market sessions, account balances, permissions and fees; unify account namespaces with the futures margin/binding pipeline.
3. Implement deterministic portfolio/risk checks and one fenced sender per real account, followed by a broker paper adapter and persistent status/fill reconciliation.
4. Exercise disconnect after send, unknown status, duplicated callbacks, partial fills, cancellations, restarts and unavailable broker; keep late events processing during stops.

Primary API design references reviewed 20 October 2026: [Alpaca order IDs and state](https://docs.alpaca.markets/us/docs/orders-at-alpaca) and [IBKR TWS protocol](https://www.interactivebrokers.com/docs/tws-api/doc/introduction). These explain why provider-specific behavior belongs behind adapters; they do not establish a working connection in this project.
