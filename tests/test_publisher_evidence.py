"""Synthetic offline fixtures; no original trader artifacts or network access."""
import copy
import json
import unittest
from decimal import Decimal

from trading_intelligence.common import DataError
from trading_intelligence.publisher_evidence import normalize_evidence


def image_row(**updates):
    row = {"schema_version": "1.0",
           "record_kind": "dated_transaction_row_transcribed_from_publisher_shared_broker_screenshot",
           "source_id": "fictional_image", "trader": "Fictional Trader Alpha",
           "source_url": "https://publisher.example.test/post/image01",
           "source_asset_url": "https://publisher.example.test/assets/image01.png",
           "source_asset_sha256": "a" * 64, "source_asset_path": "fixture-only/image01.png",
           "source_asset_width": 600, "source_asset_height": 100,
           "source_retrieved_at_utc": "2025-01-02T00:00:00+00:00",
           "source_sheet": None, "source_spreadsheet_row": None, "source_row": 1,
           "source_rectangle_xyxy": [0, 20, 600, 40],
           "source_column_rectangles_xyxy": {key: [i * 100, 20, (i + 1) * 100, 40]
             for i, key in enumerate(["TradeDate", "Symbol", "QTY", "Price", "Fees", "NetAmount"])},
           "physical_row_ref": "sha256:" + "a" * 64 + "#image-data-row=1&rect=0,20,600,40",
           "raw_cells_display_text": {"TradeDate": "1/2/2025", "Symbol": "FICTION_A",
                  "QTY": "-12", "Price": "10.25", "Fees": "-0.25", "NetAmount": "122.75"},
           "verified_columns": ["TradeDate", "Symbol", "QTY", "Price", "Fees", "NetAmount"],
           "verification_method": "synthetic fixture only", "date_raw": "1/2/2025",
           "date_local": "2025-01-02", "entry_clock_raw": None, "exit_clock_raw": None,
           "entry_at_utc": None, "exit_at_utc": None, "timezone": None, "instrument": "FICTION_A",
           "side": None, "transaction_action": None, "quantity": -12, "quantity_definition": "signed transaction delta",
           "transaction_price": 10.25, "entry_price": None, "exit_price": None,
           "fees_reported": -0.25, "net_cash_amount_reported": 122.75, "currency": None,
           "strategy_identifier": None, "note_presence": False, "stop": None}
    row.update(updates)
    return row


def journal_row(**updates):
    row = {"record_id": "fictional_profile_post01", "trader": "Fictional Trader Beta",
           "publisher_profile": "fictional_profile", "record_type": "publisher_reported_closed_trade_summary",
           "source_url": "https://publisher.example.test/post01", "source_sha256": "b" * 64,
           "profile_page_url": "https://publisher.example.test/profile?page=1",
           "profile_page_sha256": "c" * 64, "ticker": "FICTION_B", "direction_raw": "Short Stock",
           "entry_date": "2025-01-02", "exit_date": "2025-01-03",
           "entry_date_raw": "1/2/2025", "exit_date_raw": "1/3/2025",
           "entry_price_display": 12.5, "exit_price_display": 12.25,
           "position_size_display": 10, "pnl_display_usd_rounded": 2,
           "broker_label": "Fictional Broker", "publisher_verification_badge": True,
           "published_timestamp_raw": "Jan 04, 25 11:59 PM", "batch_period_comment_present": True,
           "market_entry_timestamp": None, "market_exit_timestamp": None, "timezone": None,
           "order_id": None, "execution_fills": None, "stop_price": None, "decision_reason": None,
           "independently_broker_authenticated": False, "aggregation_of_scaling_fills": "not established",
           "ai_training_rights": "not established"}
    row.update(updates)
    return row


def teaching_card(**updates):
    row = {"id": "fictional_card01", "trader": "Fictional Trader Gamma", "source_id": "fictional_teaching_source",
           "class": "published_rules; incomplete", "entry": "fictional teaching statement",
           "indicator": {"period": 8, "threshold": 0.125}, "risk_pct": [0.1, 0.2],
           "preferred_windows": ["10:00-10:30"], "unresolved": ["fictional ambiguity"]}
    row.update(updates)
    return row


def artifact(rows):
    return b"\n".join(json.dumps(row).encode() for row in rows)


def normalized_image(row=None):
    return normalize_evidence(artifact([row or image_row()]), kind="image_transactions", source_id="fixture_batch")[0]


def normalized_journal(row=None):
    return normalize_evidence(artifact([row or journal_row()]), kind="journal_summaries", source_id="fixture_batch")[0]


class PublisherEvidenceTests(unittest.TestCase):
    def assert_blocked(self, row):
        for field in ("training_ready", "full_history_verified", "broker_verified", "independently_broker_authenticated"):
            self.assertIs(row[field], False)

    def test_image_preserves_cash_signed_quantity_and_raw_numeric_metadata(self):
        row = normalized_image()
        self.assertEqual(row["source_id"], "fixture_batch")
        self.assertEqual(row["publisher_source_id"], "fictional_image")
        self.assertEqual(row["record_kind"], "image_transaction")
        self.assertEqual(row["raw_cells"]["QTY"], "-12")
        self.assertEqual(row["mapped_raw_fields"]["quantity"], -12)
        self.assertEqual(row["mapped_raw_fields"]["transaction_price"], Decimal("10.25"))
        self.assertEqual(row["mapped_raw_fields"]["net_cash_amount_reported"], Decimal("122.75"))
        self.assertNotIn("net_pnl", row)
        self.assertNotIn("side", row)
        self.assertEqual(row["usage_role"], "transaction_evidence_not_closed_trade")
        self.assertIn("CASH_AMOUNT_NOT_TRADE_PNL", row["quality_flags"])
        self.assertIn("SIGNED_QUANTITY_NOT_POSITION_SIDE", row["quality_flags"])
        self.assertTrue(row["temporal_quarantined"])
        self.assert_blocked(row)

    def test_receipt_changed_image_bytes_and_clock_are_not_new_business_version(self):
        original = normalized_image()
        changed = image_row(source_asset_sha256="d" * 64, source_retrieved_at_utc="2025-02-03T00:00:00Z",
                            source_asset_path="fixture-only/new-snapshot.png")
        changed["physical_row_ref"] = changed["physical_row_ref"].replace("a" * 64, "d" * 64)
        second = normalized_image(changed)
        self.assertEqual(original["row_semantic_sha256"], second["row_semantic_sha256"])
        self.assertEqual(original["source_row_identity"], second["source_row_identity"])
        self.assertNotEqual(original["provenance"], second["provenance"])

    def test_batch_namespace_is_not_an_artifact_id_or_business_revision(self):
        first = normalized_image()
        second = normalize_evidence(artifact([image_row()]), kind="image_transactions", source_id="different_batch")[0]
        self.assertNotEqual(first["source_id"], second["source_id"])
        self.assertEqual(first["publisher_source_id"], second["publisher_source_id"])
        self.assertEqual(first["row_semantic_sha256"], second["row_semantic_sha256"])

    def test_cell_change_is_a_semantic_revision(self):
        original = normalized_image()
        changed = image_row(transaction_price=10.50)
        changed["raw_cells_display_text"]["Price"] = "10.50"
        self.assertNotEqual(original["row_semantic_sha256"], normalized_image(changed)["row_semantic_sha256"])

    def test_physical_jsonl_line_not_visible_image_row_is_source_row(self):
        raw = b"\n\n" + artifact([image_row()])
        row = normalize_evidence(raw, kind="image_transactions", source_id="fixture_batch")[0]
        self.assertEqual(row["source_row"], 3)
        self.assertEqual(row["provenance"]["publisher_source_row"], 1)
        self.assertEqual(row["row_semantic_sha256"], normalized_image()["row_semantic_sha256"])

    def test_image_locator_requires_receipt_consistency_and_bounds(self):
        for changes in [{"source_rectangle_xyxy": [0, 20, 900, 40]}, {"source_row": 0},
                        {"physical_row_ref": "unrelated locator"}, {"source_asset_width": True}]:
            with self.subTest(changes=changes), self.assertRaises(DataError):
                normalized_image(image_row(**changes))

    def test_image_numeric_and_date_display_mappings_must_match(self):
        for changes in [{"quantity": 12}, {"fees_reported": 0.25}, {"date_local": "2025-02-01"}]:
            with self.subTest(changes=changes), self.assertRaises(DataError):
                normalized_image(image_row(**changes))

    def test_image_verification_columns_cannot_be_inferred(self):
        with self.assertRaisesRegex(DataError, "EVIDENCE_IMAGE_COLUMNS_NOT_VERIFIED"):
            normalized_image(image_row(verified_columns=["TradeDate", "Symbol"]))

    def test_image_cannot_promote_signed_delta_into_position_or_execution_time(self):
        for changes in [{"side": "short"}, {"transaction_action": "open"}, {"entry_at_utc": "2025-01-02T12:00:00Z"},
                        {"timezone": "UTC"}]:
            with self.subTest(changes=changes), self.assertRaisesRegex(DataError, "EVIDENCE_UNSUPPORTED_EXECUTION_OR_TIME_CLAIM"):
                normalized_image(image_row(**changes))

    def test_journal_post_identity_and_display_summary_remain_unverified(self):
        row = normalized_journal()
        self.assertEqual(row["source_row_identity"], "fictional_profile_post01")
        self.assertEqual(row["provenance"]["publisher_post_id"], "post01")
        self.assertEqual(row["raw_cells"]["entry_price_display"], Decimal("12.5"))
        self.assertEqual(row["raw_cells"]["position_size_display"], 10)
        self.assertNotIn("fill_price", row)
        self.assertNotIn("opened_at_utc", row)
        self.assertEqual(row["usage_role"], "publisher_summary_not_execution_fills")
        self.assertIn("REPORTED_OVERNIGHT_NOT_CLASSIFIED_AS_SCALPING", row["quality_flags"])
        self.assertTrue(row["temporal_quarantined"])
        self.assert_blocked(row)

    def test_publication_clock_or_changed_page_hash_is_not_execution_or_revision(self):
        first = normalized_journal()
        second = normalized_journal(journal_row(published_timestamp_raw="Jan 05, 25 1:00 AM", source_sha256="d" * 64,
                                                profile_page_sha256="e" * 64,
                                                profile_page_url="https://publisher.example.test/profile?page=2"))
        self.assertEqual(first["row_semantic_sha256"], second["row_semantic_sha256"])
        self.assertNotEqual(first["provenance"], second["provenance"])

    def test_legacy_usd_field_and_dollar_marker_do_not_authenticate_currency(self):
        row = normalized_journal(journal_row(source_currency_marker="$"))
        self.assertEqual(row["raw_cells"]["pnl_display_usd_rounded"], 2)
        self.assertEqual(row["mapped_raw_fields"]["source_currency_marker"], "$")
        self.assertIsNone(row["mapped_raw_fields"]["pnl_currency"])
        self.assertIn("PNL_CURRENCY_NOT_AUTHENTICATED", row["quality_flags"])
        self.assertIsNone(normalized_journal()["mapped_raw_fields"]["source_currency_marker"])

    def test_journal_request_time_is_unknown_without_explicit_receipt(self):
        row = normalized_journal(journal_row(published_timestamp_raw="Jan 04, 25 11:59 PM"))
        self.assertIsNone(row["provenance"]["source_request_retrieved_at_utc"])
        self.assertIsNone(row["provenance"]["batch_date"])
        self.assertEqual(row["provenance"]["published_timestamp_raw"], "Jan 04, 25 11:59 PM")

    def test_explicit_journal_request_receipts_do_not_change_semantic_record(self):
        first = normalized_journal()
        second = normalized_journal(journal_row(source_request_retrieved_at_utc="2025-01-06T01:02:03Z",
                                                batch_date="2025-01-06"))
        self.assertEqual(second["provenance"]["source_request_retrieved_at_utc"], "2025-01-06T01:02:03Z")
        self.assertEqual(second["provenance"]["batch_date"], "2025-01-06")
        self.assertEqual(first["row_semantic_sha256"], second["row_semantic_sha256"])
        for changes in [{"source_request_retrieved_at_utc": "2025-01-06T01:02:03"},
                        {"source_request_retrieved_at_utc": "2025-01-06T01:02:03+01:00"},
                        {"batch_date": "yesterday"}]:
            with self.subTest(changes=changes), self.assertRaises(DataError):
                normalized_journal(journal_row(**changes))

    def test_reversed_summary_dates_are_flagged_without_repair(self):
        row = normalized_journal(journal_row(exit_date="2025-01-01", exit_date_raw="1/1/2025"))
        self.assertEqual(row["mapped_raw_fields"]["exit_date"], "2025-01-01")
        self.assertIn("REPORTED_EXIT_DATE_BEFORE_ENTRY_DATE", row["quality_flags"])
        self.assertTrue(row["temporal_quarantined"])

    def test_journal_mandatory_absent_fill_and_clock_fields(self):
        for field in ("market_entry_timestamp", "market_exit_timestamp", "order_id", "execution_fills"):
            for value in ("2025-01-02T10:00:00Z", []):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(DataError, "EVIDENCE_UNSUPPORTED_EXECUTION_OR_TIME_CLAIM"):
                    normalized_journal(journal_row(**{field: value}))
            row = journal_row(); del row[field]
            with self.subTest(field=field, missing=True), self.assertRaises(DataError):
                normalized_journal(row)

    def test_badge_is_not_independent_broker_authentication(self):
        self.assert_blocked(normalized_journal(journal_row(publisher_verification_badge=True)))
        with self.assertRaisesRegex(DataError, "EVIDENCE_UNSUPPORTED_BROKER_AUTHENTICATION_CLAIM"):
            normalized_journal(journal_row(independently_broker_authenticated=True))

    def test_account_aggregate_cannot_enter_closed_summary_adapter(self):
        with self.assertRaisesRegex(DataError, "EVIDENCE_JOURNAL_SCHEMA_UNSUPPORTED"):
            normalized_journal(journal_row(record_type="publisher_monthly_account_aggregate"))
        with self.assertRaises(DataError):
            normalized_journal(journal_row(entry_date=None, entry_date_raw="--", entry_price_display="--"))

    def test_post_id_must_match_source_receipt_url(self):
        with self.assertRaisesRegex(DataError, "EVIDENCE_PUBLISHER_POST_ID_MISMATCH"):
            normalized_journal(journal_row(source_url="https://publisher.example.test/different-post"))

    def test_receipt_hash_and_public_url_are_syntax_checked(self):
        for changes in [{"source_sha256": "invalid"}, {"profile_page_sha256": ""},
                        {"source_url": "file:///post01"}, {"source_url": "https://secret@publisher.example.test/post01"}]:
            with self.subTest(changes=changes), self.assertRaises(DataError):
                normalized_journal(journal_row(**changes))
        with self.assertRaisesRegex(DataError, "EVIDENCE_RECEIPT_TIME_INVALID"):
            normalized_image(image_row(source_retrieved_at_utc="2025-01-02T00:00:00"))

    def test_cards_are_education_and_preserve_numeric_settings_and_unknowns(self):
        document = {"schema_version": "1.0", "training_ready": False, "cards": [teaching_card()]}
        row = normalize_evidence(json.dumps(document).encode(), kind="strategy_cards", source_id="fixture_batch")[0]
        self.assertEqual(row["record_kind"], "strategy_card")
        self.assertEqual(row["source_row_identity"], "fictional_card01")
        self.assertEqual(row["raw_cells"]["indicator"], {"period": 8, "threshold": Decimal("0.125")})
        self.assertEqual(row["raw_cells"]["unresolved"], ["fictional ambiguity"])
        self.assertEqual(row["usage_role"], "education_not_trade")
        self.assertFalse(row["temporal_quarantined"])
        self.assertIsNone(row["provenance"]["source_url"])
        self.assert_blocked(row)

    def test_card_identity_is_stable_across_order_but_settings_are_versioned(self):
        first_card, second_card = teaching_card(), teaching_card(id="fictional_card02", entry="other teaching rule")
        def normalize(cards):
            return normalize_evidence(json.dumps({"schema_version": "1.0", "training_ready": False, "cards": cards}).encode(),
                                      kind="strategy_cards", source_id="fixture_batch")
        first, second = normalize([first_card, second_card]), normalize([second_card, first_card])
        self.assertEqual(first[0]["row_semantic_sha256"], second[1]["row_semantic_sha256"])
        changed = copy.deepcopy(first_card); changed["indicator"]["period"] = 9
        self.assertNotEqual(first[0]["row_semantic_sha256"], normalize([changed])[0]["row_semantic_sha256"])

    def test_card_container_cannot_claim_training_ready(self):
        with self.assertRaisesRegex(DataError, "EVIDENCE_CARD_SCHEMA_UNSUPPORTED"):
            normalize_evidence(json.dumps({"schema_version": "1.0", "training_ready": True, "cards": [teaching_card()]}).encode(),
                               kind="strategy_cards", source_id="fixture_batch")

    def test_untrusted_input_claims_do_not_override_output_gates_or_origin(self):
        row = normalized_image(image_row(training_ready=True, full_history_verified=True, broker_verified=True,
                                         data_origin="synthetic_fixture"))
        self.assert_blocked(row)
        self.assertEqual(row["data_origin"], "publisher_reported_unverified")

    def test_strict_json_rejects_duplicate_keys_nonfinite_and_nonobjects(self):
        for raw in (b'{"trader":"A","trader":"B"}', b'{"quantity":NaN}', b'[1,2,3]'):
            with self.subTest(raw=raw), self.assertRaises(DataError):
                normalize_evidence(raw, kind="image_transactions", source_id="fixture_batch")

    def test_kind_namespace_and_empty_artifact_are_required(self):
        for raw, kind, source_id in [(b"", "image_transactions", "fixture_batch"),
                                     (artifact([image_row()]), "fills", "fixture_batch"),
                                     (artifact([image_row()]), "image_transactions", "")]:
            with self.subTest(kind=kind, source_id=source_id), self.assertRaises(DataError):
                normalize_evidence(raw, kind=kind, source_id=source_id)


if __name__ == "__main__":
    unittest.main()
