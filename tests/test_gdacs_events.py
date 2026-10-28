"""Synthetic RSS-shaped fixtures and injected transport, never actual disaster data."""
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError

from trading_intelligence.event_sources import EventReadError, MAX_BYTES
from trading_intelligence.event_sources import EventCapture
from trading_intelligence.contracts import DataOrigin, Use
from trading_intelligence.event_store import EventStore
from trading_intelligence.gdacs_events import (
    FORMAT, GDACS_FEED_URL, GdacsEventReader, normalize_gdacs)


T = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
ITEM = '''<item><title>Synthetic test disaster</title><link>https://example.invalid/event</link>
<pubDate>Sat, 10 Jan 2026 10:10:00 GMT</pubDate>
<gdacs:datemodified>Sat, 10 Jan 2026 10:20:00 GMT</gdacs:datemodified>
<gdacs:fromdate>Sat, 10 Jan 2026 10:00:00 GMT</gdacs:fromdate>
<gdacs:todate>Sat, 10 Jan 2026 10:00:00 GMT</gdacs:todate>
<gdacs:eventtype>EQ</gdacs:eventtype><gdacs:eventid>100</gdacs:eventid>
<gdacs:episodeid>101</gdacs:episodeid><gdacs:version>1</gdacs:version>
<gdacs:iscurrent>true</gdacs:iscurrent><gdacs:alertlevel>Green</gdacs:alertlevel>
<gdacs:country>Invented region</gdacs:country>
<gdacs:severity unit="M" value="0">Synthetic severity</gdacs:severity>
<geo:Point><geo:lat>35.0</geo:lat><geo:long>139.0</geo:long></geo:Point>
<georss:point>35.0 139.0</georss:point>
<gdacs:resources><gdacs:resource source="EC-JRC" url="https://example.invalid/no-fetch"/></gdacs:resources>
</item>'''


def fixture(item=ITEM):
    return ('''<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"
 xmlns:gdacs="http://www.gdacs.org" xmlns:geo="http://www.w3.org/2003/01/geo/wgs84_pos#"
 xmlns:georss="http://www.georss.org/georss"><channel><title>Invented feed</title>'''+
        item+'</channel></rss>').encode()


class Response:
    def __init__(self, payload=None, *, status=200, url=GDACS_FEED_URL,
                 media='application/xml', encoding='identity'):
        self.payload = fixture() if payload is None else payload
        self.status, self.url = status, url
        self.headers = Message()
        self.headers['Content-Type'] = media
        self.headers['Content-Encoding'] = encoding
        self.read_limit = None
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def geturl(self): return self.url
    def read(self, size):
        self.read_limit = size
        return self.payload[:size]


class Opener:
    def __init__(self, response=None, error=None):
        self.response = response or Response()
        self.error = error
        self.calls = []
    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        return self.response


class GdacsNormalizationTests(unittest.TestCase):
    def row(self, item=ITEM):
        result = normalize_gdacs(fixture(item))
        self.assertEqual(result['quarantined'], [])
        self.assertEqual(len(result['observations']), 1)
        return result['observations'][0]

    def test_distinct_occurrence_publication_modification_and_zero_magnitude(self):
        row = self.row()
        self.assertEqual(row['event_id'], 'EQ:100')
        self.assertEqual(row['event_type'], 'earthquake')
        self.assertEqual(row['occurred_at'], '2026-01-10T10:00:00.000000Z')
        self.assertEqual(row['published_at'], '2026-01-10T10:10:00.000000Z')
        self.assertEqual(row['provider_updated_at'], '2026-01-10T10:20:00.000000Z')
        self.assertEqual(row['provider_updated_basis'], 'gdacs:datemodified')
        self.assertEqual(row['magnitude'], 0)
        self.assertIsNone(row['depth_km'])
        self.assertIsNone(row['tsunami_confirmed'])
        self.assertFalse(row['independent_confirmation'])
        self.assertIsNone(row['original_source'])
        self.assertEqual(row['provider_resource_sources'], ['EC-JRC'])

    def test_missing_publication_stays_unknown(self):
        row = self.row(ITEM.replace('<pubDate>Sat, 10 Jan 2026 10:10:00 GMT</pubDate>', ''))
        self.assertIsNone(row['published_at'])
        self.assertEqual(row['provider_updated_at'], '2026-01-10T10:20:00.000000Z')

    def test_pubdate_update_fallback_is_explicit(self):
        row = self.row(ITEM.replace('<gdacs:datemodified>Sat, 10 Jan 2026 10:20:00 GMT</gdacs:datemodified>', ''))
        self.assertEqual(row['provider_updated_basis'], 'rss:pubDate')
        self.assertEqual(row['provider_updated_at'], row['published_at'])

    def test_later_publication_does_not_rewrite_provider_modified_time(self):
        row = self.row(ITEM.replace('Sat, 10 Jan 2026 10:10:00 GMT',
                                   'Sat, 10 Jan 2026 10:30:00 GMT'))
        self.assertEqual(row['published_at'], '2026-01-10T10:30:00.000000Z')
        self.assertEqual(row['provider_updated_at'], '2026-01-10T10:20:00.000000Z')

    def test_types_and_severity_units_are_not_equated(self):
        for code, kind in [('TC', 'tropical_cyclone'), ('FL', 'flood'),
                           ('DR', 'drought'), ('WF', 'wildfire'), ('VO', 'volcanic_activity'),
                           ('XX', 'gdacs:XX')]:
            with self.subTest(code=code):
                row = self.row(ITEM.replace('>EQ<', '>'+code+'<').replace('unit="M"', 'unit="km2"'))
                self.assertEqual(row['event_type'], kind)
                self.assertEqual(row['event_id'], code+':100')
                self.assertIsNone(row['magnitude'])
                self.assertEqual(row['severity_unit'], 'km2')

    def test_alert_and_noncurrent_status_do_not_assert_resolution(self):
        row = self.row(ITEM.replace('>true<', '>false<').replace('>Green<', '>Red<'))
        self.assertFalse(row['provider_is_current'])
        self.assertEqual(row['status'], 'not_current')
        self.assertEqual(row['alert_level'], 'Red')
        self.assertNotIn('resolved', row)

    def test_malformed_xml_and_dtd_entities_rejected(self):
        for payload in (b'<rss>', b'<root/>', b'<!DOCTYPE rss [<!ENTITY x "danger">]><rss/>',
                        b'<?xml version="1.0" encoding="UTF-16"?><rss/>',
                        '<rss/>'.encode('utf-16'), b''):
            with self.subTest(payload=payload[:30]):
                result = normalize_gdacs(payload)
                self.assertEqual(result['observations'], [])
                self.assertEqual(result['quarantined'][0]['reason'], 'invalid_gdacs_rss_envelope')

    def test_bad_row_does_not_discard_good_row(self):
        bad = ITEM.replace('<gdacs:eventid>100', '<gdacs:eventid>200').replace('>35.0<', '>NaN<')
        result = normalize_gdacs(fixture(ITEM+bad))
        self.assertEqual(len(result['observations']), 1)
        self.assertEqual(len(result['quarantined']), 1)
        self.assertEqual(result['quarantined'][0]['row_index'], 1)
        self.assertEqual(result['quarantined'][0]['event_id'], 'EQ:200')
        self.assertEqual(result['quarantined'][0]['revision_id'],
                         '101:1:2026-01-10T10:20:00.000000Z')

    def test_missing_coordinates_are_not_zero(self):
        item = ITEM.replace('<geo:Point><geo:lat>35.0</geo:lat><geo:long>139.0</geo:long></geo:Point>', '').replace('<georss:point>35.0 139.0</georss:point>', '')
        result = normalize_gdacs(fixture(item))
        self.assertEqual(result['observations'], [])
        self.assertEqual(result['quarantined'][0]['reason'], 'event_location_unknown')

    def test_conflicting_geographic_fields_block_row(self):
        result = normalize_gdacs(fixture(ITEM.replace('>35.0 139.0<', '>36.0 139.0<')))
        self.assertEqual(result['observations'], [])
        self.assertEqual(result['quarantined'][0]['reason'], 'conflicting_xml_coordinates')

    def test_bad_times_and_units_quarantined(self):
        variants = [ITEM.replace('Sat, 10 Jan 2026 10:00:00 GMT', '2026-01-10T10:00:00'),
                    ITEM.replace('Sat, 10 Jan 2026 10:20:00 GMT', 'Sat, 10 Jan 2026 09:00:00 GMT'),
                    ITEM.replace('value="0"', 'value="Infinity"'),
                    ITEM.replace('<gdacs:episodeid>101</gdacs:episodeid>', ''),
                    ITEM.replace('>true<', '>unknown<'),
                    ITEM.replace('>35.0<', '>91<')]
        for item in variants:
            with self.subTest(item=item):
                result = normalize_gdacs(fixture(item))
                self.assertEqual(result['observations'], [])
                self.assertTrue(result['quarantined'])

    def test_duplicate_exact_rows_collapse_but_conflicts_quarantine(self):
        self.assertEqual(len(normalize_gdacs(fixture(ITEM+ITEM))['observations']), 1)
        result = normalize_gdacs(fixture(ITEM+ITEM.replace('>Green<', '>Orange<')))
        self.assertEqual(result['observations'], [])
        self.assertEqual(len(result['quarantined']), 2)

    def test_bad_duplicate_cannot_leave_good_version(self):
        result = normalize_gdacs(fixture(ITEM+ITEM.replace('>true<', '>broken<')))
        self.assertEqual(result['observations'], [])
        self.assertEqual(len(result['quarantined']), 2)

    def test_distinct_episode_updates_retained_but_equal_update_conflict_blocked(self):
        newer = ITEM.replace('<gdacs:episodeid>101', '<gdacs:episodeid>102').replace(
            'Sat, 10 Jan 2026 10:20:00 GMT', 'Sat, 10 Jan 2026 10:30:00 GMT')
        result = normalize_gdacs(fixture(ITEM+newer))
        self.assertEqual(len(result['observations']), 2)
        self.assertEqual(result['quarantined'], [])
        ambiguous = ITEM.replace('<gdacs:episodeid>101', '<gdacs:episodeid>102')
        result = normalize_gdacs(fixture(ITEM+ambiguous))
        self.assertEqual(result['observations'], [])
        self.assertEqual(len(result['quarantined']), 2)

    def test_two_gdacs_revisions_stage_and_latest_is_selected(self):
        newer = ITEM.replace('<gdacs:episodeid>101', '<gdacs:episodeid>102').replace(
            'Sat, 10 Jan 2026 10:20:00 GMT', 'Sat, 10 Jan 2026 10:30:00 GMT')
        with tempfile.TemporaryDirectory() as directory:
            with EventStore(Path(directory)/'events.db', clock=lambda:T) as store:
                store.register_source('synthetic-gdacs', DataOrigin.SYNTHETIC)
                store.set_permissions('synthetic-gdacs', known_at=T.replace(hour=0),
                                      uses={Use.STORAGE, Use.RESEARCH})
                capture = EventCapture(fixture(ITEM+newer), T, GDACS_FEED_URL, format=FORMAT)
                result = store.stage(source_id='synthetic-gdacs', import_id='first', capture=capture)
                self.assertEqual(len(result['observations']), 2)
                event = store.event_as_of('synthetic-gdacs', 'EQ:100', as_of=T)
                self.assertEqual(event['gdacs_episode_id'], '102')
                self.assertEqual(event['provider_updated_at'], '2026-01-10T10:30:00.000000Z')

    def test_quarantined_duplicate_marks_prior_revision_ambiguous(self):
        clock = [T]
        with tempfile.TemporaryDirectory() as directory:
            with EventStore(Path(directory)/'events.db', clock=lambda:clock[0]) as store:
                store.register_source('synthetic-gdacs', DataOrigin.SYNTHETIC)
                store.set_permissions('synthetic-gdacs', known_at=T.replace(hour=0),
                                      uses={Use.STORAGE, Use.RESEARCH})
                store.stage(source_id='synthetic-gdacs', import_id='first',
                    capture=EventCapture(fixture(), T, GDACS_FEED_URL, format=FORMAT))
                clock[0] += timedelta(seconds=1)
                conflicting = fixture(ITEM+ITEM.replace('>Green<', '>Orange<'))
                report = store.stage(source_id='synthetic-gdacs', import_id='conflicting',
                    capture=EventCapture(conflicting, clock[0], GDACS_FEED_URL, format=FORMAT))
                self.assertEqual(report['state'], 'quarantined')
                self.assertTrue(store.event_as_of('synthetic-gdacs', 'EQ:100',
                    as_of=clock[0])['unresolved_revision_conflict'])
                self.assertFalse(store.event_as_of('synthetic-gdacs', 'EQ:100',
                    as_of=T)['unresolved_revision_conflict'])

    def test_duplicate_xml_field_and_duplicate_envelope_rejected(self):
        result = normalize_gdacs(fixture(ITEM.replace('<gdacs:version>1</gdacs:version>', '<gdacs:version>1</gdacs:version><gdacs:version>2</gdacs:version>')))
        self.assertEqual(result['observations'], [])
        self.assertEqual(result['quarantined'][0]['reason'], 'duplicate_xml_field')
        result = normalize_gdacs(b'<rss><channel/><channel/></rss>')
        self.assertEqual(result['quarantined'][0]['reason'], 'invalid_gdacs_rss_envelope')


class GdacsReaderTests(unittest.TestCase):
    def test_fixed_get_and_format_and_bounded_read(self):
        response = Response()
        opener = Opener(response)
        captured = GdacsEventReader(clock=lambda: T, opener=opener).read()
        self.assertEqual(captured.source_url, GDACS_FEED_URL)
        self.assertEqual(captured.format, FORMAT)
        self.assertEqual(captured.transport, 'declared_http_get')
        self.assertEqual(captured.received_at, T)
        self.assertEqual(response.read_limit, MAX_BYTES+1)
        self.assertEqual(opener.calls[0][0].get_method(), 'GET')
        self.assertEqual(opener.calls[0][0].full_url, GDACS_FEED_URL)

    def test_bad_endpoint_status_media_encoding_and_timeout_rejected(self):
        for response in (Response(status=302), Response(url='https://example.invalid/redirect'),
                         Response(media='text/html'), Response(encoding='gzip')):
            with self.subTest(response=response), self.assertRaises(EventReadError):
                GdacsEventReader(clock=lambda: T, opener=Opener(response)).read()
        for value in (0, -1, 31, True, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(EventReadError):
                GdacsEventReader(timeout=value)

    def test_network_error_does_not_echo_provider_details_or_retry(self):
        opener = Opener(error=URLError('secret provider response'))
        with self.assertRaises(EventReadError) as error:
            GdacsEventReader(clock=lambda:T, opener=opener).read()
        self.assertNotIn('secret', str(error.exception))
        self.assertEqual(len(opener.calls), 1)

    def test_oversize_bytes_rejected(self):
        with self.assertRaises(EventReadError):
            GdacsEventReader(clock=lambda:T, opener=Opener(Response(b'x'*(MAX_BYTES+1)))).read()


if __name__ == '__main__':
    unittest.main()
