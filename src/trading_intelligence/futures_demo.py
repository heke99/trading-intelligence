"""Invented futures scenario only. These are not exchange terms or margin quotes."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .contracts import AssetKind, DataOrigin, Entity, Instrument, Use
from .futures import (
    CollateralSnapshot, FutureContract, FutureProduct, FutureTerms, FuturesCheckFailed,
    FuturesMargin, FuturesResearchLimits, PriceKind, Session, Settlement, TradingSchedule,
)
from .futures_store import FuturesStore


def futures_demo(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    decision = first + timedelta(days=1, hours=12)
    end = first + timedelta(days=5)
    with FuturesStore(directory / "futures.sqlite3") as store:
        store.register_source("invented-futures", DataOrigin.SYNTHETIC)
        store.set_permissions("invented-futures", known_at=first, uses={Use.STORAGE, Use.RESEARCH})
        evidence = store.ingest(source_id="invented-futures", record_id="reference", revision_id="1",
                                payload=b'{"origin":"synthetic_fixture","purpose":"invented futures demo"}',
                                published_at=first, received_at=first)
        store.register_entity(Entity("demo-publisher", "Invented index publisher"))
        store.register_instrument(Instrument("demo-index", "demo-publisher", AssetKind.INDEX))
        store.register_product(FutureProduct("demo-product", "DEMO", "XOFF", "demo-index", "USD", "index_points"))
        store.register_contract(FutureContract("demo-2026-03", "demo-product", "2026-03"))
        times = dict(valid_from=first, valid_to=end, known_at=first, evidence_id=evidence)
        terms = FutureTerms(Decimal("0.25"), Decimal("2"), Settlement.CASH,
                            first + timedelta(days=80), first + timedelta(days=75))
        store.put_terms("demo-2026-03", terms, **times)
        store.put_schedule("demo-product", TradingSchedule("UTC", (
            Session(first, first + timedelta(days=2)),
            Session(first + timedelta(days=2, hours=1), end),
        )), **times)
        store.put_broker_binding("invented-broker", "DEMOH26", "demo-2026-03", "synthetic-contract-123", **times)
        store.put_margin("invented-broker", "invented-account", "demo-2026-03",
                         FuturesMargin(Decimal("1500"), Decimal("1200"), "USD"), **times)
        collateral = CollateralSnapshot("invented-broker", "invented-account", Decimal("10000"),
                                        "USD", first, end)
        limits = FuturesResearchLimits(3, Decimal("100000"), Decimal("1.2"))
        intent = dict(broker="invented-broker", account_id="invented-account", identifier="DEMOH26",
                      decision_at=decision, quantity=2, price=Decimal("100.25"),
                      price_kind=PriceKind.RAW_CONTRACT, collateral=collateral, limits=limits)
        preview = store.preview_opening_intent(**intent)
        blocked = []
        for label, changes in (("adjusted_price", dict(price_kind=PriceKind.ADJUSTED_SERIES)),
                               ("fractional_contract", dict(quantity=Decimal("0.5"))),
                               ("maintenance_break", dict(decision_at=first + timedelta(days=2, minutes=30)))):
            try:
                store.preview_opening_intent(**(intent | changes))
            except ValueError as error:
                blocked.append({"case": label, "reason": str(error)})
        if len(blocked) != 3:
            raise FuturesCheckFailed("Demonstration failed to block all invalid intents")
        return {"origin": "synthetic_fixture", "preview": asdict(preview),
                "gross_pnl_example": terms.gross_pnl(Decimal("100.25"), Decimal("101.25"), 2),
                "blocked_cases": blocked, "training_implemented": False, "live_trading": False}
