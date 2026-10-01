"""Independent WSE causality regressions on invented native events only."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scalper_research.wse import import_wse


BASE_NS = int(datetime(2017, 1, 2, 9, tzinfo=timezone.utc).timestamp()) * 1_000_000_000


def event(offset_ns, action, order_id=-1, *, side=-1, price=-1, volume=-1, order_type=-1):
    return {"time": BASE_NS + offset_ns, "priority_date": -1,
            "order_date": BASE_NS if order_id >= 0 else -1,
            "symbol_idx": 11322, "price": price, "agg_volume": -1,
            "volume": volume, "order_id": order_id, "num_orders": -1,
            "side": side, "order_type": order_type,
            "action_type": action, "price_level": 2}


def specification(digest):
    return {"schema_version": 1, "format": "wselob_orders_v1",
            "expected_sha256": digest, "symbol": "PEKAO", "symbol_idx": 11322,
            "days": ["20170102"], "sample_period_ms": 1,
            "max_event_gap_ms": 10,
            "source_clock_evidence": "Entirely invented UTC epoch-nanosecond event clock",
            "retransmission_completion_policy": "first_non_retransmission_event_assumption",
            "session_start_minute_warsaw": 0, "session_end_minute_warsaw": 1440,
            "source": {"schema_version": 1, "source_id": "fictional_native_review",
                       "symbol": "PEKAO", "price_currency": "PLN",
                       "timestamp_basis": "utc_epoch_milliseconds",
                       "timezone_evidence": "Synthetic bucket ends explicitly derived from UTC ns",
                       "data_origin": "synthetic_fixture", "usage_rights": "synthetic_only"}}


class NativeDataReview(unittest.TestCase):
    def test_native_conversion_cannot_echo_training_or_trading_claims(self):
        rows = [event(0, "F"),
                event(100, "Y", 1, side=1, price=10000, volume=10, order_type=2),
                event(200, "Y", 2, side=2, price=10100, volume=10, order_type=2),
                event(1_000_100, "A", 3, side=1, price=9900, volume=1, order_type=2),
                event(1_500_100, "M", 3, volume=2),
                event(2_000_100, "M", 3, volume=3)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "fictional.h5"
            source.write_bytes(b"fictional source bytes; no market data")
            document = specification(hashlib.sha256(source.read_bytes()).hexdigest())
            document["source"].update(model_trained=True, trading_enabled=True)
            spec = root / "fictional_spec.json"
            spec.write_text(json.dumps(document))
            with patch("scalper_research.wse._iter_hdf_events", return_value=iter(rows)):
                result = import_wse(source, spec, root / "out")
            self.assertEqual(result["status"], "completed", result["errors"])
            metadata = json.loads(Path(result["output_metadata"]).read_text())
            self.assertFalse(metadata.get("model_trained", False))
            self.assertFalse(metadata.get("trading_enabled", False))

    def test_future_gap_does_not_delete_preceding_causal_bucket_quote(self):
        # Bucket0 bootstraps and is excluded. Bucket1 has a healthy two-sided
        # book; its boundary at2ms is only0.5ms after its last message. A future
        # native gap at100ms must affect the later book, not this earlier quote.
        rows = [event(0, "F"),
                event(100, "Y", 1, side=1, price=10000, volume=10, order_type=2),
                event(200, "Y", 2, side=2, price=10100, volume=10, order_type=2),
                event(1_000_100, "A", 3, side=1, price=9900, volume=1, order_type=2),
                event(1_500_100, "M", 3, volume=2),
                event(100_000_100, "M", 3, volume=3)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "fictional.h5"
            source.write_bytes(b"fictional source bytes; HDF reader replaced by invented events")
            spec = root / "fictional_spec.json"
            spec.write_text(json.dumps(specification(hashlib.sha256(source.read_bytes()).hexdigest())))
            with patch("scalper_research.wse._iter_hdf_events", return_value=iter(rows)):
                result = import_wse(source, spec, root / "out")
            self.assertEqual(result["status"], "completed", result["errors"])
            self.assertEqual(result["quote_count"], 1)
            quote_rows = Path(result["output_csv"]).read_text().splitlines()
            self.assertEqual(quote_rows, ["time_msc,bid,ask", f"{BASE_NS // 1_000_000 + 2},100.00,101.00"])
            evidence = json.loads(Path(result["quote_evidence_path"]).read_text())
            self.assertLess(evidence["latest_event_time_ns"], evidence["boundary_time_ns"])


if __name__ == "__main__":
    unittest.main()
