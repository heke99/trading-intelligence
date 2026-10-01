"""Durable paper state checks use only invented prices and local files."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from trading_intelligence.common import DataError, json_bytes, sha256
from scalper_research.paper import paper_status, start_paper, step_paper, stop_paper


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.csv = self.root / "invented.csv"
        self.metadata = self.root / "metadata.json"
        self.config = self.root / "config.json"
        self.out = self.root / "paper"
        self.csv.write_bytes(b"time_msc,bid,ask\n")
        self.metadata_doc = {
            "schema_version": 1, "source_id": "fictional_paper_fixture", "symbol": "SYNTHETIC",
            "timestamp_basis": "utc_epoch_milliseconds", "timezone_evidence": "fictional UTC generator",
            "data_origin": "synthetic_fixture", "price_currency": "USD", "usage_rights": "synthetic_only",
        }
        self.config_doc = {
            "schema_version": 1, "basis": "independent_rule_hypothesis",
            "strategy": {"lookback_quotes": 2, "breakout_buffer": "0", "stop_distance": "1",
                         "target_distance": "2", "max_hold_ms": 1000,
                         "session_start_minute_utc": 0, "session_end_minute_utc": 1440,
                         "cooldown_ms": 0},
            "execution": {"symbol": "SYNTHETIC", "quantity": "1", "contract_multiplier": "1",
                          "price_currency": "USD", "commission_per_unit_per_side": "0",
                          "slippage_price": "0", "latency_ms": 1, "max_quote_gap_ms": 1000,
                          "max_entry_spread": "1", "max_loss_currency": "100", "max_trades": 5},
            "evaluation": {"development_end_msc": 100000, "validation_end_msc": 200000},
        }
        self.metadata.write_bytes(json_bytes(self.metadata_doc))
        self.config.write_bytes(json_bytes(self.config_doc))

    def start(self):
        return start_paper(self.csv, self.metadata, self.config, self.out)

    def append(self, rows: str):
        with self.csv.open("ab") as source:
            source.write(rows.encode())

    def signal_prefix(self):
        self.append("1000,100,100.1\n1001,100.1,100.2\n1002,100.5,100.6\n")

    def model(self, *, selected=False):
        from scalper_research.learning import fit
        self.config_doc["evaluation"] = {"development_end_msc": 900, "validation_end_msc": 1000}
        self.config.write_bytes(json_bytes(self.config_doc))
        features = [[1.0, 0.1, 0.2, 0.3, 0.1, 0.1]] * 10 + [[-1.0, 0.1, 0.2, 0.3, 0.1, 0.1]] * 10
        model = fit(features, [1] * 10 + [0] * 10, origin="synthetic_fixture", provenance={
            "config_sha256": sha256(self.config.read_bytes()), "training_partition": "development_only",
            "development_end_msc": 900, "validation_end_msc": 1000,
        })
        if selected:
            receipt = {"config_sha256": sha256(self.config.read_bytes()),
                       "model_sha256": model["model_sha256"],
                       "selected": {"threshold": 1.0, "eligible": True}}
            receipt_raw = json_bytes(receipt)
            (self.root / "selection.json").write_bytes(receipt_raw)
            model["provenance"]["filter_selection"] = {
                "selected_threshold": "1.0", "selection_partition": "validation",
                "validation_selection_sha256": sha256(receipt_raw),
                "development_model_sha256": model["model_sha256"],
            }
            model["model_sha256"] = sha256(json_bytes({key: value for key, value in model.items() if key != "model_sha256"}))
        path = self.root / "model.json"
        path.write_bytes(json_bytes(model))
        return path, model

    def test_header_only_start_and_idempotent_step_keep_false_flags(self):
        started = self.start()
        self.assertEqual(started["status"], "waiting_for_quotes")
        self.assertEqual(started["report"]["quote_count"], 0)
        stepped = step_paper(self.out)
        self.assertEqual(stepped["new_event_count"], 0)
        self.assertEqual(stepped["newly_accepted_quotes"], 0)
        self.assertEqual(stepped["report"], started["report"])
        for flag in ("training_ready", "model_trained", "trading_enabled", "broker_connected", "forward_verified"):
            self.assertFalse(stepped[flag])
        self.assertEqual(stepped["report"]["state_policy"],
                         "recompute_full_prefix_with_one_session_risk_budget")

    def test_historical_start_and_appends_are_labeled_without_forward_claim(self):
        self.signal_prefix()
        start = self.start()
        self.assertEqual(start["processing_mode"], "historical_file_reprocessing")
        self.assertEqual(start["initial_history_quote_count"], 3)
        self.append("1003,100.6,100.7\n")
        step = step_paper(self.out)
        self.assertEqual(step["processing_mode"], "appended_quote_simulation")
        self.assertEqual(step["initial_history_quote_count"], 3)
        self.assertFalse(step["forward_verified"])
        self.assertEqual(step["report"]["entered_trade_count"], 1)

    def test_restart_and_incremental_batches_match_complete_prefix(self):
        self.start()
        self.signal_prefix()
        prefix = step_paper(self.out)
        self.assertEqual(prefix["report"]["pending_decision"]["kind"], "entry")
        self.assertEqual(paper_status(self.out)["report"], prefix["report"])
        self.append("1003,100.6,100.7\n1004,103,103.1\n")
        middle = step_paper(self.out)
        self.assertEqual(middle["report"]["pending_decision"]["kind"], "exit")
        self.append("1005,103.2,103.3\n")
        final = step_paper(self.out)
        one_batch = start_paper(self.csv, self.metadata, self.config, self.root / "other")
        self.assertEqual(final["report"], one_batch["report"])
        self.assertEqual(step_paper(self.out)["new_event_count"], 0)
        self.assertEqual(final["report"]["closed_trade_count"], 1)

    def test_incomplete_line_is_deferred_until_completed(self):
        self.start()
        self.append("1000,100,100.1\n1001,100.1,")
        partial = step_paper(self.out)
        self.assertEqual(partial["accepted_quote_count"], 1)
        self.assertEqual(partial["pending_incomplete_bytes"], len("1001,100.1,"))
        self.append("100.2\n")
        complete = step_paper(self.out)
        self.assertEqual(complete["accepted_quote_count"], 2)
        self.assertEqual(complete["pending_incomplete_bytes"], 0)

    def test_prefix_rewrite_and_truncation_fail_without_changing_report(self):
        self.signal_prefix()
        original = self.start()
        raw = self.csv.read_bytes()
        for corrupt in (raw.replace(b"1000,100,", b"1000,101,"), raw[:-1], b"time_msc,bid,ask\n"):
            self.csv.write_bytes(corrupt)
            with self.assertRaisesRegex(DataError, "PAPER_SOURCE_PREFIX_CHANGED_OR_TRUNCATED"):
                step_paper(self.out)
            self.assertEqual(paper_status(self.out)["report"], original["report"])
        self.csv.write_bytes(raw)
        self.assertEqual(step_paper(self.out)["new_event_count"], 0)

    def test_changed_config_or_metadata_are_rejected_without_rebinding(self):
        initial = self.start()
        for path, document, kind in ((self.config, self.config_doc, "config"),
                                     (self.metadata, self.metadata_doc, "metadata")):
            raw = path.read_bytes()
            path.write_bytes(json_bytes({**document, "extra": "mutated"}))
            with self.assertRaisesRegex(DataError, "PAPER_BOUND_INPUT_CHANGED:" + kind):
                step_paper(self.out)
            self.assertEqual(paper_status(self.out)["report"], initial["report"])
            path.write_bytes(raw)

    def test_kill_before_pending_entry_prevents_fill_and_is_sticky(self):
        self.signal_prefix()
        started = self.start()
        self.assertEqual(started["report"]["pending_decision"]["kind"], "entry")
        killed = stop_paper(self.out)
        self.assertEqual(killed["entry_halt_from_time_msc"], 1003)
        self.assertEqual(killed["status"], "stop_requested_waiting_for_quotes")
        self.assertEqual(killed["report"], started["report"])
        self.assertEqual(stop_paper(self.out)["stop_requested_at_utc"], killed["stop_requested_at_utc"])
        self.append("1003,100.6,100.7\n1004,103,103.1\n")
        stepped = step_paper(self.out)
        self.assertEqual(stepped["report"]["entered_trade_count"], 0)
        self.assertEqual(stepped["status"], "stopped_flat")
        self.assertTrue(stepped["report"]["entry_halted"])

    def test_kill_on_empty_session_never_starts_new_position(self):
        self.start()
        self.assertEqual(stop_paper(self.out)["entry_halt_from_time_msc"], 0)
        self.signal_prefix()
        self.append("1003,100.6,100.7\n")
        stepped = step_paper(self.out)
        self.assertEqual(stepped["report"]["entered_trade_count"], 0)
        self.assertEqual(stepped["status"], "stopped_flat")

    def test_kill_requests_delayed_exit_and_preserves_existing_exit_deadline(self):
        self.signal_prefix()
        self.append("1003,100.6,100.7\n1004,103,103.1\n")
        prior = self.start()
        pending = prior["report"]["pending_decision"]
        self.assertEqual(pending["eligible_time_msc"], 1005)
        killed = stop_paper(self.out)
        self.assertEqual(killed["report"]["closed_trade_count"], 0)
        self.append("1005,103.2,103.3\n")
        later = step_paper(self.out)
        trade = later["report"]["closed_trades"][0]
        self.assertEqual(trade["exit_eligible_time_msc"], 1005)
        self.assertEqual(trade["exit_reason"], "target")
        self.assertEqual(later["status"], "stopped_flat")

    def test_kill_with_open_position_waits_for_trigger_then_later_fill(self):
        self.signal_prefix()
        self.append("1003,100.6,100.7\n")
        prior = self.start()
        killed = stop_paper(self.out)
        self.assertEqual(killed["report"], prior["report"])
        self.append("1004,100.6,100.7\n")
        trigger = step_paper(self.out)
        self.assertEqual(trigger["report"]["closed_trade_count"], 0)
        self.assertEqual(trigger["report"]["pending_decision"]["eligible_time_msc"], 1005)
        self.append("1005,100.5,100.6\n")
        filled = step_paper(self.out)
        self.assertEqual(filled["report"]["closed_trade_count"], 1)
        self.assertEqual(filled["status"], "stopped_flat")

    def test_trade_limit_and_loss_budget_do_not_reset_with_new_batches(self):
        self.config_doc["execution"]["max_trades"] = 1
        self.config.write_bytes(json_bytes(self.config_doc))
        self.start()
        self.signal_prefix()
        step_paper(self.out)
        self.append("1003,100.6,100.7\n1004,103,103.1\n1005,103.2,103.3\n")
        first = step_paper(self.out)
        self.assertEqual(first["report"]["entered_trade_count"], 1)
        self.append("1006,104,104.1\n1007,105,105.1\n1008,106,106.1\n")
        later = step_paper(self.out)
        self.assertEqual(later["report"]["entered_trade_count"], 1)
        self.assertTrue(later["report"]["trade_limit_reached"])

    def test_loss_halt_is_preserved_after_restart_and_later_recovery(self):
        self.config_doc["execution"]["max_loss_currency"] = "0.15"
        self.config.write_bytes(json_bytes(self.config_doc))
        self.signal_prefix()
        self.append("1003,100.6,100.7\n")
        self.start()
        self.append("1004,100.4,100.5\n1005,100.3,100.4\n")
        halted = step_paper(self.out)
        self.assertTrue(halted["report"]["risk_halted"])
        self.assertEqual(halted["status"], "halted_flat")
        self.assertEqual(halted["report"]["entered_trade_count"], 1)
        self.assertEqual(paper_status(self.out)["report"], halted["report"])
        self.append("1006,103,103.1\n1007,104,104.1\n1008,105,105.1\n")
        recovered_quotes = step_paper(self.out)
        self.assertTrue(recovered_quotes["report"]["risk_halted"])
        self.assertEqual(recovered_quotes["report"]["entered_trade_count"], 1)

    def test_archived_config_and_committed_prefix_hash_corruption_are_detected(self):
        started = self.start()
        archive = self.out / started["config_archive_path"]
        original = archive.read_bytes()
        archive.write_bytes(b"{}")
        with self.assertRaisesRegex(DataError, "PAPER_BOUND_ARCHIVE_INVALID:config"):
            step_paper(self.out)
        archive.write_bytes(original)
        connection = sqlite3.connect(self.out / "paper.sqlite3")
        connection.execute("UPDATE paper_session SET accepted_csv=? WHERE singleton=1", (b"modified",))
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(DataError, "PAPER_STATE_HASH_MISMATCH"):
            paper_status(self.out)

    def test_last_raw_csv_archive_corruption_blocks_an_unchanged_step(self):
        started = self.start()
        archived = self.out / started["observed_csv_archive_path"]
        archived.write_bytes(b"altered immutable evidence")
        with self.assertRaisesRegex(DataError, "PAPER_BOUND_ARCHIVE_INVALID:csv"):
            step_paper(self.out)

    def test_malformed_database_returns_a_stable_error(self):
        self.start()
        (self.out / "paper.sqlite3").write_bytes(b"not a SQLite database")
        with self.assertRaisesRegex(DataError, "PAPER_DATABASE_UNAVAILABLE"):
            paper_status(self.out)

    def test_transaction_failure_does_not_advance_committed_prefix(self):
        started = self.start()
        self.signal_prefix()
        with patch("scalper_research.paper._write_state", side_effect=OSError("fictional disk failure")):
            with self.assertRaises(OSError):
                step_paper(self.out)
        after = paper_status(self.out)
        self.assertEqual(after["accepted_prefix_sha256"], started["accepted_prefix_sha256"])
        self.assertEqual(after["report"], started["report"])
        self.assertEqual(step_paper(self.out)["accepted_quote_count"], 3)

    def test_concurrent_writer_is_rejected(self):
        self.start()
        connection = sqlite3.connect(self.out / "paper.sqlite3", timeout=0, isolation_level=None)
        self.addCleanup(connection.close)
        connection.execute("BEGIN IMMEDIATE")
        with self.assertRaisesRegex(DataError, "PAPER_SESSION_BUSY"):
            step_paper(self.out)
        connection.rollback()
        self.assertEqual(step_paper(self.out)["new_event_count"], 0)

    def test_duplicate_clocks_bad_prices_and_unasserted_rights_fail_atomically(self):
        self.start()
        for invalid in ("1000,100,100.1\n1000,100,100.1\n", "1000,100,99\n"):
            self.csv.write_text("time_msc,bid,ask\n" + invalid)
            with self.assertRaises(DataError):
                step_paper(self.out)
            self.assertEqual(paper_status(self.out)["accepted_quote_count"], 0)
        self.csv.write_text("time_msc,bid,ask\n")
        self.metadata_doc["usage_rights"] = "not_verified"
        self.metadata.write_bytes(json_bytes(self.metadata_doc))
        with self.assertRaisesRegex(DataError, "PAPER_USAGE_RIGHTS_NOT_ASSERTED"):
            start_paper(self.csv, self.metadata, self.config, self.root / "no_rights")

    def test_second_start_cannot_replace_durable_session(self):
        first = self.start()
        with self.assertRaisesRegex(DataError, "PAPER_SESSION_ALREADY_EXISTS"):
            self.start()
        self.assertEqual(paper_status(self.out)["session_id"], first["session_id"])

    def test_frozen_model_filter_and_manual_threshold_are_labeled_honestly(self):
        model_path, _ = self.model()
        self.signal_prefix()
        started = start_paper(self.csv, self.metadata, self.config, self.out,
                              model_path=model_path, threshold=1.0)
        self.assertTrue(started["model_used"])
        self.assertEqual(started["model_fitted_on"], "synthetic_fixture")
        self.assertFalse(started["threshold_selection_verified"])
        self.assertFalse(started["report"]["training_performed_in_session"])
        self.assertEqual(started["report"]["pending_decision"], None)
        self.assertTrue(started["report"]["filter_decisions"])
        self.assertFalse(started["report"]["filter_decisions"][0]["accepted"])
        self.assertIn("SYNTHETIC_MODEL_NOT_MARKET_EVIDENCE", started["blockers"])
        self.append("1003,100.6,100.7\n")
        stepped = step_paper(self.out)
        self.assertEqual(stepped["report"]["entered_trade_count"], 0)
        self.assertEqual(stepped["model_sha256"], started["model_sha256"])

    def test_saved_validation_selection_is_hashed_and_frozen(self):
        model_path, _ = self.model(selected=True)
        self.signal_prefix()
        started = start_paper(self.csv, self.metadata, self.config, self.out,
                              model_path=model_path, threshold=1.0)
        self.assertTrue(started["threshold_selection_verified"])
        receipt_path = self.root / "selection.json"
        receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
        with self.assertRaisesRegex(DataError, "PAPER_BOUND_INPUT_CHANGED:selection"):
            step_paper(self.out)
        self.assertEqual(paper_status(self.out)["report"], started["report"])

    def test_model_bytes_are_immutable_and_cannot_be_replaced_after_restart(self):
        model_path, _ = self.model()
        started = start_paper(self.csv, self.metadata, self.config, self.out,
                              model_path=model_path, threshold=0.0)
        model_path.write_bytes(model_path.read_bytes() + b" ")
        with self.assertRaisesRegex(DataError, "PAPER_BOUND_INPUT_CHANGED:model"):
            step_paper(self.out)
        self.assertEqual(paper_status(self.out)["report"], started["report"])

    def test_future_fitted_model_and_wrong_configuration_are_rejected(self):
        model_path, model = self.model()
        self.signal_prefix()
        model["provenance"]["development_end_msc"] = 1001
        model["provenance"]["validation_end_msc"] = 1005
        self.config_doc["evaluation"] = {"development_end_msc": 1001, "validation_end_msc": 1005}
        self.config.write_bytes(json_bytes(self.config_doc))
        model["provenance"]["config_sha256"] = sha256(self.config.read_bytes())
        model["model_sha256"] = sha256(json_bytes({key: value for key, value in model.items() if key != "model_sha256"}))
        model_path.write_bytes(json_bytes(model))
        with self.assertRaisesRegex(DataError, "PAPER_QUOTES_PRECEDE_MODEL_FIT_OR_SELECTION"):
            start_paper(self.csv, self.metadata, self.config, self.out, model_path=model_path, threshold=0.0)
        model["provenance"]["config_sha256"] = "0" * 64
        model["model_sha256"] = sha256(json_bytes({key: value for key, value in model.items() if key != "model_sha256"}))
        model_path.write_bytes(json_bytes(model))
        with self.assertRaisesRegex(DataError, "PAPER_MODEL_CONFIG_MISMATCH"):
            start_paper(self.csv, self.metadata, self.config, self.out, model_path=model_path, threshold=0.0)

    def test_model_cutoffs_must_match_the_hashed_config(self):
        model_path, model = self.model()
        model["provenance"]["development_end_msc"] = 800
        model["model_sha256"] = sha256(json_bytes({key: value for key, value in model.items() if key != "model_sha256"}))
        model_path.write_bytes(json_bytes(model))
        with self.assertRaisesRegex(DataError, "PAPER_MODEL_EVALUATION_CUTOFF_MISMATCH"):
            start_paper(self.csv, self.metadata, self.config, self.out, model_path=model_path, threshold=0.0)

    def test_invalid_or_missing_threshold_and_selected_threshold_substitution_are_rejected(self):
        model_path, _ = self.model()
        for threshold in (None, True, -0.1, 1.1, float("nan")):
            with self.subTest(threshold=threshold), self.assertRaisesRegex(DataError, "PAPER_MODEL_THRESHOLD_REQUIRED"):
                start_paper(self.csv, self.metadata, self.config, self.out, model_path=model_path, threshold=threshold)
        with self.assertRaisesRegex(DataError, "PAPER_THRESHOLD_REQUIRES_MODEL"):
            start_paper(self.csv, self.metadata, self.config, self.out, threshold=0.5)
        model_path, _ = self.model(selected=True)
        with self.assertRaisesRegex(DataError, "PAPER_MODEL_THRESHOLD_SELECTION_MISMATCH"):
            start_paper(self.csv, self.metadata, self.config, self.out, model_path=model_path, threshold=0.5)


if __name__ == "__main__":
    unittest.main()
