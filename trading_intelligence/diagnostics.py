"""Read-only access probes. Never archive key metadata or provider responses.

GetAccessKey intentionally returns the secret in AccessKey. This probe must
project approved metadata directly, without passing it through ingestion or
weakening the importer's reflected-secret rejection.
"""
from __future__ import annotations

import re
from datetime import datetime

from .collective2 import (ACCESS_KEY_PATH, BASE, COMMISSION_PLANS, ENDPOINTS,
                         C2Client, HTTPSGetTransport, Transport, parse_envelope)
from .common import DataError, MAX_BYTES, field, positive_id


def _error(check: dict, error: DataError, api_key: str) -> dict:
    code = str(error)
    if api_key in code or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
        code = "DIAGNOSTIC_REQUEST_FAILED"
    check.update(status="error", error=code)
    if re.fullmatch(r"HTTP_[1-5][0-9]{2}", code):
        check["http_status"] = int(code[5:])
    return check


def _role(value, api_key: str) -> str | None:
    if (not isinstance(value, str) or api_key in value
            or not re.fullmatch(r"[A-Za-z0-9_, .:/-]{1,80}", value)):
        return None
    return value


def _delete_date(value, api_key: str) -> str | None:
    # Preserve the documented field name; deletion is not claimed to be expiry.
    if (not isinstance(value, str) or api_key in value or len(value) > 40
            or not re.fullmatch(r"[0-9TtZz:+.\-]+", value)):
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def diagnose_access(api_key: str, strategy_id: int, *, commission_plan: str = "0",
                    transport: Transport | None = None) -> dict:
    strategy_id = positive_id(strategy_id)
    if commission_plan not in COMMISSION_PLANS:
        raise DataError("REQUEST_NOT_ALLOWED")
    client = C2Client(api_key, transport=transport or HTTPSGetTransport(), limit=1, retries=0)
    checks = []
    check = {"endpoint": ACCESS_KEY_PATH, "method": "GET", "http_status": None}
    try:
        response = client.transport.get(BASE + ACCESS_KEY_PATH, {
            "Authorization": "Bearer " + api_key, "Accept": "application/json",
            "Content-Type": "application/json", "User-Agent": "trading-intelligence/0.1 read-only"})
        check["http_status"] = response.status
        if response.status != 200:
            raise DataError(f"HTTP_{response.status}")
        if len(response.body) > MAX_BYTES:
            raise DataError("RESPONSE_TOO_LARGE")
        headers = {k.lower(): v for k, v in response.headers.items()}
        if "json" not in headers.get("content-type", "").lower():
            raise DataError("RESPONSE_NOT_JSON")
        rows, _ = parse_envelope(response.body)
        metadata = rows[0] if rows else {}
        check.update(status="ok", result_rows=len(rows),
                     key_role=_role(field(metadata, "Role"), api_key),
                     key_delete_date=_delete_date(field(metadata, "DeleteDate"), api_key))
    except DataError as error:
        _error(check, error, api_key)
    checks.append(check)

    for kind, path in ENDPOINTS.items():
        check = {"endpoint": path, "method": "GET", "http_status": None}
        params = {"StrategyId": strategy_id}
        if kind == "closed_trades":
            params["CommissionPlan"] = commission_plan
        else:
            params.update(Limit=1, AscendingOrder="true")
        try:
            # One response per endpoint. A probe never traverses the history.
            raw = client._get(path, params)
            check["http_status"] = 200
            rows, cursor = parse_envelope(raw)
            check.update(status="ok", result_rows=len(rows), has_next_cursor=bool(cursor))
        except DataError as error:
            _error(check, error, api_key)
        checks.append(check)
    return {"strategy_id": str(strategy_id), "checks": checks,
            "access_checks_passed": all(check["status"] == "ok" for check in checks),
            "scope": "access_probes_not_full_history", "data_saved": False,
            "training_ready": False, "full_history_verified": False}
