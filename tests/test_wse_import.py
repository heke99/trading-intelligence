"""Synthetic native order regressions; no external files, accounts or traffic."""
import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from unittest.mock import patch

from scalper_research.market import load_quotes
from scalper_research.wse import FIELDS, _Book, import_wse

BASE_NS = int(datetime(2017, 1, 2, 9, tzinfo=timezone.utc).timestamp()) * 1_000_000_000


def event(offset, action="M", **changes):
    row = {"time": BASE_NS + offset, "priority_date": BASE_NS, "order_date": BASE_NS,
           "symbol_idx": 11322, "price": -1, "agg_volume": 1, "volume": -1,
           "order_id": 3, "num_orders": 1, "side": -1, "order_type": "-1",
           "action_type": action, "price_level": 2}
    return dict(row, **changes)


def rows():
    return [event(1000, "F", order_id=0),
            event(2000, "Y", order_id=1, side=1, price=10000, volume=10, order_type="2"),
            event(3000, "Y", order_id=2, side=2, price=10010, volume=20, order_type="2"),
            event(4000, "A", order_id=3, side=1, price=9999, volume=1, order_type="2"),
            event(1_100_000), event(2_100_000), event(3_100_000)]


def specification(raw=b"fictional-hdf-container", **changes):
    source = {"schema_version": 1, "source_id": "fictional-wse", "symbol": "PEKAO",
              "price_currency": "PLN", "timestamp_basis": "utc_epoch_milliseconds",
              "timezone_evidence": "Fictional UTC nanosecond events projected to causal boundaries.",
              "data_origin": "synthetic_fixture", "usage_rights": "synthetic_only",
              "training_usage_rights": "synthetic_only", "broker_verified": False,
              "training_ready": False, "full_history_verified": False}
    return {"schema_version": 1, "format": "wselob_orders_v1",
            "expected_sha256": hashlib.sha256(raw).hexdigest(), "symbol": "PEKAO",
            "symbol_idx": 11322, "days": ["20170102"], "sample_period_ms": 1,
            "max_event_gap_ms": 10, "source_clock_evidence": "Fictional UTC epoch nanoseconds.",
            "retransmission_completion_policy": "first_non_retransmission_event_assumption",
            "source": source, **changes}


class WseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.file, self.spec, self.out = self.root / "original.h5", self.root / "spec.json", self.root / "out"
        self.write()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, spec=None, raw=b"fictional-hdf-container"):
        self.file.write_bytes(raw)
        self.spec.write_text(json.dumps(spec or specification(raw)))

    def convert(self, events=None):
        with patch("scalper_research.wse._iter_hdf_events", side_effect=lambda _p, _d: iter(events or rows())):
            return import_wse(self.file, self.spec, self.out)

    def quotes(self, result):
        self.assertEqual(result["status"], "completed", result)
        return load_quotes(Path(result["output_csv"]), Path(result["output_metadata"]))

    def assert_failed(self, code, events=None):
        result = self.convert(events)
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["errors"], [code])
        self.assertIsNone(result["output_csv"])
        self.assertIsNone(result["output_metadata"])
        if result["raw_hdf_path"]:
            self.assertEqual(Path(result["raw_hdf_path"]).read_bytes(), self.file.read_bytes())
        self.assertFalse(result["training_ready"])
        return result

    def test_causal_quotes_native_evidence_and_conservative_metadata(self):
        result = self.convert()
        data = self.quotes(result)
        self.assertEqual([q.time_msc for q in data.quotes], [BASE_NS // 1_000_000 + 2, BASE_NS // 1_000_000 + 3])
        self.assertEqual([(q.bid, q.ask) for q in data.quotes], [(Decimal("100"), Decimal("100.10"))] * 2)
        native = [json.loads(line) for line in Path(result["native_events_path"]).read_text().splitlines()]
        self.assertEqual([row["time_ns"] for row in native], [row["time"] for row in rows()])
        self.assertEqual([row["source_row"] for row in native], list(range(len(rows()))))
        self.assertTrue(all(not row["execution_label"] for row in native))
        evidence = [json.loads(line) for line in Path(result["quote_evidence_path"]).read_text().splitlines()]
        self.assertTrue(all(row["latest_event_time_ns"] < row["boundary_time_ns"] for row in evidence))
        self.assertEqual(data.metadata["wse_required_max_quote_gap_ms"], 1)
        self.assertIn("BOOTSTRAP_COMPLETION_ASSUMED", data.metadata["quality_flags"])
        self.assertFalse(data.metadata["fills_or_queue_priority_identified"])
        self.assertEqual(result["final_incomplete_buckets_excluded"], 1)
        self.assertEqual(json.loads(Path(result["manifest_path"]).read_text()), result)

    def test_boundary_event_and_future_price_never_enter_previous_quote(self):
        source = rows()[:5] + [event(2_000_000, order_id=1, price=10003),
                              event(3_000_000, order_id=1, price=10005), event(4_000_000)]
        data = self.quotes(self.convert(source))
        self.assertEqual([q.bid for q in data.quotes], [Decimal("100"), Decimal("100.03"), Decimal("100.05")])

    def test_final_incomplete_bucket_is_not_projected(self):
        result = self.convert(rows()[:6])
        self.assertEqual(result["quote_count"], 1)
        self.assertEqual(result["final_incomplete_buckets_excluded"], 1)

    def test_equal_native_clocks_and_original_indexes_survive(self):
        source = rows()[:5] + [event(1_200_000, order_id=1, price=10002, index=900),
                              event(1_200_000, order_id=2, price=10012, index=950), event(2_100_000)]
        result = self.convert(source)
        self.assertEqual(result["equal_ns_rows"], 1)
        data = self.quotes(result)
        self.assertEqual((data.quotes[0].bid, data.quotes[0].ask), (Decimal("100.02"), Decimal("100.12")))
        native = [json.loads(line) for line in Path(result["native_events_path"]).read_text().splitlines()]
        self.assertEqual([row["native_fields"].get("index") for row in native][-3:], [900, 950, None])

    def test_reset_inside_bucket_excludes_prior_and_rebuilt_book(self):
        source = rows()[:5] + [event(1_200_000, "F", order_id=0)]
        source += [event(1_300_000, "Y", order_id=1, side=1, price=9000, volume=10, order_type="2"),
                   event(1_400_000, "Y", order_id=2, side=2, price=9010, volume=10, order_type="2"),
                   event(1_500_000, "A", order_id=3, side=1, price=8999, volume=1, order_type="2"),
                   event(2_100_000), event(3_100_000)]
        data = self.quotes(self.convert(source))
        self.assertEqual(len(data.quotes), 1)
        self.assertEqual(data.quotes[0].time_msc, BASE_NS // 1_000_000 + 3)
        self.assertEqual(data.quotes[0].bid, Decimal("90"))

    def test_crossed_or_one_sided_end_does_not_reuse_old_valid_quote(self):
        for altered in (event(1_200_000, order_id=1, price=10020), event(1_200_000, "D", order_id=2)):
            with self.subTest(action=altered):
                result = self.assert_failed("WSE_NO_SUPPORTED_CAUSAL_QUOTES", rows()[:5] + [altered, event(2_100_000)])
                self.assertTrue(result["partial_outputs"])

    def test_unknown_operation_or_order_poison_state_until_reset(self):
        for altered in (event(1_200_000, "Q"), event(1_200_000, "D", order_id=999),
                        event(1_200_000, "A", order_id=1, side=1, volume=1, price=10000, order_type="2")):
            with self.subTest(altered=altered):
                self.assert_failed("WSE_NO_SUPPORTED_CAUSAL_QUOTES", rows()[:5] + [altered, event(2_100_000), event(3_100_000)])

    def test_clock_gap_invalidates_and_later_reset_can_recover(self):
        source = rows() + [event(30_000_000)]
        source += [dict(row, time=row["time"] + 40_000_000) for row in rows()]
        result = self.convert(source)
        data = self.quotes(result)
        self.assertEqual(result["event_clock_gaps"], 2)
        self.assertEqual([q.time_msc - BASE_NS // 1_000_000 for q in data.quotes], [2, 3, 4, 42, 43])

    def test_decreasing_native_clock_fails_without_sorting(self):
        self.assert_failed("WSE_NATIVE_CLOCK_REVERSED", rows() + [event(1_500_000)])

    def test_reset_is_required_at_start_of_every_selected_day(self):
        self.assert_failed("WSE_INITIAL_RESET_REQUIRED", rows()[1:])
        self.write(specification(days=["20170102", "20170103"]))
        def per_day(_p, day):
            if day == "20170102":
                return iter(rows())
            return iter([dict(row, time=row["time"] + 86_400_000_000_000) for row in rows()[1:]])
        with patch("scalper_research.wse._iter_hdf_events", side_effect=per_day):
            result = import_wse(self.file, self.spec, self.out)
        self.assertEqual(result["errors"], ["WSE_INITIAL_RESET_REQUIRED"])
        self.assertIsNone(result["output_csv"])

    def test_symbol_day_and_field_types_are_checked(self):
        for replacement, code in (({"symbol_idx": 10783}, "WSE_EVENT_SYMBOL_MISMATCH"),
                                  ({"time": BASE_NS + 86_400_000_000_000}, "WSE_EVENT_DAY_MISMATCH"),
                                  ({"time": float(BASE_NS)}, "WSE_EVENT_INTEGER_FIELDS"),
                                  ({"price": True}, "WSE_EVENT_INTEGER_FIELDS")):
            with self.subTest(replacement=replacement):
                source = rows()
                source[4] = dict(source[4], **replacement)
                self.assert_failed(code, source)

    def test_hash_mismatch_preserves_original_and_never_reads_hdf(self):
        self.write(specification(expected_sha256="0" * 64))
        with patch("scalper_research.wse._iter_hdf_events") as reader:
            result = import_wse(self.file, self.spec, self.out)
        self.assertEqual(result["errors"], ["WSE_SOURCE_SHA256_MISMATCH"])
        reader.assert_not_called()
        self.assertEqual(Path(result["raw_hdf_path"]).read_bytes(), self.file.read_bytes())

    def test_archive_has_different_inode_and_input_mutation_cannot_change_it(self):
        result = self.convert()
        archived = Path(result["raw_hdf_path"])
        self.assertNotEqual(archived.stat().st_ino, self.file.stat().st_ino)
        self.file.write_bytes(b"changed later")
        self.assertEqual(archived.read_bytes(), b"fictional-hdf-container")

    def test_exact_decimal_prices_under_low_ambient_precision(self):
        source = rows()
        source[1] = dict(source[1], price=123456789123, price_level=9)
        source[2] = dict(source[2], price=123456799123, price_level=9)
        source[3] = dict(source[3], price=123456788123, price_level=9)
        with localcontext() as context:
            context.prec, context.Emax, context.Emin = 2, 2, -2
            result = self.convert(source)
        data = self.quotes(result)
        self.assertEqual(data.quotes[0].bid, Decimal("123.456789123"))

    def test_specification_rejects_missing_contract_boolean_clock_or_wrong_symbol(self):
        for changes, code in (({"sample_period_ms": True}, "WSE_SAMPLING_CONTRACT"),
                              ({"expected_sha256": "bad"}, "WSE_EXPECTED_SHA256_REQUIRED"),
                              ({"days": ["20170103", "20170102"]}, "WSE_DAYS_CONTRACT"),
                              ({"days": ["20171302"]}, "WSE_DAYS_CONTRACT"),
                              ({"symbol_idx": 1}, "WSE_SYMBOL_CONTRACT"),
                              ({"retransmission_completion_policy": "verified"}, "WSE_BOOTSTRAP_POLICY_REQUIRED")):
            with self.subTest(changes=changes):
                self.write(specification(**changes))
                self.assert_failed(code)

    def test_optional_dependency_failure_has_archived_inputs(self):
        with patch.dict("sys.modules", {"h5py": None}):
            result = import_wse(self.file, self.spec, self.out)
        self.assertEqual(result["errors"], ["WSE_OPTIONAL_H5PY_REQUIRED"])
        self.assertTrue(Path(result["raw_hdf_path"]).exists())

    def test_output_row_limit_failure_never_publishes_partial_market_csv(self):
        with patch("scalper_research.wse.MAX_ROWS", 1):
            result = self.assert_failed("WSE_PROJECTED_QUOTE_LIMIT")
        self.assertTrue(any(path.endswith("partial_quotes.csv") for path in result["partial_outputs"]))

    def test_book_top_delete_fallback_short_sell_and_omitted_fields(self):
        book = _Book()
        for row in rows()[:4]:
            book.apply(row)
        self.assertEqual(book.snapshot(), (Decimal("100"), Decimal("100.10")))
        book.apply(event(5000, "D", order_id=1))
        self.assertEqual(book.snapshot(), (Decimal("99.99"), Decimal("100.10")))
        book.apply(event(6000, "M", order_id=2, volume=-1, side=-1, price=-1, order_type="-1"))
        self.assertEqual(book.orders[(BASE_NS, 2)][2], 20)
        book.apply(event(7000, "A", order_id=4, side=5, price=10005, volume=5, order_type="2"))
        self.assertEqual(book.snapshot()[1], Decimal("100.05"))

    def test_retransmission_is_state_upsert_and_never_trade_evidence(self):
        book = _Book()
        for row in rows()[:4]:
            book.apply(row)
        book.apply(event(5000, "Y", order_id=1, price=10002, volume=12, side=1, order_type="2"))
        self.assertIsNone(book.snapshot())
        book.apply(event(6000))
        self.assertEqual(book.snapshot(), (Decimal("100.02"), Decimal("100.10")))
        self.assertEqual(book.levels[1][Decimal("100.02")], 12)


@unittest.skipUnless(importlib.util.find_spec("h5py"), "optional wse dependency is not installed")
class WseHdfTests(unittest.TestCase):
    setUp = WseTests.setUp
    tearDown = WseTests.tearDown
    write = WseTests.write
    quotes = WseTests.quotes
    def make_hdf(self, *, invalid=None):
        import h5py
        import numpy as np
        dtype = [(name, "S1" if name == "action_type" else "S2" if name == "order_type" else "<i8") for name in FIELDS]
        if invalid == "float-clock":
            dtype[0] = ("time", "<f8")
        array = np.array([tuple(str(row[name]).encode() if name in ("action_type", "order_type") else row[name]
                                for name in FIELDS) for row in rows()], dtype=dtype)
        with h5py.File(self.file, "w") as output:
            output.create_dataset("d20170102/table", data=array, compression="gzip")
        self.spec.write_text(json.dumps(specification(self.file.read_bytes())))

    def test_actual_hdf_streaming_fixture(self):
        self.make_hdf()
        result = import_wse(self.file, self.spec, self.out)
        self.assertEqual(len(self.quotes(result).quotes), 2)

    def test_hdf_floating_native_clock_is_rejected(self):
        self.make_hdf(invalid="float-clock")
        result = import_wse(self.file, self.spec, self.out)
        self.assertEqual(result["errors"], ["WSE_HDF_FIELD_SCHEMA"])

    def test_external_hdf_link_is_rejected(self):
        import h5py
        with h5py.File(self.file, "w") as output:
            output["d20170102"] = h5py.ExternalLink("elsewhere.h5", "/d20170102")
        self.spec.write_text(json.dumps(specification(self.file.read_bytes())))
        result = import_wse(self.file, self.spec, self.out)
        self.assertEqual(result["errors"], ["WSE_DAY_GROUP_REQUIRED"])


if __name__ == "__main__":
    unittest.main()
