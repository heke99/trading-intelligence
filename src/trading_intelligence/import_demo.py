"""Synthetic vendor-shaped import; no HTTP, credentials or real account data."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .alpaca_reader import BrokerRead
from .broker_imports import BrokerImportStore
from .brokers import BrokerAccount, Environment
from .contracts import DataOrigin, Use


def reference_import_demo(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    received = first + timedelta(hours=1)
    processed = received + timedelta(minutes=1)
    native_account = "00000000-0000-4000-8000-000000000001"
    route = BrokerAccount("alpaca", "invented-reference-connection", "INVENTED-ACCOUNT", Environment.PAPER)
    account = dict(id=native_account, account_number=route.account_id, status="ACTIVE", currency="USD",
                   cash="1000.00", buying_power="1000.00", equity="1000.00", trading_blocked=False,
                   account_blocked=False, trade_suspended_by_user=False)
    assets = [dict(id="00000000-0000-4000-8000-000000000002", symbol="INVENTED", exchange="NASDAQ",
                   status="active", tradable=True, **{"class": "us_equity"}),
              dict(id="00000000-0000-4000-8000-000000000003", symbol="UNSUPPORTED", exchange="CRYPTO",
                   status="active", tradable=True, **{"class": "crypto"})]
    with BrokerImportStore(directory / "broker-import.sqlite3", clock=lambda: processed) as store:
        store.register_source("synthetic-alpaca-shaped", DataOrigin.SYNTHETIC)
        store.set_permissions("synthetic-alpaca-shaped", known_at=first, uses={Use.STORAGE, Use.RESEARCH})
        store.register_account(route)
        result = store.import_alpaca(route, import_id="invented-reference-batch", source_id="synthetic-alpaca-shaped",
                                     expected_native_id=native_account,
                                     account=BrokerRead("account", json.dumps(account).encode(), received, None),
                                     assets=BrokerRead("assets", json.dumps(assets).encode(), received, None))
        before = store.reference_import_as_of(route, "invented-reference-batch", as_of=received)
        return dict(origin="synthetic_fixture", state=result["report"]["state"],
                    normalized_assets=len(result["report"]["assets"]),
                    quarantined_rows=len(result["report"]["quarantined"]),
                    unavailable_before_processing=before is None, available_at=result["available_at"],
                    training_ready=False, orders_sent=0, live_trading=False)
