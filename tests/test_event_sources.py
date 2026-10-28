"""Invented USGS-shaped observations; transport is injected, never networked."""

from copy import deepcopy
from datetime import datetime, timezone
from email.message import Message
from io import BytesIO
import json
import unittest
from urllib.error import HTTPError, URLError

from trading_intelligence.contracts import ContractError
from trading_intelligence.event_sources import (
    EventCapture, EventReadError, MAX_BYTES, NORMALIZER_VERSION,
    UsgsEventReader, USGS_FEEDS, endpoint, normalize_usgs,
)


T = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
TIME = 1768046400000


def feature(event_id="invented-1", **properties):
    props = dict(type="earthquake", time=TIME, updated=TIME + 1000,
                 mag=0, magType="mw", place="Invented region", title="Invented event",
                 status="automatic", tsunami=1)
    props.update(properties)
    return dict(type="Feature", id=event_id, properties=props,
                geometry=dict(type="Point", coordinates=[24.5, 61.2, 8.0]))


def fixture(*features, **metadata):
    features = list(features) if features else [feature()]
    meta = dict(generated=TIME + 2000, count=len(features), status=200,
                title="Invented feed", api="1.10.3")
    meta.update(metadata)
    return dict(type="FeatureCollection", metadata=meta, features=features)


def encoded(body):
    return json.dumps(body).encode()


class Response:
    def __init__(self, payload=None, *, status=200, url=None,
                 media="application/json; charset=utf-8", encoding="identity"):
        self.payload = encoded(fixture()) if payload is None else payload
        self.status = status
        self.url = url or endpoint()
        self.headers = Message()
        self.headers["Content-Type"] = media
        self.headers["Content-Encoding"] = encoding
        self.read_size = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def geturl(self):
        return self.url

    def read(self, size):
        self.read_size = size
        return self.payload[:size]


class Opener:
    def __init__(self, response=None, *, error=None):
        self.response = response or Response()
        self.error = error
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        return self.response


class EventReaderTests(unittest.TestCase):
    def test_capture_requires_explicit_allowed_url_and_transport(self):
        capture = EventCapture(b"{}", T, endpoint())
        self.assertEqual(capture.transport, "supplied_bytes")
        self.assertNotIn("{}", repr(capture))
        for url in ("http://earthquake.usgs.gov/", endpoint() + "?token=private",
                    "https://example.com/feed", None, []):
            with self.subTest(url=url), self.assertRaises(EventReadError):
                EventCapture(b"{}", T, url)
        for transport in ("verified", None, []):
            with self.subTest(transport=transport), self.assertRaises(EventReadError):
                EventCapture(b"{}", T, endpoint(), transport=transport)
        with self.assertRaises(EventReadError):
            EventCapture(b"{}", T, endpoint(), format="arbitrary_news")

    def test_capture_validates_bytes_time_and_size(self):
        for value in (b"", "{}", None, bytearray(b"{}")):
            with self.subTest(value=value), self.assertRaises(EventReadError):
                EventCapture(value, T, endpoint())
        with self.assertRaises(ContractError):
            EventCapture(b"{}", T.replace(tzinfo=None), endpoint())
        with self.assertRaises(EventReadError):
            EventCapture(b"x" * (MAX_BYTES + 1), T, endpoint())

    def test_only_fixed_named_feeds_are_selected(self):
        for name, url in USGS_FEEDS.items():
            self.assertEqual(endpoint(name), url)
        for name in ("../../private", endpoint(), "all_hour?x", None, []):
            with self.subTest(name=name), self.assertRaises(EventReadError):
                endpoint(name)

    def test_public_get_is_bounded_and_capture_time_is_post_response(self):
        response = Response()
        opener = Opener(response)
        capture = UsgsEventReader(opener=opener, clock=lambda: T).read()
        request, timeout = opener.calls[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.full_url, endpoint())
        self.assertEqual(timeout, 10)
        self.assertEqual(response.read_size, MAX_BYTES + 1)
        self.assertEqual(capture.received_at, T)
        self.assertEqual(capture.transport, "declared_http_get")
        self.assertNotIn("Authorization", request.headers)

    def test_geojson_response_and_configured_feed(self):
        url = endpoint("all_day")
        opener = Opener(Response(url=url, media="application/geo+json"))
        result = UsgsEventReader("all_day", opener=opener, clock=lambda: T).read()
        self.assertEqual(result.source_url, url)

    def test_mutated_reader_url_cannot_bypass_fixed_capability(self):
        opener = Opener()
        reader = UsgsEventReader(opener=opener)
        reader.source_url = "https://example.com/private"
        with self.assertRaises(EventReadError):
            reader.read()
        self.assertEqual(opener.calls, [])

    def test_bad_status_redirect_content_or_encoding_is_rejected(self):
        cases = (dict(status=302), dict(url="https://example.com/private"),
                 dict(media="text/html"), dict(encoding="gzip"))
        for args in cases:
            with self.subTest(args=args), self.assertRaises(EventReadError):
                UsgsEventReader(opener=Opener(Response(**args))).read()

    def test_http_and_network_errors_hide_details_and_do_not_retry(self):
        errors = (URLError("private-diagnostic"), OSError("private-diagnostic"),
                  HTTPError(endpoint(), 429, "private-diagnostic", {}, BytesIO(b"private")))
        for error in errors:
            opener = Opener(error=error)
            with self.subTest(error=type(error)), self.assertRaises(EventReadError) as raised:
                UsgsEventReader(opener=opener).read()
            self.assertNotIn("private", str(raised.exception))
            self.assertEqual(len(opener.calls), 1)

    def test_invalid_timeout_is_rejected(self):
        for timeout in (0, -1, 31, float("inf"), float("nan"), True, "10", None, 10 ** 1000):
            with self.subTest(timeout=str(timeout)[:20]), self.assertRaises(EventReadError):
                UsgsEventReader(timeout=timeout)


class EventNormalizerTests(unittest.TestCase):
    def normalize(self, body):
        return normalize_usgs(encoded(body))

    def test_provider_update_is_revision_and_publication_remains_unknown(self):
        report = self.normalize(fixture())
        self.assertEqual(report["normalizer_version"], NORMALIZER_VERSION)
        self.assertEqual(report["quarantined"], [])
        row = report["observations"][0]
        self.assertEqual(row["revision_id"], str(TIME + 1000))
        self.assertLess(row["occurred_at"], row["provider_updated_at"])
        self.assertIsNone(row["published_at"])
        self.assertEqual(row["magnitude"], 0)
        self.assertEqual(report["metadata"]["generated_at"], "2026-01-10T12:00:02.000000Z")

    def test_tsunami_flag_is_not_confirmation(self):
        row = self.normalize(fixture())["observations"][0]
        self.assertEqual(row["tsunami_flag"], 1)
        self.assertIsNone(row["tsunami_confirmed"])

    def test_nullable_fields_and_negative_magnitude_are_preserved(self):
        for magnitude in (None, -0.8, 0):
            body = fixture(feature(mag=magnitude, magType=None, place=None, status=None, tsunami=None))
            row = self.normalize(body)["observations"][0]
            self.assertEqual(row["magnitude"], magnitude)
            self.assertIsNone(row["status"])

    def test_longitude_latitude_order_and_range(self):
        row = self.normalize(fixture())["observations"][0]
        self.assertEqual((row["longitude"], row["latitude"], row["depth_km"]), (24.5, 61.2, 8.0))
        for coordinates in ([181, 0, 0], [0, 91, 0], [0, 0], [True, 0, 0], [0, "0", 0]):
            body = fixture()
            body["features"][0]["geometry"]["coordinates"] = coordinates
            with self.subTest(coordinates=coordinates):
                report = self.normalize(body)
                self.assertEqual(report["observations"], [])
                self.assertEqual(len(report["quarantined"]), 1)

    def test_arbitrary_native_event_type_is_not_relabelled_earthquake(self):
        row = self.normalize(fixture(feature(type="quarry blast")))["observations"][0]
        self.assertEqual(row["event_type"], "quarry blast")

    def test_bad_row_does_not_discard_valid_row(self):
        invalid = feature("bad", mag="unknown")
        report = self.normalize(fixture(invalid, feature()))
        self.assertEqual(report["observations"][0]["event_id"], "invented-1")
        self.assertEqual(report["quarantined"][0]["row_index"], 0)

    def test_boolean_numeric_fields_are_not_numbers(self):
        for field in ("time", "updated", "mag", "tsunami"):
            body = fixture(feature(**{field: True}))
            with self.subTest(field=field):
                self.assertEqual(self.normalize(body)["observations"], [])

    def test_invalid_epoch_and_update_before_occurrence(self):
        for properties in (dict(time=10 ** 100), dict(updated=TIME - 1), dict(time=1.5)):
            with self.subTest(properties=properties):
                self.assertTrue(self.normalize(fixture(feature(**properties)))["quarantined"])

    def test_exact_duplicate_rows_consolidate_without_independent_evidence(self):
        row = feature()
        report = self.normalize(fixture(row, deepcopy(row)))
        self.assertEqual(len(report["observations"]), 1)
        self.assertEqual(report["metadata"]["duplicate_rows"], 1)
        self.assertEqual(report["quarantined"], [])

    def test_conflicting_same_revision_and_multiple_revisions_quarantine_all(self):
        for second in (feature(mag=3), feature(updated=TIME + 3000)):
            report = self.normalize(fixture(feature(), second, feature("other")))
            self.assertEqual([r["event_id"] for r in report["observations"]], ["other"])
            self.assertEqual(len(report["quarantined"]), 2)
            self.assertEqual(report["quarantined"][0]["reason"], "conflicting_event_rows")

    def test_malformed_duplicate_cannot_leave_same_event_accepted(self):
        report = self.normalize(fixture(feature(), feature(mag="invalid")))
        self.assertEqual(report["observations"], [])
        self.assertEqual(len(report["quarantined"]), 2)

    def test_malformed_sole_feature_retains_known_event_identity_for_staging(self):
        report = self.normalize(fixture(feature("known-event", mag="invalid")))
        self.assertEqual(report["observations"], [])
        quarantine = report["quarantined"][0]
        self.assertEqual(quarantine["event_id"], "known-event")
        self.assertEqual(quarantine["reason"], "invalid_number")
        self.assertNotIn("revision_id", quarantine)

    def test_malformed_native_identity_is_neither_repaired_nor_guessed(self):
        for native_id in (None, [], 123, True, "", " ", " event", "event "):
            with self.subTest(native_id=native_id):
                report = self.normalize(fixture(feature(native_id, mag="invalid")))
                self.assertEqual(report["observations"], [])
                self.assertNotIn("event_id", report["quarantined"][0])

    def test_malformed_duplicate_keys_or_nonfinite_json_quarantines_capture(self):
        for payload in (b"bad", b'{"type":"FeatureCollection","type":"other"}',
                        b'{"x":NaN}', b"[]", b"\xff", b"{}", b""):
            with self.subTest(payload=payload):
                report = normalize_usgs(payload)
                self.assertEqual(report["observations"], [])
                self.assertTrue(report["quarantined"])

    def test_json_numeric_overflow_is_not_accepted_as_infinite_coordinate(self):
        payload = encoded(fixture()).replace(b"24.5", b"1e9999")
        self.assertEqual(normalize_usgs(payload)["observations"], [])

    def test_feed_count_status_and_metadata_type_must_be_consistent(self):
        for changes in (dict(count=2), dict(count=True), dict(status=500), dict(generated=True)):
            with self.subTest(changes=changes):
                self.assertEqual(self.normalize(fixture(**changes))["observations"], [])
        body = fixture()
        body["metadata"] = []
        self.assertTrue(self.normalize(body)["quarantined"])

    def test_empty_feature_collection_is_valid(self):
        body = fixture()
        body["features"] = []
        body["metadata"]["count"] = 0
        report = self.normalize(body)
        self.assertEqual(report["observations"], [])
        self.assertEqual(report["quarantined"], [])

    def test_untrusted_feature_urls_are_data_never_requests(self):
        body = fixture(feature(url="https://example.com/untrusted", detail="file:///private"))
        row = self.normalize(body)["observations"][0]
        self.assertEqual(row["detail_url"], "file:///private")
        self.assertEqual(row["source_event_url"], "https://example.com/untrusted")


if __name__ == "__main__":
    unittest.main()
