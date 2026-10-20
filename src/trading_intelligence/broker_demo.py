"""Two invented broker formats and persisted offline drafts, without any connection."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .brokers import (
    AdapterRegistry, BrokerAccount, BrokerCapabilities, ContractPaperAdapter, Environment,
    InstrumentTarget, NativeBinding, OrderIntent, OrderRule, SessionMode, Side,
    SymbolPaperAdapter, TargetKind, TimeInForce,
)
from .broker_store import BrokerStore
from .contracts import AssetKind, DataOrigin, Entity, Instrument, Listing, Use


def broker_demo(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    decision = first + timedelta(days=1)
    end = first + timedelta(days=5)
    with BrokerStore(directory / "brokers.sqlite3") as store:
        store.register_source("invented-brokers", DataOrigin.SYNTHETIC)
        store.set_permissions("invented-brokers", known_at=first, uses={Use.STORAGE, Use.RESEARCH})
        evidence = store.ingest(source_id="invented-brokers", record_id="reference", revision_id="1",
                                payload=b'{"origin":"synthetic_fixture","scope":"invented broker formats"}',
                                published_at=first, received_at=first)
        times = dict(valid_from=first, valid_to=end, known_at=first, evidence_id=evidence)
        store.register_entity(Entity("invented-issuer", "Invented demo issuer"))
        store.register_instrument(Instrument("invented-equity", "invented-issuer", AssetKind.EQUITY))
        store.register_listing(Listing("invented-listing", "invented-equity", "XNAS", "USD"))
        target = InstrumentTarget(TargetKind.LISTING, "invented-listing")
        a = BrokerAccount("invented-symbol-broker", "demo-connection", "demo-account", Environment.PAPER)
        b = BrokerAccount("invented-contract-broker", "demo-connection", "demo-account", Environment.PAPER)
        registry = AdapterRegistry()
        binding = NativeBinding(target, "synthetic-id-a", "DEMO.A", "XNAS", "USD",
                                Decimal("0.01"), Decimal("1"), Decimal("1"))
        capabilities = BrokerCapabilities((OrderRule(AssetKind.EQUITY, TimeInForce.DAY, SessionMode.REGULAR),), True)
        for account, adapter, mapping in (
            (a, SymbolPaperAdapter(a), binding),
            (b, ContractPaperAdapter(b), replace(binding, native_id="synthetic-id-b", symbol="OTHER-DEMO")),
        ):
            store.register_account(account)
            registry.register(adapter)
            store.put_capabilities(account, capabilities, **times)
            store.put_binding(account, mapping, **times)
        intent = OrderIntent("demo-intent", "demo-strategy", target, Side.BUY, Decimal("2"),
                             Decimal("100.25"), decision, end)
        drafts = [store.prepare(account, intent, prepared_at=decision, adapters=registry) for account in (a, b)]
        retry = store.prepare(a, intent, prepared_at=decision, adapters=registry)
        assert retry.client_order_id == drafts[0].client_order_id and retry.payload == drafts[0].payload
        return {"origin": "synthetic_fixture", "canonical_target": target.internal_id,
                "drafts": [dict(adapter=x.adapter_id, account_key=x.account_key,
                                client_order_id=x.client_order_id, payload=x.payload,
                                replayed=x.replayed, state=x.state) for x in drafts],
                "persisted_draft_count": store.db.execute("SELECT count(*) FROM broker_drafts").fetchone()[0],
                "retry_reused_original": retry.replayed, "orders_sent": 0, "live_trading": False}
