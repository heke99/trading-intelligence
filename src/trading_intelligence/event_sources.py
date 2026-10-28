"""Read-only event captures and strict USGS summary normalization.

USGS update/generation times are provider observations, not established
publication times. A USGS tsunami flag is not confirmation of a tsunami.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.client import HTTPException
import json
import math
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .alpaca_normalizer import decode, NormalizationError
from .contracts import ContractError, required, utc


MAX_BYTES = 20_000_000
NORMALIZER_VERSION = "usgs-summary-1"
USGS_FEEDS = {
    "all_hour": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson",
    "all_day": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
    "all_week": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson",
    "all_month": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_month.geojson",
}
GDACS_FEED_URL = "https://www.gdacs.org/xml/rss.xml"
EVENT_FEEDS = {**USGS_FEEDS, "gdacs": GDACS_FEED_URL}
FORMAT_URLS = {
    "usgs_geojson_v1": frozenset(USGS_FEEDS.values()),
    "gdacs_rss_v1": frozenset({GDACS_FEED_URL}),
}


class EventReadError(ContractError):
    pass


def endpoint(feed="all_hour"):
    if not isinstance(feed, str) or feed not in USGS_FEEDS:
        raise EventReadError("Select an explicitly supported USGS summary feed")
    return USGS_FEEDS[feed]


@dataclass(frozen=True)
class EventCapture:
    payload: bytes = field(repr=False)
    received_at: datetime
    source_url: str
    format: str = "usgs_geojson_v1"
    transport: str = "supplied_bytes"

    def __post_init__(self):
        if not isinstance(self.format, str) or self.format not in FORMAT_URLS:
            raise EventReadError("Unsupported event capture format")
        if not isinstance(self.source_url, str) or self.source_url not in FORMAT_URLS[self.format]:
            raise EventReadError("Event capture endpoint does not match its declared format")
        if not isinstance(self.transport, str) or self.transport not in {"supplied_bytes", "declared_http_get"}:
            raise EventReadError("Explicit event capture transport is required")
        if not isinstance(self.payload, bytes) or not 0 < len(self.payload) <= MAX_BYTES:
            raise EventReadError("Bounded nonempty original event response bytes are required")
        utc(self.received_at)


def normalize_capture(capture):
    """Explicit versioned format dispatch, separate from provider observations."""
    if not isinstance(capture, EventCapture):
        raise EventReadError("Explicit EventCapture required")
    if capture.format == "usgs_geojson_v1":
        return normalize_usgs(capture.payload)
    if capture.format == "gdacs_rss_v1":
        from .gdacs_events import normalize_gdacs
        return normalize_gdacs(capture.payload)
    raise EventReadError("Unsupported event capture format")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class UsgsEventReader:
    """One public GET from a selected official summary feed; no automatic retry."""

    def __init__(self, feed="all_hour", *, timeout=10, clock=None, opener=None):
        self.source_url = endpoint(feed)
        if type(timeout) not in {int, float} or not 0 < timeout <= 30:
            raise EventReadError("A positive bounded timeout is required")
        self._timeout = timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._opener = opener or build_opener(
            _NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))

    def __repr__(self):
        return "<UsgsEventReader public GET summary>"

    def read(self):
        url = self.source_url
        if not isinstance(url, str) or url not in USGS_FEEDS.values():
            raise EventReadError("Event reader endpoint is not a supported USGS feed")
        request = Request(url, method="GET", headers={
            "User-Agent": "TradingIntelligence-event-capture/1",
            "Accept": "application/geo+json, application/json",
            "Accept-Encoding": "identity",
        })
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200 or response.geturl() != url:
                    raise EventReadError("Unexpected event response status or endpoint")
                media = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
                if media not in {"application/json", "application/geo+json", "application/vnd.geo+json"}:
                    raise EventReadError("Expected a JSON or GeoJSON event response")
                if encoding not in {"", "identity"}:
                    raise EventReadError("Expected an uncompressed event response")
                payload = response.read(MAX_BYTES + 1)
        except EventReadError:
            raise
        except HTTPError as error:
            status = str(error.code) if type(error.code) is int and 100 <= error.code <= 599 else "unknown"
            error.close()
            raise EventReadError(f"Event HTTP failure ({status}); details omitted; no retry") from None
        except (URLError, OSError, HTTPException, UnicodeError, ValueError):
            raise EventReadError("Event connection failed; no retry or fallback") from None
        return EventCapture(payload, self._clock(), url, transport="declared_http_get")


def _text(value, *, optional=False):
    if value is None and optional:
        return None
    try:
        return required(value, "provider text")
    except ContractError:
        raise NormalizationError("invalid_text") from None


def _integer(value):
    if type(value) is not int:
        raise NormalizationError("invalid_integer")
    return value


def _millis(value):
    value = _integer(value)
    try:
        return utc(datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=value))
    except (OverflowError, ValueError):
        raise NormalizationError("invalid_epoch_milliseconds") from None


def _number(value, *, optional=False, lower=None, upper=None):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise NormalizationError("invalid_number")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise NormalizationError("invalid_number") from None
    if not math.isfinite(result) or (lower is not None and result < lower) or (upper is not None and result > upper):
        raise NormalizationError("number_out_of_range")
    return result


def _feature(value, index):
    if not isinstance(value, dict) or value.get("type") != "Feature":
        raise NormalizationError("feature_object_required")
    native_id = _text(value.get("id"))
    props, geometry = value.get("properties"), value.get("geometry")
    if not isinstance(props, dict) or not isinstance(geometry, dict) or geometry.get("type") != "Point":
        raise NormalizationError("properties_and_point_geometry_required")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != 3:
        raise NormalizationError("three_usgs_coordinates_required")
    occurred = _millis(props.get("time"))
    updated_ms = _integer(props.get("updated"))
    updated = _millis(updated_ms)
    if updated < occurred:
        raise NormalizationError("provider_update_before_event")
    tsunami = props.get("tsunami")
    if tsunami is not None and (type(tsunami) is not int or tsunami not in {0, 1}):
        raise NormalizationError("invalid_tsunami_flag")
    return dict(
        event_id=native_id, revision_id=str(updated_ms),
        event_type=_text(props.get("type")), occurred_at=occurred,
        provider_updated_at=updated, published_at=None,
        longitude=_number(coordinates[0], lower=-180, upper=180),
        latitude=_number(coordinates[1], lower=-90, upper=90),
        depth_km=_number(coordinates[2], optional=True),
        magnitude=_number(props.get("mag"), optional=True),
        magnitude_type=_text(props.get("magType"), optional=True),
        place=_text(props.get("place"), optional=True),
        title=_text(props.get("title"), optional=True),
        status=_text(props.get("status"), optional=True),
        source_event_url=_text(props.get("url"), optional=True),
        detail_url=_text(props.get("detail"), optional=True),
        tsunami_flag=tsunami, tsunami_confirmed=None, row_index=index,
    )


def normalize_usgs(payload):
    """Return normalized observations and durable-quarantine descriptions.

    This function establishes no source admission, independence between sources,
    physical damage, market impact or publication timestamp. Future-time checks
    belong to staging, which knows receipt and processing times.
    """
    metadata = {}
    report = dict(observations=[], quarantined=[], metadata=metadata,
                  normalizer_version=NORMALIZER_VERSION)
    try:
        if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_BYTES:
            raise NormalizationError("invalid_payload_bytes")
        body = decode(payload)
        if not isinstance(body, dict) or body.get("type") != "FeatureCollection":
            raise NormalizationError("feature_collection_required")
        features = body.get("features")
        native_metadata = body.get("metadata")
        if not isinstance(features, list) or not isinstance(native_metadata, dict):
            raise NormalizationError("features_and_metadata_required")
        generated = native_metadata.get("generated")
        count = native_metadata.get("count")
        status = native_metadata.get("status")
        metadata.update(
            generated_at=_millis(generated) if generated is not None else None,
            generated_epoch_ms=generated,
            count=_integer(count) if count is not None else None,
            status=_integer(status) if status is not None else None,
            title=_text(native_metadata.get("title"), optional=True),
            api=_text(native_metadata.get("api"), optional=True),
            url=_text(native_metadata.get("url"), optional=True),
            duplicate_rows=0,
        )
        if count is not None and count != len(features):
            raise NormalizationError("feature_count_mismatch")
        if status is not None and status != 200:
            raise NormalizationError("provider_status_not_success")
    except (NormalizationError, ContractError) as error:
        # Keep only fixed diagnostic reasons, not arbitrary provider content.
        reason = str(error)
        report["quarantined"].append(dict(row_index=None, reason=reason))
        return report

    grouped = defaultdict(list)
    invalid_ids = set()
    for index, feature in enumerate(features):
        try:
            row = _feature(feature, index)
            grouped[row["event_id"]].append(row)
        except (NormalizationError, ContractError) as error:
            quarantine = dict(row_index=index, reason=str(error))
            # A malformed duplicate of the same event must not let the other
            # row through as if the capture contained an unambiguous version.
            # Preserve only a usable native ID so staging can also mark an
            # earlier archived observation as ambiguous after a later bad row.
            # Do not repair malformed IDs or guess a revision from bad fields.
            native_id = feature.get("id") if isinstance(feature, dict) else None
            if isinstance(native_id, str) and native_id.strip() and native_id == native_id.strip():
                quarantine["event_id"] = native_id
                invalid_ids.add(native_id)
            report["quarantined"].append(quarantine)
    for event_id, rows in grouped.items():
        semantic = [json.dumps({k: v for k, v in row.items() if k != "row_index"},
                               sort_keys=True, separators=(",", ":")) for row in rows]
        if len(set(semantic)) != 1 or event_id in invalid_ids:
            for row in rows:
                report["quarantined"].append(dict(row_index=row["row_index"],
                    reason="conflicting_event_rows", event_id=event_id))
        else:
            report["observations"].append(rows[0])
            metadata["duplicate_rows"] += len(rows) - 1
    report["observations"].sort(key=lambda row: row["row_index"])
    report["quarantined"].sort(key=lambda row: -1 if row["row_index"] is None else row["row_index"])
    return report
