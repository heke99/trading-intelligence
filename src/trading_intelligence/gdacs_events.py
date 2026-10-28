"""Read-only GDACS RSS observations, with provider provenance and explicit times.

GDACS is an aggregation/model feed, not independent confirmation of every input.
Alert levels and geographic points are not claims about corporate damage.
"""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from http.client import HTTPException
import json
import math
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from xml.etree import ElementTree

from .contracts import utc
from .event_sources import EventCapture, EventReadError, MAX_BYTES


GDACS_FEED_URL = 'https://www.gdacs.org/xml/rss.xml'
FORMAT = 'gdacs_rss_v1'
NORMALIZER_VERSION = 'gdacs-rss-1'
GDACS = '{http://www.gdacs.org}'
GEO = '{http://www.w3.org/2003/01/geo/wgs84_pos#}'
GEORSS = '{http://www.georss.org/georss}'
EVENT_TYPES = {'EQ': 'earthquake', 'TC': 'tropical_cyclone', 'FL': 'flood',
               'DR': 'drought', 'WF': 'wildfire', 'VO': 'volcanic_activity',
               'TS': 'tsunami'}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class GdacsEventReader:
    """One bounded GET to the official all-events RSS feed; no linked fetches."""
    def __init__(self, *, timeout=10, clock=None, opener=None):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise EventReadError('A finite positive bounded timeout is required')
        self.source_url = GDACS_FEED_URL
        self._timeout = timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._opener = opener or build_opener(
            _NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))

    def read(self):
        if self.source_url != GDACS_FEED_URL:
            raise EventReadError('GDACS reader endpoint changed')
        request = Request(GDACS_FEED_URL, method='GET', headers={
            'User-Agent': 'TradingIntelligence-event-capture/1',
            'Accept': 'application/rss+xml, application/xml, text/xml',
            'Accept-Encoding': 'identity'})
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200 or response.geturl() != GDACS_FEED_URL:
                    raise EventReadError('Unexpected GDACS response status or endpoint')
                media = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                encoding = response.headers.get('Content-Encoding', 'identity').strip().lower()
                if media not in {'application/rss+xml', 'application/xml', 'text/xml'}:
                    raise EventReadError('Expected a GDACS RSS/XML response')
                if encoding not in {'', 'identity'}:
                    raise EventReadError('Expected an uncompressed GDACS response')
                payload = response.read(MAX_BYTES + 1)
        except EventReadError:
            raise
        except HTTPError as error:
            status = str(error.code) if type(error.code) is int and 100 <= error.code <= 599 else 'unknown'
            error.close()
            raise EventReadError(f'GDACS HTTP failure ({status}); details omitted; no retry') from None
        except (URLError, OSError, HTTPException, UnicodeError, ValueError):
            raise EventReadError('GDACS connection failed; no retry or fallback') from None
        return EventCapture(payload, self._clock(), GDACS_FEED_URL,
                            format=FORMAT, transport='declared_http_get')


class _Invalid(ValueError):
    pass


def _element(parent, tag, *, required=False):
    found = parent.findall(tag)
    if len(found) > 1:
        raise _Invalid('duplicate_xml_field')
    if not found:
        if required:
            raise _Invalid('missing_xml_field')
        return None
    return found[0]


def _text(parent, tag, *, required=False):
    node = _element(parent, tag, required=required)
    value = None if node is None else node.text
    if value is None or not value.strip():
        if required:
            raise _Invalid('missing_xml_text')
        return None
    value = value.strip()
    if len(value) > 4096 or list(node):
        raise _Invalid('invalid_xml_text')
    return value


def _date(value):
    if not isinstance(value, str):
        raise _Invalid('missing_provider_time')
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (TypeError, ValueError, OverflowError):
            raise _Invalid('invalid_provider_time') from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _Invalid('provider_timezone_required')
    return utc(parsed)


def _number(value, *, lower=None, upper=None):
    if not isinstance(value, str) or not value.strip():
        raise _Invalid('missing_numeric_value')
    try:
        parsed = Decimal(value.strip())
        number = float(parsed)
    except (InvalidOperation, ValueError, OverflowError):
        raise _Invalid('invalid_numeric_value') from None
    if (not parsed.is_finite() or not math.isfinite(number)
            or (lower is not None and number < lower) or (upper is not None and number > upper)):
        raise _Invalid('numeric_value_out_of_range')
    return number


def _coordinates(item):
    point = _element(item, GEO+'Point')
    latitude = longitude = None
    if point is not None:
        latitude = _number(_text(point, GEO+'lat', required=True), lower=-90, upper=90)
        longitude = _number(_text(point, GEO+'long', required=True), lower=-180, upper=180)
    georss = _text(item, GEORSS+'point')
    if georss is not None:
        parts = georss.split()
        if len(parts) != 2:
            raise _Invalid('invalid_georss_point')
        geo_lat = _number(parts[0], lower=-90, upper=90)
        geo_lon = _number(parts[1], lower=-180, upper=180)
        if latitude is not None and (abs(latitude-geo_lat) > 1e-6 or abs(longitude-geo_lon) > 1e-6):
            raise _Invalid('conflicting_xml_coordinates')
        latitude, longitude = geo_lat, geo_lon
    if latitude is None:
        raise _Invalid('event_location_unknown')
    return latitude, longitude


def _item(item, index):
    code = _text(item, GDACS+'eventtype', required=True)
    identity = _text(item, GDACS+'eventid', required=True)
    episode = _text(item, GDACS+'episodeid', required=True)
    if (re.fullmatch(r'[A-Z][A-Z0-9]{0,15}', code) is None
            or re.fullmatch(r'[0-9]+', identity) is None
            or re.fullmatch(r'[0-9]+', episode) is None):
        raise _Invalid('invalid_gdacs_identity')
    published_raw = _text(item, 'pubDate')
    modified_raw = _text(item, GDACS+'datemodified')
    published = _date(published_raw) if published_raw is not None else None
    updated = _date(modified_raw) if modified_raw is not None else published
    if updated is None:
        raise _Invalid('provider_update_time_unknown')
    occurred_raw = _text(item, GDACS+'fromdate', required=True)
    occurred = _date(occurred_raw)
    if updated < occurred:
        raise _Invalid('provider_update_before_event')
    # Publication and modification are separate provider fields. In the live
    # RSS, publication can follow modification (e.g. later dissemination of an
    # existing calculation). Do not invent a universal ordering between them.
    ended_raw = _text(item, GDACS+'todate')
    ended = _date(ended_raw) if ended_raw is not None else None
    if ended is not None and ended < occurred:
        raise _Invalid('event_end_before_start')
    latitude, longitude = _coordinates(item)
    version = _text(item, GDACS+'version')
    if version is not None and re.fullmatch(r'[0-9]+', version) is None:
        raise _Invalid('invalid_provider_version')
    current_raw = _text(item, GDACS+'iscurrent')
    if current_raw is not None and current_raw.lower() not in {'true', 'false'}:
        raise _Invalid('invalid_current_flag')
    iscurrent = current_raw.lower() == 'true' if current_raw is not None else None
    severity = _element(item, GDACS+'severity')
    severity_value = None
    severity_unit = None
    if severity is not None:
        severity_unit = severity.get('unit')
        if severity_unit is not None and (not severity_unit.strip() or len(severity_unit) > 128):
            raise _Invalid('invalid_severity_unit')
        if severity.get('value') is not None:
            severity_value = _number(severity.get('value'))
    sources = sorted({node.get('source').strip() for node in item.findall(
        GDACS+'resources/'+GDACS+'resource') if node.get('source') and node.get('source').strip()})
    return dict(event_id=code+':'+identity,
        revision_id=':'.join((episode, version or 'unknown', updated)),
        event_type=EVENT_TYPES.get(code, 'gdacs:'+code), occurred_at=occurred,
        provider_updated_at=updated, published_at=published,
        longitude=longitude, latitude=latitude, depth_km=None,
        magnitude=severity_value if code == 'EQ' and severity_unit == 'M' else None,
        magnitude_type=None, place=_text(item, GDACS+'country'),
        title=_text(item, 'title'), status='current' if iscurrent else (
            'not_current' if iscurrent is False else None),
        source_event_url=_text(item, 'link'), detail_url=None,
        tsunami_flag=None, tsunami_confirmed=None,
        provider='GDACS', gdacs_event_type=code, gdacs_event_id=identity,
        gdacs_episode_id=episode, gdacs_version=version, provider_is_current=iscurrent,
        alert_level=_text(item, GDACS+'alertlevel'),
        severity_value=severity_value, severity_unit=severity_unit,
        event_end_at=ended, original_source=None, independent_confirmation=False,
        provider_resource_sources=sources,
        provider_updated_basis='gdacs:datemodified' if modified_raw is not None else 'rss:pubDate',
        original_time_values=dict(fromdate=occurred_raw, todate=ended_raw,
            pubDate=published_raw, datemodified=modified_raw), row_index=index)


def _quarantine_identity(item):
    """Retain a known native identity even if another field prevents admission."""
    identity = {}
    try:
        code = _text(item, GDACS+'eventtype', required=True)
        event_id = _text(item, GDACS+'eventid', required=True)
        if (re.fullmatch(r'[A-Z][A-Z0-9]{0,15}', code) is None
                or re.fullmatch(r'[0-9]+', event_id) is None):
            return identity
        identity['event_id'] = code+':'+event_id
    except _Invalid:
        return identity
    try:
        episode = _text(item, GDACS+'episodeid', required=True)
        version = _text(item, GDACS+'version')
        modified = _text(item, GDACS+'datemodified')
        published = _text(item, 'pubDate')
        if (re.fullmatch(r'[0-9]+', episode) is None
                or (version is not None and re.fullmatch(r'[0-9]+', version) is None)):
            return identity
        updated = _date(modified if modified is not None else published)
        identity['revision_id'] = ':'.join((episode, version or 'unknown', updated))
    except _Invalid:
        pass
    return identity


def normalize_gdacs(payload):
    """Normalize supplied RSS bytes; preserve invalid rows as quarantine reasons."""
    report = dict(observations=[], quarantined=[], metadata={}, normalizer_version=NORMALIZER_VERSION)
    try:
        if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_BYTES:
            raise _Invalid('invalid_payload_bytes')
        text = payload.decode('utf-8-sig')
        if '\x00' in text or re.search(r'<!\s*(?:DOCTYPE|ENTITY)', text, re.I):
            raise _Invalid('xml_dtd_or_entity_forbidden')
        declaration = re.match(r'\s*<\?xml\s+([^?]*)\?>', text)
        if declaration:
            encoding = re.search(r'encoding\s*=\s*[\"\x27]([^\"\x27]+)', declaration.group(1), re.I)
            if encoding and encoding.group(1).lower() not in {'utf-8', 'utf8'}:
                raise _Invalid('utf8_xml_required')
        root = ElementTree.fromstring(text)
        if root.tag != 'rss':
            raise _Invalid('rss_envelope_required')
        channel = _element(root, 'channel', required=True)
        items = channel.findall('item')
        if len(items) > 10000:
            raise _Invalid('too_many_rss_items')
        built = _text(channel, 'lastBuildDate')
        report['metadata'] = dict(generated_at=_date(built) if built is not None else None,
            item_count=len(items), provider='GDACS', independent_confirmation=False,
            geometry_role='provider_reference_point_not_impact_area',
            title=_text(channel, 'title'))
    except (UnicodeError, ElementTree.ParseError, _Invalid):
        report['quarantined'].append(dict(row_index=None, reason='invalid_gdacs_rss_envelope'))
        return report
    grouped = defaultdict(list)
    invalid_ids = set()
    for index, item in enumerate(items):
        try:
            row = _item(item, index)
            grouped[(row['event_id'], row['revision_id'])].append(row)
        except _Invalid as error:
            identity = _quarantine_identity(item)
            report['quarantined'].append(dict(row_index=index, reason=str(error), **identity))
            if identity.get('event_id') is not None:
                invalid_ids.add(identity['event_id'])
    update_revisions = defaultdict(set)
    for (identity, revision), rows in grouped.items():
        update_revisions[(identity, rows[0]['provider_updated_at'])].add(revision)
    for (identity, revision), rows in grouped.items():
        versions = [json.dumps({k:v for k,v in row.items() if k != 'row_index'},
                               sort_keys=True, separators=(',', ':'), allow_nan=False) for row in rows]
        # Distinct episodes/updates may legitimately coexist. Keep their
        # revisions, but never invent precedence for conflicting revisions
        # sharing exactly the same native modification time.
        ambiguous_update = len(update_revisions[(identity, rows[0]['provider_updated_at'])]) > 1
        if identity in invalid_ids or len(set(versions)) != 1 or ambiguous_update:
            for row in rows:
                report['quarantined'].append(dict(row_index=row['row_index'],
                    reason='conflicting_event_rows', event_id=identity, revision_id=revision))
        else:
            report['observations'].append(rows[0])
    return report
