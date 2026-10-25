"""Bounded paper Trading API calendar GET transport; no order capabilities."""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, HTTPSHandler, build_opener

from .brokers import BrokerAccount, Environment
from .contracts import ContractError, required, utc

PAPER_CALENDAR_URL = 'https://paper-api.alpaca.markets/v2/calendar'
MAX_CALENDAR_BYTES = 2_000_000


class CalendarReadError(ContractError):
    pass


def calendar_query(start_date, end_date):
    """Explicit canonical inclusive bounds, up to 366 days, documented legacy range."""
    parsed = []
    for value in (start_date, end_date):
        if not isinstance(value, str):
            raise CalendarReadError('Canonical calendar date strings required')
        try:
            day = date.fromisoformat(value)
        except ValueError:
            raise CalendarReadError('Invalid calendar date') from None
        if day.isoformat() != value or not 1970 <= day.year <= 2029:
            raise CalendarReadError('Date outside supported legacy calendar scope')
        parsed.append(day)
    if not 0 <= (parsed[1] - parsed[0]).days <= 365:
        raise CalendarReadError('Require ordered inclusive range of at most 366 days')
    return {'start': start_date, 'end': end_date, 'date_type': 'TRADING'}


@dataclass(frozen=True)
class CalendarRead:
    payload: bytes = field(repr=False)
    received_at: datetime
    source_url: str
    route: BrokerAccount
    start_date: str
    end_date: str

    def __post_init__(self):
        if not isinstance(self.route, BrokerAccount) or self.route.broker_id != 'alpaca' or self.route.environment != Environment.PAPER:
            raise CalendarReadError('Explicit Alpaca paper route required')
        query = calendar_query(self.start_date, self.end_date)
        if self.source_url != PAPER_CALENDAR_URL + '?' + urlencode(query):
            raise CalendarReadError('Unexpected calendar endpoint or query')
        if not isinstance(self.payload, bytes) or not 0 < len(self.payload) <= MAX_CALENDAR_BYTES:
            raise CalendarReadError('Nonempty bounded original calendar response required')
        utc(self.received_at)

    @property
    def endpoint(self):
        return PAPER_CALENDAR_URL

    @property
    def query(self):
        return calendar_query(self.start_date, self.end_date)

    @property
    def method(self):
        return 'GET'

    @property
    def provenance(self):
        # Declared request context, not account identity verification.
        return {'endpoint': self.endpoint, 'method': self.method,
                'query': self.query, 'route': {'broker_id': self.route.broker_id,
                    'connection_id': self.route.connection_id, 'account_id': self.route.account_id,
                    'environment': self.route.environment.value}}

    @property
    def request_query(self):
        return calendar_query(self.start_date, self.end_date)


class _NoCalendarRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class AlpacaCalendarReader:
    """Runtime keys may have wider permissions; this software exposes GET only.

    The declared route labels a request; it is not proof that the credentials
    belong to that account. Authenticated account matching is separate work.
    Injected clocks/openers support offline verification, not authenticity claims.
    """
    def __init__(self, route: BrokerAccount, key_id: str, secret_key: str, *,
                 timeout: float = 10, clock=None, opener=None):
        if not isinstance(route, BrokerAccount) or route.broker_id != 'alpaca' or route.environment != Environment.PAPER:
            raise CalendarReadError('Explicit Alpaca paper route required')
        for credential in (key_id, secret_key):
            required(credential, 'credential')
            if any(not 33 <= ord(char) <= 126 for char in credential):
                raise CalendarReadError('Invalid credential header characters')
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise CalendarReadError('Timeout must be positive, finite and bounded')
        self._route = route
        self._key_id, self._secret_key = key_id, secret_key
        self._timeout = timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._opener = opener or build_opener(_NoCalendarRedirect(), HTTPSHandler(context=ssl.create_default_context()))

    def __repr__(self):
        return '<AlpacaCalendarReader paper GET /v2/calendar>'

    def read(self, start_date: str, end_date: str) -> CalendarRead:
        query = calendar_query(start_date, end_date)
        url = PAPER_CALENDAR_URL + '?' + urlencode(query)
        request = Request(url, method='GET', headers={
            'APCA-API-KEY-ID': self._key_id, 'APCA-API-SECRET-KEY': self._secret_key,
            'Accept': 'application/json', 'Accept-Encoding': 'identity'})
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200 or response.geturl() != url:
                    raise CalendarReadError('Unexpected calendar response status or endpoint')
                media = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                encoding = response.headers.get('Content-Encoding', 'identity').strip().lower()
                if media != 'application/json' or encoding not in ('', 'identity'):
                    raise CalendarReadError('Expected an uncompressed JSON calendar response')
                payload = response.read(MAX_CALENDAR_BYTES + 1)
        except CalendarReadError:
            raise
        except HTTPError as exc:
            status = str(exc.code) if type(exc.code) is int and 100 <= exc.code <= 599 else 'unknown'
            exc.close()
            raise CalendarReadError(f'Calendar HTTP failure ({status}); response details omitted') from None
        except (URLError, TimeoutError, OSError, UnicodeError, ValueError):
            raise CalendarReadError('Calendar connection failed; no retry or fallback was attempted') from None
        return CalendarRead(payload=payload, received_at=self._clock(), source_url=url,
                            route=self._route, start_date=start_date, end_date=end_date)
