"""Collective2 API4: allowlisted GETs only. No broker/account write methods.

Contract references and unresolved live verification are in docs/SOURCES.md.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Iterator, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, unquote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .common import DataError, MAX_BYTES, MAX_ROWS, field, load_json, positive_id

BASE = "https://api4-general.collective2.com"
ENDPOINTS = {
    "closed_trades": "/Strategies/GetStrategyHistoricalClosedTrades",
    "orders": "/Strategies/GetStrategyHistoricalOrders",
}
COMMISSION_PLANS = {"0", "1", "3", "4", "5"}


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


class Transport(Protocol):
    def get(self, url: str, headers: dict[str, str]) -> Response: ...


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Redirect refused", headers, fp)


class HTTPSGetTransport:
    """TLS certificate validation remains enabled; no env proxies or redirects."""
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirects())

    def get(self, url: str, headers: dict[str, str]) -> Response:
        if not any(url.startswith(BASE + path + "?") for path in ENDPOINTS.values()):
            raise DataError("URL_NOT_ALLOWED")
        request = Request(url, headers=headers, method="GET")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise DataError("RESPONSE_TOO_LARGE")
                return Response(response.status, {k.lower(): v for k, v in response.headers.items()}, raw)
        except HTTPError as error:
            # Error bodies and redirect targets may contain credentials/private data.
            status, headers = error.code, dict(error.headers or {})
            error.close()
            return Response(status, {k.lower(): v for k, v in headers.items()}, b"")
        except (URLError, TimeoutError, OSError):
            raise DataError("NETWORK_ERROR") from None


@dataclass(frozen=True)
class Page:
    body: bytes
    rows: list[dict]
    next_cursor: str | None
    page_number: int


def parse_envelope(body: bytes) -> tuple[list[dict], str | None]:
    value = load_json(body)
    if not isinstance(value, dict):
        raise DataError("ENVELOPE_SCHEMA")
    status = field(value, "ResponseStatus")
    if status is not None:
        if not isinstance(status, dict):
            raise DataError("STATUS_SCHEMA")
        code = field(status, "ErrorCode")
        if code not in (None, "", "200", 200, "0", 0) or isinstance(code, bool) or field(status, "Errors"):
            raise DataError("API_RESPONSE_ERROR")
    rows = field(value, "Results")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or any(not isinstance(row, dict) for row in rows):
        raise DataError("RESULTS_SCHEMA")
    pagination = field(value, "Pagination")
    if pagination is None:
        return rows, None
    if not isinstance(pagination, dict):
        raise DataError("PAGINATION_SCHEMA")
    cursor = field(pagination, "next_cursor")
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 8192):
        raise DataError("CURSOR_SCHEMA")
    return rows, cursor or None


class C2Client:
    def __init__(self, api_key: str, *, transport: Transport | None = None,
                 sleep: Callable[[float], None] = time.sleep, max_pages: int = 200,
                 limit: int = 500, retries: int = 2):
        if (not isinstance(api_key, str) or not 8 <= len(api_key) <= 4096
                or not api_key.isascii() or any(c.isspace() or ord(c) < 33 for c in api_key)):
            raise DataError("API_KEY_INVALID")
        if not 1 <= max_pages <= 1000 or not 1 <= limit <= 1000 or not 0 <= retries <= 3:
            raise DataError("CLIENT_LIMIT_INVALID")
        self._api_key = api_key
        self.transport = transport or HTTPSGetTransport()
        self.sleep, self.max_pages, self.limit, self.retries = sleep, max_pages, limit, retries

    def _get(self, path: str, params: dict) -> bytes:
        if path not in ENDPOINTS.values():
            raise DataError("ENDPOINT_NOT_ALLOWED")
        url = BASE + path + "?" + urlencode(params)
        for attempt in range(self.retries + 1):
            response = self.transport.get(url, {"Authorization": "Bearer " + self._api_key,
                                                "Accept": "application/json",
                                                "User-Agent": "trading-intelligence/0.1 read-only"})
            headers = {k.lower(): v for k, v in response.headers.items()}
            if response.status == 200:
                if len(response.body) > MAX_BYTES:
                    raise DataError("RESPONSE_TOO_LARGE")
                if self._api_key.encode() in response.body:
                    raise DataError("SECRET_IN_RESPONSE")
                if "json" not in headers.get("content-type", "").lower():
                    raise DataError("RESPONSE_NOT_JSON")
                return response.body
            if response.status not in (429, 500, 502, 503, 504) or attempt == self.retries:
                raise DataError(f"HTTP_{response.status}")
            delay = float(2**attempt)
            if "retry-after" in headers:
                text = headers["retry-after"].strip()
                try:
                    delay = float(text)
                except ValueError:
                    try:
                        retry_date = parsedate_to_datetime(text)
                        if retry_date.tzinfo is None:
                            retry_date = retry_date.replace(tzinfo=timezone.utc)
                        delay = max(0.0, (retry_date - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError, OverflowError):
                        raise DataError("RETRY_AFTER_INVALID") from None
                if not 0 <= delay <= 30:
                    raise DataError("RETRY_LATER")
            self.sleep(delay)
        raise DataError("RETRY_LIMIT")

    def pages(self, kind: str, strategy_id: int, *, commission_plan: str = "0") -> Iterator[Page]:
        strategy_id = positive_id(strategy_id)
        if kind not in ENDPOINTS or commission_plan not in COMMISSION_PLANS:
            raise DataError("REQUEST_NOT_ALLOWED")
        params: dict = {"StrategyId": strategy_id}
        if kind == "closed_trades":
            params["CommissionPlan"] = commission_plan
        else:
            params.update(Limit=self.limit, AscendingOrder="true")
        seen: set[str] = set()
        count = 0
        for page_number in range(1, self.max_pages + 1):
            raw = self._get(ENDPOINTS[kind], params)
            rows, cursor = parse_envelope(raw)
            count += len(rows)
            if count > MAX_ROWS:
                raise DataError("ROW_LIMIT")
            yield Page(raw, rows, cursor, page_number)
            if cursor is None:
                return
            if kind != "orders":
                raise DataError("UNEXPECTED_PAGINATION")
            # Decode exactly once. Do not use unquote_plus: literal '+' is significant.
            decoded = unquote(cursor)
            if decoded in seen:
                raise DataError("CURSOR_LOOP")
            seen.add(decoded)
            params["Cursor"] = decoded
        raise DataError("PAGE_LIMIT")
