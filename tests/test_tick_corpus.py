"""Offline, wholly fictional sharding and tamper checks; never vendor downloads."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scalper_research.market import load_quotes
from scalper_research.tick_corpus import shard_ticks, verify_tick_corpus
from trading_intelligence.common import DataError, json_bytes


class TickCorpusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.csv = self.root / "fictional.csv"
        self.meta = self.root / "fictional.json"
        self.out = self.root / "out"
        self.metadata = {"schema_version": 1, "source_id": "fictional_eurusd", "symbol": "EURUSD",
                         "price_currency": "USD", "timestamp_basis": "utc_epoch_milliseconds",
                         "timezone_evidence": "fixture generator defines UTC-ms",
                         "data_origin": "synthetic_fixture", "usage_rights": "synthetic_only",
                         "training_usage_rights": "synthetic_only"}
        self.meta.write_bytes(json_bytes(self.metadata))
        self.times = [1704153599998, 1704153599999, 1704153599999,
                      1704153600000, 1704153600001, 1704153600001, 1704153600002]
        self.write_csv(self.times)

    def write_csv(self, times):
        self.csv.write_text("time_msc,bid,ask\n" + "".join(
            f"{t},1.100000{i},1.100001{i}\n" for i, t in enumerate(times)), encoding="ascii")

    def run_shard(self, **kwargs):
        return shard_ticks(self.csv, self.meta, self.out, **kwargs)

    def chunk(self, result, index=0):
        directory = Path(result["dataset_directory"])
        shard = result["shards"][index]
        return directory / shard["file"], directory / shard["metadata_file"]

    def expect_failure(self, code, **kwargs):
        result = self.run_shard(**kwargs)
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["errors"], [code])
        self.assertEqual(result["shards"], [])
        self.assertFalse((Path(result["manifest_path"]).parent / "dataset").exists())
        self.assertIsNotNone(result["completed_at_utc"])
        return result

    def test_day_capacity_groups_and_exact_prices(self):
        result = self.run_shard(max_shard_rows=3)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual([s["rows"] for s in result["shards"]], [3, 3, 1])
        self.assertEqual(result["duplicate_timestamp_rows"], 2)
        self.assertEqual(result["quote_count"], 7)
        values = []
        for i, shard in enumerate(result["shards"]):
            dataset = load_quotes(*self.chunk(result, i))
            values += [q.time_msc for q in dataset.quotes]
            self.assertEqual(dataset.metadata["training_usage_rights"], "synthetic_only")
            self.assertEqual(shard["source_last_physical_row"] - shard["source_first_physical_row"] + 1, shard["rows"])
        self.assertEqual(values, self.times)
        self.assertIn("1.1000000", self.chunk(result)[0].read_text())
        checked = verify_tick_corpus(Path(result["manifest_path"]))
        self.assertEqual(checked["quote_count"], 7)
        self.assertFalse(checked["training_ready"])
        self.assertFalse(checked["raw_source_rechecked"])

    def test_archive_bytes_readonly_and_unique_run(self):
        a, b = self.run_shard(), self.run_shard()
        self.assertNotEqual(a["run_id"], b["run_id"])
        self.assertEqual(a["raw_csv_path"], b["raw_csv_path"])
        self.assertEqual(Path(a["raw_csv_path"]).read_bytes(), self.csv.read_bytes())
        self.assertEqual(Path(a["raw_csv_path"]).stat().st_mode & 0o777, 0o400)

    def test_equal_clock_group_never_split_for_row_limit(self):
        self.write_csv([1000, 1001, 1001, 1002])
        result = self.run_shard(max_shard_rows=2)
        self.assertEqual([s["rows"] for s in result["shards"]], [1, 2, 1])
        self.assertTrue(all(a["last_time_msc"] < b["first_time_msc"] for a, b in zip(result["shards"], result["shards"][1:])))

    def test_equal_clock_group_never_split_for_byte_limit(self):
        self.write_csv([1000, 1001, 1001, 1002])
        result = self.run_shard(max_shard_bytes=70)
        self.assertEqual([s["rows"] for s in result["shards"]], [1, 2, 1])
        self.assertTrue(all(s["bytes"] <= 70 for s in result["shards"]))

    def test_oversize_group_fails_before_dataset_publication(self):
        self.write_csv([1000, 1000, 1000])
        self.expect_failure("CORPUS_EQUAL_CLOCK_GROUP_TOO_LARGE", max_shard_rows=2)

    def test_byte_oversize_group_fails(self):
        self.write_csv([1000, 1000, 1000])
        self.expect_failure("CORPUS_EQUAL_CLOCK_GROUP_TOO_LARGE", max_shard_bytes=64)

    def test_decreasing_clock_fails_without_published_partial_shards(self):
        self.write_csv([1000, 1001, 1002, 999])
        self.expect_failure("MARKET_CLOCK_NOT_NONDECREASING", max_shard_rows=1)

    def test_gap_report_not_missing_data_or_continuous_history(self):
        self.write_csv([1000, 1000, 2000, 10_000])
        result = self.run_shard(gap_report_ms=1000)
        self.assertEqual(result["observed_max_gap_ms"], 8000)
        self.assertEqual(result["observed_gap_count_over_threshold"], 1)
        self.assertFalse(result["gaps_classified_as_missing_data"])
        self.assertFalse(result["calendar_coverage_verified"])
        self.assertFalse(result["multishard_training_implemented"])

    def test_bounded_gap_sample_but_exact_total(self):
        self.write_csv([1000 + i * 2000 for i in range(101)])
        result = self.run_shard(gap_report_ms=1000)
        self.assertEqual(result["observed_gap_count_over_threshold"], 100)
        self.assertEqual(len(result["observed_gap_samples"]), 50)

    def test_symbol_column_and_reordered_headers_supported(self):
        self.csv.write_text("ask,symbol,time_msc,bid\n1.2,EURUSD,1000,1.10000\n", encoding="ascii")
        result = self.run_shard()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.chunk(result)[0].read_bytes(), b"time_msc,bid,ask\n1000,1.10000,1.2\n")

    def test_wrong_symbol_fails(self):
        self.csv.write_text("time_msc,bid,ask,symbol\n1000,1,2,XAUUSD\n", encoding="ascii")
        self.expect_failure("MARKET_SYMBOL_MISMATCH")

    def test_empty_or_multiline_rows_fail(self):
        for raw in (b"time_msc,bid,ask\n", b"time_msc,bid,ask\n\n", b'time_msc,bid,ask\n"1000\n",1,2\n'):
            with self.subTest(raw=raw):
                self.csv.write_bytes(raw)
                self.assertEqual(self.run_shard()["status"], "failed")

    def test_line_and_total_archive_caps(self):
        self.csv.write_bytes(b"time_msc,bid,ask\n" + b"1" * 4097 + b"\n")
        self.expect_failure("CORPUS_LINE_TOO_LARGE")
        self.write_csv(self.times)
        with patch("scalper_research.tick_corpus.MAX_SOURCE_BYTES", 10):
            self.expect_failure("CORPUS_SOURCE_TOO_LARGE")

    def test_price_and_clock_strictness(self):
        for row in ("1000,2,1", "1000,NaN,2", "0,1,2", "1000,-1,2", "1000,1,2,extra"):
            with self.subTest(row=row):
                self.csv.write_text("time_msc,bid,ask\n" + row + "\n", encoding="ascii")
                self.assertEqual(self.run_shard()["status"], "failed")

    def hist_spec(self):
        spec = {"schema_version": 1, "format": "histdata_generic_ascii_tick_v1",
                "source_file_sha256": hashlib.sha256(self.csv.read_bytes()).hexdigest(),
                "symbol": "EURUSD", "native_timestamp_basis": "fixed_est_milliseconds",
                "native_timezone_utc_offset_minutes": -300,
                "source_clock_evidence": "fictional fixed-EST clock", "source": self.metadata}
        self.meta.write_bytes(json_bytes(spec))
        return spec

    def test_histdata_clock_native_volume_archive_and_row_locators(self):
        self.csv.write_bytes(b"20240701 185959999,1.10000,1.20000,123\n20240701 190000000,1.10001,1.20001,0\n20240701 190000000,1.10002,1.20002,0\n")
        self.hist_spec()
        result = self.run_shard(source_format="histdata_generic_ascii_tick_v1")
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual([s["rows"] for s in result["shards"]], [1, 2])
        self.assertEqual(result["first_time_utc"], "2024-07-01T23:59:59.999Z")
        self.assertEqual(result["last_time_utc"], "2024-07-02T00:00:00.000Z")
        self.assertEqual(result["shards"][1]["source_first_physical_row"], 2)
        _, mp = self.chunk(result, 1)
        meta = json.loads(mp.read_text())
        self.assertEqual(meta["derived_csv_source_row_rule"], meta["corpus_source_row_rule"])
        self.assertFalse(meta["orderflow_feature_present"])
        self.assertIn(b",123\n", Path(result["raw_csv_path"]).read_bytes())
        self.assertEqual(verify_tick_corpus(Path(result["manifest_path"]))["quote_count"], 3)

    def test_histdata_hash_and_clock_must_be_explicit(self):
        self.csv.write_bytes(b"20240701 120000000,1,2,0\n")
        spec = self.hist_spec()
        spec["source_file_sha256"] = "0" * 64
        self.meta.write_bytes(json_bytes(spec))
        self.expect_failure("HISTDATA_SOURCE_HASH_MISMATCH", source_format="histdata_generic_ascii_tick_v1")
        spec = self.hist_spec()
        spec["native_timezone_utc_offset_minutes"] = -240
        self.meta.write_bytes(json_bytes(spec))
        self.expect_failure("HISTDATA_FIXED_EST_REQUIRED", source_format="histdata_generic_ascii_tick_v1")

    def test_invalid_metadata_and_encoding_get_failure_receipt(self):
        self.metadata["training_ready"] = True
        self.meta.write_bytes(json_bytes(self.metadata))
        self.expect_failure("MARKET_UNSUPPORTED_VERIFICATION_CLAIM")
        del self.metadata["training_ready"]
        self.metadata["rights_evidence"] = "\ud800"
        self.meta.write_text(json.dumps(self.metadata), encoding="ascii")
        self.expect_failure("CORPUS_METADATA_ENCODING")

    def test_interruption_gets_finished_receipt(self):
        with patch("scalper_research.tick_corpus._rows", side_effect=KeyboardInterrupt):
            self.expect_failure("INTERRUPTED")

    def test_archive_tamper_rejected_before_publication(self):
        from scalper_research.tick_corpus import _rows
        def mutating(path, metadata, **kwargs):
            yield from _rows(path, metadata, **kwargs)
            path.chmod(0o600)
            with path.open("ab") as stream:
                stream.write(b"\n")
        with patch("scalper_research.tick_corpus._rows", side_effect=mutating):
            self.expect_failure("CORPUS_ARCHIVE_CHANGED")

    def test_changed_shard_and_metadata_hash_rejected(self):
        for which in (0, 1):
            with self.subTest(which=which):
                result = self.run_shard()
                path = self.chunk(result)[which]
                with path.open("ab") as stream:
                    stream.write(b" " if which else b"1000,1,2\n")
                with self.assertRaises(DataError):
                    verify_tick_corpus(Path(result["manifest_path"]))

    def test_manifest_path_traversal_and_totals_rejected(self):
        result = self.run_shard()
        mp = Path(result["manifest_path"])
        for changes in (lambda m: m["shards"][0].update(file="../other.csv"),
                        lambda m: m.update(quote_count=999),
                        lambda m: m["shards"][0].update(source_first_physical_row=1)):
            modified = json.loads(json_bytes(result))
            changes(modified)
            mp.write_bytes(json_bytes(modified))
            with self.assertRaises(DataError):
                verify_tick_corpus(mp)

    def test_shard_symlink_rejected(self):
        result = self.run_shard()
        path = self.chunk(result)[0]
        other = self.root / "copy.csv"
        other.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(other)
        with self.assertRaisesRegex(DataError, "CORPUS_UNSAFE_PATH"):
            verify_tick_corpus(Path(result["manifest_path"]))

    def test_policy_types_and_limits(self):
        for policy in ({"max_shard_rows": True}, {"max_shard_rows": 500001},
                       {"max_shard_bytes": 63}, {"gap_report_ms": 0}, {"source_format": "unknown"}):
            with self.subTest(policy=policy), self.assertRaisesRegex(DataError, "CORPUS_POLICY_INVALID"):
                self.run_shard(**policy)

    def test_cli_shard_then_verify(self):
        command = [sys.executable, "-m", "scalper_research", "shard-ticks", str(self.csv),
                   "--evidence", str(self.meta), "--source-format", "utc_bidask_csv_v1",
                   "--out", str(self.out), "--max-shard-rows", "3"]
        proc = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        proc = subprocess.run([sys.executable, "-m", "scalper_research", "verify-tick-corpus", result["manifest_path"]], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["integrity_verified_against_local_unsigned_manifest"])

    def test_file_larger_than_old_byte_and_row_limits_streams_losslessly(self):
        # 510,001 fictional quotes, >32 MiB. Neither source nor expected rows
        # are kept in RAM. This is a size/behavior test, not a market benchmark.
        count, base = 510_001, 1704067200000
        with self.csv.open("wb") as stream:
            stream.write(b"time_msc,bid,ask\n")
            for index in range(count):
                stream.write(f"{base + index},1.100000000000000000000000,1.200000000000000000000000\n".encode("ascii"))
        self.assertGreater(self.csv.stat().st_size, 32 * 1024 * 1024)
        result = self.run_shard()
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["quote_count"], count)
        self.assertGreater(result["shard_count"], 1)
        self.assertTrue(all(s["rows"] <= 500_000 and s["bytes"] <= 32 * 1024 * 1024 for s in result["shards"]))
        self.assertEqual(verify_tick_corpus(Path(result["manifest_path"]))["quote_count"], count)

    def test_positive_training_claims_do_not_leak_into_shards(self):
        self.metadata.update(model_trained=True, real_market_model_trained=True,
                             expert_trade_history=True, forward_verified=True)
        self.meta.write_bytes(json_bytes(self.metadata))
        result = self.run_shard()
        _, mp = self.chunk(result)
        metadata = json.loads(mp.read_text())
        for field in ("model_trained", "real_market_model_trained", "expert_trade_history", "forward_verified"):
            self.assertIs(metadata[field], False)

    def test_manifest_does_not_promote_implemented_multishard_training(self):
        result = self.run_shard()
        mp = Path(result["manifest_path"])
        result["multishard_training_implemented"] = True
        mp.write_bytes(json_bytes(result))
        with self.assertRaisesRegex(DataError, "CORPUS_MANIFEST_INVALID"):
            verify_tick_corpus(mp)

    def test_inventory_integer_types_are_not_numeric_equivalence(self):
        result = self.run_shard()
        mp = Path(result["manifest_path"])
        for edit in (lambda m: m.update(quote_count=7.0),
                     lambda m: m["shards"][0].update(rows=3.0)):
            modified = json.loads(json_bytes(result))
            edit(modified)
            mp.write_text(json.dumps(modified), encoding="utf-8")
            with self.subTest(edit=edit), self.assertRaises(DataError):
                verify_tick_corpus(mp)

    def test_strategy_audit_keeps_teaching_conflicts_and_identity_unverified(self):
        from scalper_research.strategy_requirements import strategy_requirements
        audit = strategy_requirements()
        self.assertFalse(audit["training_ready"])
        self.assertFalse(audit["expert_trader_imitation_verified"])
        fabio, siva = audit["traders"]
        self.assertIn("tradezella.com", fabio["source"])
        self.assertFalse(siva["user_spelling_verified_alias"])
        self.assertFalse(siva["original_pdf_visual_verification_completed"])
        self.assertTrue(siva["unresolved_source_conflicts"])
        self.assertTrue(all(not trader["complete_fill_history_verified"] for trader in audit["traders"]))


if __name__ == "__main__":
    unittest.main()
