"""Offline, synthetic OOXML fixtures only; no trader exports or network."""
import copy
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from trading_intelligence.common import DataError
from trading_intelligence.trader_xlsx import (
    _DAY, _SWING, _TIM_HEADERS, _TIM_MAPS, _TOM_MONTHS,
    mark_ambiguous_entry_links, normalize_workbook, read_workbook,
)

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"


def source(ident="hougaard_2021_08"):
    if ident in _TIM_MAPS:
        return {"id": ident, "trader": "Tim Grittani", "sheet_name": "Sheet1",
                "columns": dict(_TIM_MAPS[ident]), "synthetic": True}
    month, name = _TOM_MONTHS[ident]
    return {"id": ident, "trader": "Tom Hougaard", "month": month,
            "sheet_name": name + " Day", "columns": dict(_DAY), "swing_columns": dict(_SWING),
            "synthetic": True}


def day_row(**changes):
    row = {"B": "synthetic channel", "D": "SYNTHETIC", "E": "44411", "F": "0.375",
           "H": "Long", "I": "100.00", "J": "90", "L": "1.5", "N": "https://example.invalid/entry",
           "P": "breakout strategy", "T": "105", "U": "0.5", "Z": "5", "AD": "44411"}
    row.update(changes)
    return row


def tim_rows(ident, **fields):
    mapping = _TIM_MAPS[ident]
    defaults = {"transaction_date": "43952", "transaction_type": "Sold Short", "symbol": "SYNTHETIC",
                "signed_quantity": "-10", "cash_amount": "999", "price": "100", "commission": "-1",
                "description": "synthetic", "net_cash_amount": "999", "fees": "-1",
                "entry_type_description": "Sell", "total_cash_amount": "999"}
    defaults.update(fields)
    return {1: dict(_TIM_HEADERS[ident]), 2: {column: defaults[field] for field, column in mapping.items()}}


def write_xlsx(path, sheets, *, date1904=False, compression=ZIP_STORED,
               formulas=None, types=None, styles=False, extra=None, relationship_target=None):
    """Minimal stdlib OOXML; all strings are explicit synthetic test data."""
    formulas, types = formulas or {}, types or {}
    workbook = ET.Element(f"{{{M}}}workbook")
    ET.SubElement(workbook, f"{{{M}}}workbookPr", date1904="1" if date1904 else "0")
    sheet_list = ET.SubElement(workbook, f"{{{M}}}sheets")
    relationships = ET.Element(f"{{{P}}}Relationships")
    members = {}
    for index, (name, rows) in enumerate(sheets.items(), 1):
        ET.SubElement(sheet_list, f"{{{M}}}sheet", {"name": name, "sheetId": str(index), f"{{{R}}}id": f"rId{index}"})
        ET.SubElement(relationships, f"{{{P}}}Relationship", {
            "Id": f"rId{index}", "Type": R + "/worksheet",
            "Target": relationship_target or f"worksheets/sheet{index}.xml"})
        root = ET.Element(f"{{{M}}}worksheet")
        data = ET.SubElement(root, f"{{{M}}}sheetData")
        for row_number, cells in rows.items():
            row = ET.SubElement(data, f"{{{M}}}row", r=str(row_number))
            for column, value in cells.items():
                ref = f"{column}{row_number}"
                kind = types.get((name, ref), "inlineStr")
                cell = ET.SubElement(row, f"{{{M}}}c", r=ref, t=kind)
                if (name, ref) in formulas:
                    text, attrs = formulas[(name, ref)]
                    ET.SubElement(cell, f"{{{M}}}f", attrs).text = text
                if kind == "inlineStr":
                    ET.SubElement(ET.SubElement(cell, f"{{{M}}}is"), f"{{{M}}}t").text = value
                elif value is not None:
                    ET.SubElement(cell, f"{{{M}}}v").text = value
        members[f"xl/worksheets/sheet{index}.xml"] = ET.tostring(root)
    members["xl/workbook.xml"] = ET.tostring(workbook)
    members["xl/_rels/workbook.xml.rels"] = ET.tostring(relationships)
    if styles:
        members["xl/styles.xml"] = f'<styleSheet xmlns="{M}"><cellXfs count="1"><xf numFmtId="0"/></cellXfs></styleSheet>'.encode()
    members.update(extra or {})
    with ZipFile(path, "w", compression=compression) as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)


class TraderXlsxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "synthetic.xlsx"

    def tearDown(self):
        self.tmp.cleanup()

    def normalize_day(self, row=None, **kwargs):
        write_xlsx(self.path, {"Aug 2021 Day": {9: row or day_row()}}, **kwargs)
        return normalize_workbook(self.path, source())

    def test_exact_eight_catalog_mappings_supported(self):
        for ident in (*_TIM_MAPS, *_TOM_MONTHS):
            with self.subTest(source_id=ident):
                spec = source(ident)
                rows = tim_rows(ident) if ident in _TIM_MAPS else {9: day_row()}
                write_xlsx(self.path, {spec["sheet_name"]: rows})
                result = normalize_workbook(self.path, spec)
                self.assertEqual(result["source_meta"]["row_count"], 1)
                observation = result["observations"][0]
                for field, column in spec["columns"].items():
                    self.assertEqual(observation["mapped_raw_fields"][field], rows[observation["source_row"]].get(column, ""))

    def test_publisher_row_is_not_broker_trade_and_utc_stays_unknown(self):
        observation = self.normalize_day()["observations"][0]
        self.assertFalse(observation["training_ready"])
        self.assertFalse(observation["full_history_verified"])
        self.assertFalse(observation["broker_fill_verified"])
        self.assertEqual(observation["data_origin"], "synthetic_fixture")
        self.assertEqual(observation["source_row"], 9)
        self.assertEqual(observation["entry_clock_local"], "09:00:00")
        for field in ("entry_at_utc", "exit_at_utc", "transaction_at_utc", "timezone"):
            self.assertIsNone(observation[field])
        self.assertIsNone(observation["quantity"])
        self.assertEqual(observation["relative_stake"], "1.5")
        self.assertIn("RELATIVE_STAKE_NOT_CONTRACT_QUANTITY", observation["quality_flags"])
        self.assertIn("SOURCE_ROW_LOCATOR_NOT_STABLE_TRADE_ID", observation["quality_flags"])

    def test_negative_reported_duration_retained_and_temporally_quarantined(self):
        observation = self.normalize_day(day_row(U="0.25"))["observations"][0]
        self.assertEqual(observation["reported_duration_minutes"], "-180.000")
        self.assertTrue(observation["temporal_quarantined"])
        self.assertIn("NEGATIVE_REPORTED_DURATION", observation["quality_flags"])
        self.assertEqual(observation["mapped_raw_fields"]["exit_date"], "44411")

    def test_same_reported_minute_is_not_zero_duration_scalping_proof(self):
        observation = self.normalize_day(day_row(U="0.375"))["observations"][0]
        self.assertFalse(observation["temporal_quarantined"])
        self.assertIn("SAME_REPORTED_MINUTE_NOT_INSTANTANEOUS_FILL", observation["quality_flags"])
        self.assertNotIn("scalper", observation)

    def test_missing_or_invalid_clocks_preserve_raw_and_quarantine(self):
        for value in ("", "NaN", "Infinity", "-0.1", "1", "0.99999999999"):
            with self.subTest(clock=value):
                observation = self.normalize_day(day_row(U=value))["observations"][0]
                self.assertIsNone(observation["exit_clock_local"])
                self.assertTrue(observation["temporal_quarantined"])
                self.assertEqual(observation["mapped_raw_fields"]["exit_time"], value)

    def test_nonfinite_optional_numbers_are_not_json_numeric_values(self):
        observation = self.normalize_day(day_row(J="NaN", L="Infinity", Z="-Infinity"))["observations"][0]
        self.assertIsNone(observation["initial_stop"])
        self.assertIsNone(observation["relative_stake"])
        self.assertIsNone(observation["reported_pnl_gbp"])
        self.assertIn("INITIAL_STOP_NONFINITE_OR_INVALID", observation["quality_flags"])
        json.dumps(observation, allow_nan=False)

    def test_boolean_numeric_looking_cells_are_not_dates_or_prices(self):
        observation = self.normalize_day(day_row(E="1", I="1"), types={
            ("Aug 2021 Day", "E9"): "b", ("Aug 2021 Day", "I9"): "b"})["observations"][0]
        self.assertIsNone(observation["entry_date_local"])
        self.assertIsNone(observation["entry_price"])
        self.assertTrue(observation["temporal_quarantined"])
        self.assertEqual(observation["raw_cells"]["E"], "1")
        self.assertIn("ENTRY_PRICE_CELL_TYPE_UNSUPPORTED", observation["quality_flags"])

    def test_1904_date_system_is_used_without_inferred_timezone(self):
        observation = self.normalize_day(day_row(E="0", AD="1"), date1904=True)["observations"][0]
        self.assertEqual(observation["entry_date_local"], "1904-01-01")
        self.assertEqual(observation["exit_date_local"], "1904-01-02")
        self.assertIsNone(observation["entry_at_utc"])

    def test_excel_fictional_leap_day_noninteger_extreme_dates_quarantine(self):
        for value in ("60", "44411.5", "1e100", "NaN"):
            with self.subTest(date=value):
                observation = self.normalize_day(day_row(E=value))["observations"][0]
                self.assertIsNone(observation["entry_date_local"])
                self.assertTrue(observation["temporal_quarantined"])

    def test_swing_uses_distinct_exit_and_pnl_columns(self):
        swing = day_row(AA="7", AC="https://example.invalid/exit", AE="44412", Z="999", AD="999")
        write_xlsx(self.path, {"Aug 2021 Day": {9: day_row()}, "Aug 2021 Swing": {11: swing}, "stats": {1: {"A": "synthetic"}}})
        result = normalize_workbook(self.path, source())
        observation = result["observations"][1]
        self.assertEqual(observation["record_kind"], "reported_swing_exit_leg")
        self.assertEqual(observation["reported_pnl_gbp"], "7")
        self.assertEqual(observation["exit_date_local"], "2021-08-04")
        self.assertEqual(observation["exit_post_url"], "https://example.invalid/exit")
        self.assertEqual(result["source_meta"]["unmapped_sheets"], ["stats"])
        self.assertEqual(len(normalize_workbook(self.path, source(), include_swing=False)["observations"]), 1)

    def test_same_link_different_signatures_flagged_without_merging_rows(self):
        write_xlsx(self.path, {"Aug 2021 Day": {9: day_row(), 10: day_row(I="102"), 11: day_row()}})
        result = normalize_workbook(self.path, source())
        self.assertEqual(result["source_meta"]["ambiguous_day_entry_link_groups"], 1)
        self.assertEqual(len(result["observations"]), 3)
        for row in result["observations"]:
            self.assertIn("ENTRY_LINK_HAS_MULTIPLE_REPORTED_ENTRY_SIGNATURES", row["quality_flags"])

    def test_equal_physical_rows_preserved_with_distinct_locators(self):
        write_xlsx(self.path, {"Aug 2021 Day": {9: day_row(), 10: day_row()}})
        first, second = normalize_workbook(self.path, source())["observations"]
        self.assertNotEqual(first["source_ref"], second["source_ref"])
        self.assertEqual(first["row_semantic_sha256"], second["row_semantic_sha256"])

    def test_incomplete_nonselected_row_is_counted_and_raw_evidence_preserved(self):
        missing_entry = day_row(I="", D="SYNTHETIC_MISSING_ENTRY")
        write_xlsx(self.path, {"Aug 2021 Day": {9: day_row(), 10: missing_entry},
                               "stats": {1: {"A": "synthetic statistics"}}})
        result = normalize_workbook(self.path, source())
        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(result["observations"][0]["source_row"], 9)
        selection = result["source_meta"]["physical_row_selection_by_sheet"]
        self.assertEqual(selection["Aug 2021 Day"], {
            "selected_row_count": 1, "nonselected_nonempty_row_count": 1,
            "nonselected_nonempty_source_rows": [10]})
        self.assertEqual(selection["stats"]["nonselected_nonempty_source_rows"], [1])
        self.assertIn("I entry price nonempty", result["source_meta"]["selection_policy"])
        raw = read_workbook(self.path)["sheets"]["Aug 2021 Day"]["rows"][10]
        self.assertEqual(raw, missing_entry)

    def test_transaction_cash_and_signed_qty_do_not_become_pnl_or_side(self):
        ident = "grittani_may_june_etrade_2020"
        write_xlsx(self.path, {"Sheet1": tim_rows(ident)})
        observation = normalize_workbook(self.path, source(ident))["observations"][0]
        self.assertEqual(observation["signed_quantity"], "-10")
        self.assertEqual(observation["cash_amount"], "999")
        self.assertIsNone(observation["side"])
        self.assertIsNone(observation["net_pnl"])
        self.assertIsNone(observation["transaction_clock_local"])
        self.assertIn("TRANSACTION_CASH_NOT_TRADE_PNL", observation["quality_flags"])

    def test_option_multiplier_and_broker_conflict_are_flagged(self):
        ident = "grittani_july_etrade_2020"
        write_xlsx(self.path, {"Sheet1": tim_rows(ident, transaction_type="Bought To Open")})
        observation = normalize_workbook(self.path, source(ident))["observations"][0]
        self.assertIn("OPTION_CONTRACT_MULTIPLIER_UNCONFIRMED", observation["quality_flags"])
        self.assertIn("PUBLISHER_BROKER_LABEL_CONFLICT", observation["quality_flags"])

    def test_nonfinite_transaction_fields_preserve_evidence(self):
        ident = "grittani_may_june_speedtrader_2020"
        write_xlsx(self.path, {"Sheet1": tim_rows(ident, signed_quantity="NaN", price="Infinity")})
        observation = normalize_workbook(self.path, source(ident))["observations"][0]
        self.assertIsNone(observation["signed_quantity"])
        self.assertIsNone(observation["price"])
        self.assertEqual(observation["mapped_raw_fields"]["signed_quantity"], "NaN")

    def test_explicit_no_stop_and_blank_stop_distinguished(self):
        no_stop = self.normalize_day(day_row(J="no sl"))["observations"][0]
        blank = self.normalize_day(day_row(J=""))["observations"][0]
        self.assertIn("NO_STOP_EXPLICITLY_REPORTED", no_stop["quality_flags"])
        self.assertIn("INITIAL_STOP_MISSING", blank["quality_flags"])

    def test_formula_cache_preserved_never_evaluated(self):
        write_xlsx(self.path, {"Aug 2021 Day": {9: day_row(I="100", Z="")}},
                   formulas={("Aug 2021 Day", "I9"): ("50+50", {}), ("Aug 2021 Day", "Z9"): ("1+1", {})},
                   types={("Aug 2021 Day", "I9"): "n", ("Aug 2021 Day", "Z9"): "n"})
        observation = normalize_workbook(self.path, source())["observations"][0]
        self.assertEqual(observation["entry_price"], "100")
        self.assertIsNone(observation["reported_pnl_gbp"])
        self.assertEqual(observation["cell_formulas"]["I"]["formula"], "50+50")
        self.assertIn("FORMULA_CACHED_VALUES_NOT_RECALCULATED", observation["quality_flags"])
        self.assertIn("FORMULA_CACHE_MISSING", observation["quality_flags"])

    def test_zip_repack_and_styles_dont_create_business_content_revision(self):
        sheets = {"Aug 2021 Day": {9: day_row()}}
        write_xlsx(self.path, sheets, compression=ZIP_STORED)
        before = normalize_workbook(self.path, source())
        write_xlsx(self.path, sheets, compression=ZIP_DEFLATED, styles=True,
                   extra={"docProps/core.xml": b"<synthetic/>"})
        after = normalize_workbook(self.path, source())
        self.assertNotEqual(before["source_meta"]["raw_sha256"], after["source_meta"]["raw_sha256"])
        self.assertEqual(before["source_meta"]["semantic_sha256"], after["source_meta"]["semantic_sha256"])
        self.assertEqual(before["observations"][0]["row_semantic_sha256"], after["observations"][0]["row_semantic_sha256"])

    def test_actual_cell_and_formula_changes_change_semantics(self):
        first = self.normalize_day()["observations"][0]["row_semantic_sha256"]
        changed = self.normalize_day(day_row(I="101"))["observations"][0]["row_semantic_sha256"]
        self.assertNotEqual(first, changed)
        write_xlsx(self.path, {"Aug 2021 Day": {9: day_row()}}, formulas={("Aug 2021 Day", "I9"): ("100", {"t": "shared", "si": "0"})})
        formula = normalize_workbook(self.path, source())["observations"][0]["row_semantic_sha256"]
        self.assertNotEqual(first, formula)

    def test_interpretation_changing_xml_types_change_semantic_hashes(self):
        text = self.normalize_day(day_row(I="1"))
        boolean = self.normalize_day(day_row(I="1"), types={("Aug 2021 Day", "I9"): "b"})
        self.assertEqual(text["observations"][0]["entry_price"], "1")
        self.assertIsNone(boolean["observations"][0]["entry_price"])
        self.assertNotEqual(text["source_meta"]["semantic_sha256"], boolean["source_meta"]["semantic_sha256"])
        self.assertNotEqual(text["observations"][0]["row_semantic_sha256"], boolean["observations"][0]["row_semantic_sha256"])

    def test_tampered_catalog_and_wrong_headers_fail_closed(self):
        spec = source("grittani_may_june_etrade_2020")
        rows = tim_rows(spec["id"])
        write_xlsx(self.path, {"Sheet1": rows})
        tampered = copy.deepcopy(spec)
        tampered["columns"]["cash_amount"] = "F"
        with self.assertRaisesRegex(DataError, "TRADER_COLUMN_MAPPING_MISMATCH"):
            normalize_workbook(self.path, tampered)
        rows[1]["E"], rows[1]["F"] = rows[1]["F"], rows[1]["E"]
        write_xlsx(self.path, {"Sheet1": rows})
        with self.assertRaisesRegex(DataError, "TRADER_HEADER_SCHEMA_MISMATCH"):
            normalize_workbook(self.path, spec)

    def test_unrelated_sheet_not_accepted_by_suffix_only(self):
        write_xlsx(self.path, {"Unrelated Day": {9: day_row()}})
        with self.assertRaisesRegex(DataError, "TRADER_EXPECTED_SHEET_MISSING"):
            normalize_workbook(self.path, source())

    def test_invalid_package_and_external_path_fail_safely(self):
        self.path.write_bytes(b"not a workbook")
        with self.assertRaisesRegex(DataError, "XLSX_PACKAGE_INVALID"):
            read_workbook(self.path)
        write_xlsx(self.path, {"Aug 2021 Day": {9: day_row()}}, relationship_target="../../outside.xml")
        with self.assertRaisesRegex(DataError, "XLSX_SHEET_TARGET_INVALID"):
            read_workbook(self.path)

    def test_duplicate_physical_cells_and_xml_entities_rejected(self):
        write_xlsx(self.path, {"Aug 2021 Day": {9: day_row()}})
        with ZipFile(self.path) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        member = "xl/worksheets/sheet1.xml"
        root = ET.fromstring(members[member])
        row = root.find(f"{{{M}}}sheetData/{{{M}}}row")
        row.append(copy.deepcopy(row[0]))
        members[member] = ET.tostring(root)
        with ZipFile(self.path, "w") as archive:
            for name, raw in members.items():
                archive.writestr(name, raw)
        with self.assertRaisesRegex(DataError, "XLSX_DUPLICATE_CELL"):
            read_workbook(self.path)
        write_xlsx(self.path, {"Aug 2021 Day": {9: day_row()}}, extra={
            "xl/workbook.xml": b'<!DOCTYPE x [<!ENTITY e "forbidden">]><x/>'})
        with self.assertRaisesRegex(DataError, "XLSX_XML_DECLARATION_FORBIDDEN"):
            read_workbook(self.path)


if __name__ == "__main__":
    unittest.main()
