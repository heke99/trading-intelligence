"""Read-only Alpaca Trading API reader. No order endpoints or vendor SDK."""

from dataclasses import dataclass
from datetime import datetime, timezone
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, HTTPSHandler, build_opener

from .brokers import Environment
from .contracts import ContractError, required, utc


MAX_RESPONSE_BYTES = 20_000_000
PAPER_HOST = "https://paper-api.alpaca.markets"
RESOURCES = {"account": "/v2/account", "assets": "/v2/assets"}


class BrokerReadError(ContractError):
    pass


@dataclass(frozen=True)
class BrokerRead:
    resource: str
    payload: bytes
    received_at: datetime
    source_url: str | None
    environment: Environment = Environment.PAPER

    def __post_init__(self):
        if self.resource not in RESOURCES:
            raise BrokerReadError("Unsupported reference resource")
        if not isinstance(self.payload, bytes) or not 0 < len(self.payload) <= MAX_RESPONSE_BYTES:
            raise BrokerReadError("Response must contain nonempty original bytes within the size limit")
        utc(self.received_at)
        object.__setattr__(self, "environment", Environment(self.environment))
        # None explicitly marks a supplied/local response, never a verified fetch.
        if self.source_url is not None and self.source_url != PAPER_HOST + RESOURCES[self.resource]:
            raise BrokerReadError("Reference response URL does not match the allowed endpoint")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class AlpacaReferenceReader:
    """Paper-environment GET only; credentials are never included in repr/errors.

    Keys may have wider vendor permissions. The software's GET restriction does
    not turn them into read-only credentials or create an isolation sandbox.
    """
    def __init__(self, key_id: str, secret_key: str, *, timeout: float = 10,
                 clock=None, opener=None):
        for value in (key_id, secret_key):
            required(value, "credential")
            if any(ord(x) < 32 or ord(x) == 127 for x in value):
                raise BrokerReadError("Credential contains invalid header characters")
        if type(timeout) not in {int, float} or not 0 < timeout <= 30:
            raise BrokerReadError("Timeout must be positive and bounded")
        self._key_id, self._secret_key = key_id, secret_key
        self._timeout = timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._opener = opener or build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))

    def read(self, resource: str) -> BrokerRead:
        if resource not in RESOURCES:
            raise BrokerReadError("Only account/assets reference reads are implemented")
        url = PAPER_HOST + RESOURCES[resource]
        request = Request(url, method="GET", headers={
            "APCA-API-KEY-ID": self._key_id, "APCA-API-SECRET-KEY": self._secret_key,
            "Accept": "application/json", "Accept-Encoding": "identity",
        })
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200 or response.geturl() != url:
                    raise BrokerReadError("Unexpected response status or endpoint")
                media = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if media != "application/json":
                    raise BrokerReadError("Expected a JSON reference response")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            status = error.code
            error.close()
            raise BrokerReadError(f"Broker reference HTTP failure ({status}); body omitted") from None
        except (URLError, TimeoutError, OSError):
            raise BrokerReadError("Broker reference connection failed; no retry or fallback was attempted") from None
        return BrokerRead(resource, payload, self._clock(), url)
