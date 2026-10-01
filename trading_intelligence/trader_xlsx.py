"""Read-only adapters for eight documented publisher XLSX exports.

Cell strings and physical row locations are evidence, not broker trade IDs.
Formula caches are preserved but never evaluated. No timezone is inferred.
"""
from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .common import DataError, MAX_ROWS, read_limited

ADAPTER_VERSION = 2
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_MAX_UNCOMPRESSED = 100 * 1024 * 1024
_BUILTIN_FORMATS = {0: "General", 14: "mm-dd-yy", 20: "h:mm", 21: "h:mm:ss", 22: "m/d/yy h:mm", 49: "@"}

_ETRADE = {"transaction_date": "A", "transaction_type": "B", "symbol": "C",
           "signed_quantity": "D", "cash_amount": "E", "price": "F", "commission": "G"}
_DAY = {"channel": "B", "instrument": "D", "entry_date": "E", "entry_time": "F",
        "position_side": "H", "entry_price": "I", "initial_stop": "J", "relative_stake": "L",
        "entry_post": "N", "reason": "P", "chart_post": "R", "exit_price": "T", "exit_time": "U",
        "point_result": "W", "weighted_point_result": "X", "reported_pnl_gbp": "Z",
        "exit_post": "AB", "exit_date": "AD"}
_SWING = {key: value for key, value in _DAY.items()
          if key not in {"point_result", "weighted_point_result"}}
_SWING.update(reported_pnl_gbp="AA", exit_post="AC", exit_date="AE",
              point_result_raw="W", pip_result="X", weighted_pip_result="Y")
_TIM_MAPS = {
    "grittani_may_june_etrade_2020": dict(_ETRADE, description="H"),
    "grittani_july_etrade_2020": dict(_ETRADE, total_cash_amount="H"),
    "grittani_may_june_speedtrader_2020": {
        "transaction_date": "A", "symbol": "B", "signed_quantity": "C", "price": "D",
        "fees": "E", "net_cash_amount": "F"},
    "grittani_aug_dec_speedtrader_2020": {
        "transaction_date": "A", "entry_type_description": "B", "symbol": "C",
        "signed_quantity": "D", "price": "E", "fees": "F", "net_cash_amount": "G"},
}
_TIM_HEADERS = {
    "grittani_may_june_etrade_2020": dict(zip("ABCDEFGH", (
        "TransactionDate", "TransactionType", "Symbol", "Quantity", "Amount", "Price", "Commission", "Description"))),
    "grittani_july_etrade_2020": dict(zip("ABCDEFGH", (
        "TransactionDate", "TransactionType", "Symbol", "Quantity", "Amount", "Price", "Commission", "Total"))),
    "grittani_may_june_speedtrader_2020": dict(zip("ABCDEF", (
        "Trade Date", "Symbol", "QTY", "Price", "Fees", "Net Amount"))),
    "grittani_aug_dec_speedtrader_2020": dict(zip("ABCDEFG", (
        "Trade Date", "Entry Type Description", "Symbol", "QTY", "Price", "Fees", "Net Amount"))),
}
_TOM_MONTHS = {f"hougaard_2021_{month}": (f"2021-{month}", f"{name} 2021")
               for month, name in (("08", "Aug"), ("09", "Sep"), ("10", "Oct"), ("11", "Nov"))}


def _digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _xml(archive: ZipFile, member: str):
    try:
        raw = archive.read(member)
    except KeyError:
        raise DataError("XLSX_REQUIRED_PART_MISSING") from None
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise DataError("XLSX_XML_DECLARATION_FORBIDDEN")
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        raise DataError("XLSX_XML_INVALID") from None


def _integer(raw, code: str, minimum: int, maximum: int) -> int:
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdigit() or len(raw) > 10:
        raise DataError(code)
    value = int(raw)
    if not minimum <= value <= maximum:
        raise DataError(code)
    return value


def _column_number(column: str) -> int:
    value = 0
    for char in column:
        value = value * 26 + ord(char) - ord("A") + 1
    return value


def _read_archive(raw: bytes) -> dict:
    with ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(infos) > 50_000 or len(set(names)) != len(names):
            raise DataError("XLSX_PACKAGE_AMBIGUOUS")
        if sum(item.file_size for item in infos) > _MAX_UNCOMPRESSED:
            raise DataError("XLSX_UNCOMPRESSED_TOO_LARGE")
        if any(item.flag_bits & 1 for item in infos):
            raise DataError("XLSX_ENCRYPTION_UNSUPPORTED")
        strings = []
        if "xl/sharedStrings.xml" in names:
            shared = _xml(archive, "xl/sharedStrings.xml")
            strings = ["".join(node.text or "" for node in item.findall(".//m:t", _NS))
                       for item in shared.findall("m:si", _NS)]
        formats, xfs = dict(_BUILTIN_FORMATS), []
        if "xl/styles.xml" in names:
            styles = _xml(archive, "xl/styles.xml")
            for item in styles.findall("m:numFmts/m:numFmt", _NS):
                ident = _integer(item.get("numFmtId"), "XLSX_STYLE_INVALID", 0, 65535)
                formats[ident] = item.get("formatCode", "")
            xfs = styles.findall("m:cellXfs/m:xf", _NS)
        workbook = _xml(archive, "xl/workbook.xml")
        props = workbook.find("m:workbookPr", _NS)
        if props is not None and props.get("date1904", "0") not in {"0", "1", "true", "false"}:
            raise DataError("XLSX_DATE_SYSTEM_INVALID")
        date_system = "1904" if props is not None and props.get("date1904") in {"1", "true"} else "1900"
        relationships = _xml(archive, "xl/_rels/workbook.xml.rels")
        targets = {}
        for item in relationships:
            ident = item.get("Id")
            if not ident or ident in targets:
                raise DataError("XLSX_RELATIONSHIP_AMBIGUOUS")
            targets[ident] = item
        sheet_elements = workbook.find("m:sheets", _NS)
        if sheet_elements is None:
            raise DataError("XLSX_SHEETS_MISSING")
        sheets, total_rows = {}, 0
        for element in sheet_elements:
            name = element.get("name")
            if not name or name in sheets:
                raise DataError("XLSX_SHEET_NAME_AMBIGUOUS")
            rel = targets.get(element.get(_REL_ID))
            if rel is None or rel.get("TargetMode") == "External":
                raise DataError("XLSX_SHEET_RELATIONSHIP_INVALID")
            target = rel.get("Target", "")
            member = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            if not member.startswith("xl/") or "\\" in member or ":" in member:
                raise DataError("XLSX_SHEET_TARGET_INVALID")
            root = _xml(archive, member)
            rows, metadata, seen_rows = {}, {}, set()
            for row in root.findall("m:sheetData/m:row", _NS):
                row_number = _integer(row.get("r"), "XLSX_ROW_INVALID", 1, 1048576)
                if row_number in seen_rows:
                    raise DataError("XLSX_DUPLICATE_ROW")
                seen_rows.add(row_number)
                total_rows += 1
                if total_rows > MAX_ROWS:
                    raise DataError("XLSX_TOO_MANY_ROWS")
                values = {}
                for cell in row.findall("m:c", _NS):
                    ref, kind = cell.get("r", ""), cell.get("t", "n")
                    match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", ref)
                    if not match or int(match[2]) != row_number or _column_number(match[1]) > 16384:
                        raise DataError("XLSX_CELL_REFERENCE_INVALID")
                    column = match[1]
                    if column in values:
                        raise DataError("XLSX_DUPLICATE_CELL")
                    if kind not in {"n", "s", "inlineStr", "str", "b", "e", "d"}:
                        raise DataError("XLSX_CELL_TYPE_UNSUPPORTED")
                    node = cell.find("m:v", _NS)
                    value = node.text or "" if node is not None else ""
                    if kind == "s":
                        index = _integer(value, "XLSX_SHARED_STRING_INVALID", 0, max(0, len(strings) - 1))
                        if index >= len(strings):
                            raise DataError("XLSX_SHARED_STRING_INVALID")
                        value = strings[index]
                    elif kind == "inlineStr":
                        value = "".join(node.text or "" for node in cell.findall("m:is//m:t", _NS))
                    style_id = _integer(cell.get("s", "0"), "XLSX_STYLE_INVALID", 0, 65535)
                    if (xfs and style_id >= len(xfs)) or (not xfs and style_id != 0):
                        raise DataError("XLSX_STYLE_INVALID")
                    fmt_id = _integer(xfs[style_id].get("numFmtId", "0"), "XLSX_STYLE_INVALID", 0, 65535) if xfs else 0
                    formula = cell.find("m:f", _NS)
                    values[column] = value
                    metadata[ref] = {
                        "xml_type": kind, "number_format": formats.get(fmt_id, f"builtin:{fmt_id}"),
                        "formula": formula.text or "" if formula is not None else None,
                        "formula_attributes": dict(formula.attrib) if formula is not None else {},
                    }
                # Formula-only rows also carry evidence even without cached values.
                if any(value.strip() for value in values.values()) or any(
                    metadata[f"{column}{row_number}"]["formula"] is not None for column in values
                ):
                    rows[row_number] = values
            sheets[name] = {"rows": rows, "cell_metadata": metadata}
        semantic = [{"sheet": name, "row": number, "values": cells,
                     "xml_cell_types": _row_cell_types(sheet, number, cells),
                     "formulas": _row_formulas(sheet, number, cells)}
                    for name, sheet in sorted(sheets.items()) for number, cells in sorted(sheet["rows"].items())]
        return {"date_system": date_system, "sheets": sheets,
                "semantic_sha256": _digest({"date_system": date_system, "rows": semantic}),
                "raw_sha256": hashlib.sha256(raw).hexdigest()}


def read_workbook(path: Path | str) -> dict:
    """Decode bounded OOXML without evaluating formulas or opening external links."""
    raw = read_limited(Path(path))
    try:
        return _read_archive(raw)
    except DataError:
        raise
    except (BadZipFile, RuntimeError, OSError):
        raise DataError("XLSX_PACKAGE_INVALID") from None
    except (ValueError, TypeError, OverflowError, IndexError):
        raise DataError("XLSX_SCHEMA_INVALID") from None


def _row_formulas(sheet: dict, number: int, cells: dict) -> dict:
    return {column: {"formula": meta["formula"], "attributes": meta["formula_attributes"]}
            for column in cells
            if (meta := sheet["cell_metadata"][f"{column}{number}"])["formula"] is not None}


def _row_cell_types(sheet: dict, number: int, cells: dict) -> dict:
    # A boolean/error/date cell can contain the same raw text as a usable
    # numeric string. Its type changes interpretation and must be versioned.
    return {column: sheet["cell_metadata"][f"{column}{number}"]["xml_type"] for column in cells}


def _number(raw) -> Decimal | None:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 100:
        return None
    try:
        value = Decimal(raw.strip())
    except InvalidOperation:
        return None
    return value if value.is_finite() and abs(value.adjusted()) <= 100 else None


def _number_field(raw: str, field: str, flags: list[str], *, required: bool = False) -> str | None:
    if not raw.strip():
        if required:
            flags.append(f"{field.upper()}_MISSING")
        return None
    value = _number(raw)
    if value is None:
        flags.append(f"{field.upper()}_NONFINITE_OR_INVALID")
    return str(value) if value is not None else None


def _excel_date(raw: str, system: str) -> str | None:
    value = _number(raw)
    if value is None or value != value.to_integral_value() or not 0 <= value <= 2958465:
        return None
    serial = int(value)
    if system == "1900" and serial == 60:
        return None  # Excel's fictional 1900-02-29 is not a real date.
    base = date(1904, 1, 1) if system == "1904" else date(1899, 12, 31) if serial < 60 else date(1899, 12, 30)
    try:
        return (base + timedelta(days=serial)).isoformat()
    except (OverflowError, ValueError):
        return None


def _clock(raw: str) -> str | None:
    value = _number(raw)
    if value is None or not 0 <= value < 1:
        return None
    second = int((value * 86400).to_integral_value(rounding=ROUND_HALF_UP))
    if second >= 86400:
        return None
    return f"{second // 3600:02d}:{second // 60 % 60:02d}:{second % 60:02d}"


def _validate_source(source: dict) -> tuple[str, dict, list[str]]:
    if not isinstance(source, dict):
        raise DataError("TRADER_CATALOG_SOURCE_INVALID")
    ident = source.get("id")
    if not isinstance(ident, str):
        raise DataError("TRADER_CATALOG_SOURCE_INVALID")
    if ident in _TIM_MAPS:
        if source.get("trader") != "Tim Grittani" or source.get("sheet_name") != "Sheet1":
            raise DataError("TRADER_CATALOG_SOURCE_MISMATCH")
        expected = _TIM_MAPS[ident]
        names = ["Sheet1"]
    elif ident in _TOM_MONTHS:
        month, name = _TOM_MONTHS[ident]
        if (source.get("trader") != "Tom Hougaard" or source.get("month") != month
                or source.get("sheet_name") != name + " Day" or source.get("swing_columns") != _SWING):
            raise DataError("TRADER_CATALOG_SOURCE_MISMATCH")
        expected, names = _DAY, [name + " Day", name + " Swing"]
    else:
        raise DataError("TRADER_SOURCE_UNSUPPORTED")
    if source.get("columns") != expected:
        raise DataError("TRADER_COLUMN_MAPPING_MISMATCH")
    return ident, expected, names


def _base_observation(workbook: dict, source: dict, name: str, row_number: int,
                      cells: dict, fields: dict, sheet: dict, kind: str, columns: dict) -> dict:
    formulas = _row_formulas(sheet, row_number, cells)
    flags = ["TIMEZONE_UNVERIFIED", "BROKER_FILL_NOT_VERIFIED", "FULL_HISTORY_NOT_VERIFIED",
             "ML_USE_RIGHTS_UNCONFIRMED", "SOURCE_ROW_LOCATOR_NOT_STABLE_TRADE_ID"]
    if formulas:
        flags.append("FORMULA_CACHED_VALUES_NOT_RECALCULATED")
        if any(not cells[column] for column in formulas):
            flags.append("FORMULA_CACHE_MISSING")
    if any(sheet["cell_metadata"][f"{column}{row_number}"]["xml_type"] == "e" for column in cells):
        flags.append("EXCEL_ERROR_CELL_PRESENT")
    ident = source["id"]
    return {
        "adapter_version": ADAPTER_VERSION, "source": "publisher_xlsx", "source_id": ident,
        "trader": source["trader"], "record_kind": kind, "sheet": name, "source_row": row_number,
        "source_ref": f"{ident}:{name}:row{row_number}",
        "source_row_identity": {"source_id": ident, "sheet": name, "source_row": row_number},
        "identity_basis": "source_row_locator_not_broker_trade_id",
        "raw_sha256": workbook["raw_sha256"], "source_url": source.get("publisher_url"),
        "data_origin": "synthetic_fixture" if source.get("synthetic") is True else "publisher_shared_export",
        "raw_cells": dict(cells), "raw_cell_types": _row_cell_types(sheet, row_number, cells),
        "mapped_raw_fields": fields, "cell_formulas": formulas,
        "mapped_cell_types": {field: sheet["cell_metadata"].get(f"{column}{row_number}", {}).get("xml_type")
                              for field, column in columns.items()},
        "row_semantic_sha256": _digest({"date_system": workbook["date_system"], "raw_cells": cells,
                                         "xml_cell_types": _row_cell_types(sheet, row_number, cells), "formulas": formulas}),
        "date_system": workbook["date_system"], "quality_flags": flags,
        "training_ready": False, "full_history_verified": False, "broker_fill_verified": False,
        "temporal_quarantined": False, "timezone": None,
        "entry_at_utc": None, "exit_at_utc": None, "transaction_at_utc": None,
        "net_pnl": None, "pnl_currency": None,
    }


def _mapped_value(observation: dict, field: str) -> str:
    kind = observation["mapped_cell_types"].get(field)
    if kind not in {None, "n", "s", "str", "inlineStr"}:
        observation["quality_flags"].append(f"{field.upper()}_CELL_TYPE_UNSUPPORTED")
        return ""
    return observation["mapped_raw_fields"].get(field, "")


def _tom(observation: dict, source: dict) -> None:
    fields, flags = observation["mapped_raw_fields"], observation["quality_flags"]
    flags.extend(["EXACT_INSTRUMENT_PRODUCT_UNVERIFIED", "REPORTED_CLOCK_NOT_EXECUTION_TIMESTAMP",
                  "RELATIVE_STAKE_NOT_CONTRACT_QUANTITY", "RELATIVE_STAKE_NOT_ACCOUNT_RISK_PERCENT",
                  "EXIT_LEG_NOT_VERIFIED_UNIQUE_TRADE", "COST_SEMANTICS_UNVERIFIED"])
    dates = {key: _excel_date(_mapped_value(observation, key), observation["date_system"]) for key in ("entry_date", "exit_date")}
    clocks = {key: _clock(_mapped_value(observation, key)) for key in ("entry_time", "exit_time")}
    observation.update(instrument=fields["instrument"], side=fields["position_side"],
                       entry_date_local=dates["entry_date"], exit_date_local=dates["exit_date"],
                       entry_clock_local=clocks["entry_time"], exit_clock_local=clocks["exit_time"],
                       transaction_date_local=None, transaction_clock_local=None,
                       entry_post_url=fields["entry_post"], exit_post_url=fields["exit_post"],
                       chart_post_url=fields["chart_post"], quantity=None, signed_quantity=None,
                       strategy_identifier=None, note_raw=fields["reason"],
                       reported_duration_minutes=None, reported_pnl_currency="GBP")
    for field in ("entry_price", "exit_price", "relative_stake", "reported_pnl_gbp"):
        observation[field] = _number_field(_mapped_value(observation, field), field, flags, required=field in {"entry_price", "exit_price"})
    stop = _mapped_value(observation, "initial_stop").strip()
    if not stop:
        flags.append("INITIAL_STOP_MISSING")
        observation["initial_stop"] = None
    elif stop.casefold() == "no sl":
        flags.append("NO_STOP_EXPLICITLY_REPORTED")
        observation["initial_stop"] = None
    else:
        observation["initial_stop"] = _number_field(stop, "initial_stop", flags)
    note = fields["reason"].strip()
    if note and note.upper() != "N/A":
        flags.append("NOTE_TIMING_UNVERIFIED")
        if note.casefold() in {"breakout strategy", "30 point rule"}:
            observation["strategy_identifier"] = f"publisher_label:{note}"
            flags.append("STRATEGY_LABEL_NOT_VERIFIED_POLICY")
    for key, value in {**dates, **clocks}.items():
        if value is None:
            flags.append(f"{key.upper()}_MISSING_OR_INVALID")
            observation["temporal_quarantined"] = True
    if observation["temporal_quarantined"]:
        flags.append("INCOMPLETE_OR_INVALID_DATE_CLOCK")
    else:
        numeric = {key: _number(fields[key]) for key in (*dates, *clocks)}
        duration = (numeric["exit_date"] + numeric["exit_time"] - numeric["entry_date"] - numeric["entry_time"]) * 1440
        observation["reported_duration_minutes"] = str(duration.quantize(Decimal("0.001")))
        if duration < Decimal("-0.00001"):
            flags.append("NEGATIVE_REPORTED_DURATION")
            observation["temporal_quarantined"] = True
        elif abs(duration) < Decimal("0.00001"):
            flags.append("SAME_REPORTED_MINUTE_NOT_INSTANTANEOUS_FILL")
    parsed_clocks = [_number(fields[key]) for key in clocks if clocks[key] is not None]
    if parsed_clocks and all(abs(value * 86400 - (value * 1440).to_integral_value(rounding=ROUND_HALF_UP) * 60) <= Decimal("0.00001")
                             for value in parsed_clocks):
        flags.append("MINUTE_ALIGNED_REPORTED_CLOCK")
    elif parsed_clocks:
        flags.append("NON_MINUTE_REPORTED_CLOCK")
    if dates["entry_date"] and dates["entry_date"][:7] != source["month"]:
        flags.append("ENTRY_DATE_OUTSIDE_WORKBOOK_LABEL_MONTH")


def _tim(observation: dict) -> None:
    fields, flags = observation["mapped_raw_fields"], observation["quality_flags"]
    flags.extend(["INTRADAY_TIME_MISSING", "OPENING_INVENTORY_UNKNOWN", "INTRADAY_ROW_ORDER_UNVERIFIED",
                  "TRANSACTION_CASH_NOT_TRADE_PNL", "DECISION_REASON_MISSING", "EXACT_INSTRUMENT_CONTRACT_UNVERIFIED",
                  "SIGNED_QUANTITY_NOT_POSITION_SIDE"])
    transaction_date = _excel_date(_mapped_value(observation, "transaction_date"), observation["date_system"])
    if transaction_date is None:
        flags.append("TRANSACTION_DATE_MISSING_OR_INVALID")
        observation["temporal_quarantined"] = True
    action = fields.get("transaction_type") or fields.get("entry_type_description")
    observation.update(instrument=fields["symbol"], side=None, transaction_action=action,
                       transaction_date_local=transaction_date, transaction_clock_local=None,
                       entry_date_local=None, entry_clock_local=None, exit_date_local=None, exit_clock_local=None,
                       quantity=None, entry_price=None, exit_price=None, initial_stop=None,
                       relative_stake=None, strategy_identifier=None, note_raw=None)
    for field in ("signed_quantity", "price", "cash_amount", "net_cash_amount", "total_cash_amount", "fees", "commission"):
        if field in fields:
            observation[field] = _number_field(_mapped_value(observation, field), field, flags, required=field in {"signed_quantity", "price"})
    if observation.get("signed_quantity") is not None and Decimal(observation["signed_quantity"]) == 0:
        flags.append("ZERO_SIGNED_QUANTITY")
    if action in {"Bought To Open", "Sold To Close", "Sold To Open", "Bought To Close"}:
        flags.append("OPTION_CONTRACT_MULTIPLIER_UNCONFIRMED")
    if observation["source_id"] == "grittani_july_etrade_2020":
        flags.append("PUBLISHER_BROKER_LABEL_CONFLICT")


def mark_ambiguous_entry_links(observations: list[dict]) -> int:
    """Flag entry posts with differing reported signatures; never merge legs."""
    groups = defaultdict(list)
    for observation in observations:
        if observation["record_kind"] == "reported_day_exit_leg" and observation["mapped_raw_fields"].get("entry_post"):
            groups[observation["mapped_raw_fields"]["entry_post"]].append(observation)
    count = 0
    for group in groups.values():
        signatures = {tuple(item["mapped_raw_fields"].get(field) for field in
                            ("instrument", "position_side", "entry_date", "entry_time", "entry_price")) for item in group}
        if len(signatures) > 1:
            count += 1
            for observation in group:
                observation["quality_flags"] = sorted(set(observation["quality_flags"]) | {"ENTRY_LINK_HAS_MULTIPLE_REPORTED_ENTRY_SIGNATURES"})
    return count


def normalize_workbook(path: Path | str, source: dict, include_swing: bool = True) -> dict:
    """Return source metadata and conservative row observations, without writes."""
    ident, day_columns, names = _validate_source(source)
    workbook = read_workbook(path)
    if names[0] not in workbook["sheets"]:
        raise DataError("TRADER_EXPECTED_SHEET_MISSING")
    if ident in _TIM_MAPS:
        headers = workbook["sheets"]["Sheet1"]["rows"].get(1, {})
        if any(headers.get(column) != label for column, label in _TIM_HEADERS[ident].items()):
            raise DataError("TRADER_HEADER_SCHEMA_MISMATCH")
    observations, mapped_names = [], []
    selected_rows_by_sheet = {name: set() for name in workbook["sheets"]}
    for name, sheet in workbook["sheets"].items():
        if name not in names or (name.endswith(" Swing") and not include_swing):
            continue
        mapped_names.append(name)
        columns = _SWING if name.endswith(" Swing") else day_columns
        tom = ident in _TOM_MONTHS
        kind = ("reported_swing_exit_leg" if name.endswith(" Swing") else "reported_day_exit_leg") if tom else "publisher_shared_transaction_row"
        for row_number, cells in sorted(sheet["rows"].items()):
            if tom:
                included = cells.get("H") in {"Long", "Short"} and bool(cells.get("D")) and bool(cells.get("I"))
            else:
                included = row_number > 1 and bool(cells.get(columns["transaction_date"])) and bool(cells.get(columns["symbol"]))
            if not included:
                continue
            selected_rows_by_sheet[name].add(row_number)
            fields = {field: cells.get(column, "") for field, column in columns.items()}
            observation = _base_observation(workbook, source, name, row_number, cells, fields, sheet, kind, columns)
            if tom:
                _tom(observation, source)
            else:
                _tim(observation)
            observation["quality_flags"] = sorted(set(observation["quality_flags"]))
            observations.append(observation)
    ambiguous_count = mark_ambiguous_entry_links(observations)
    metadata = {
        "adapter_version": ADAPTER_VERSION, "source_id": ident, "trader": source["trader"],
        "raw_sha256": workbook["raw_sha256"], "semantic_sha256": workbook["semantic_sha256"],
        "semantic_hash_method": "canonical decoded physical rows, XML cell types, formulas and date system; excludes ZIP packaging and styles",
        "date_system": workbook["date_system"], "sheet_names": list(workbook["sheets"]),
        "mapped_sheets": mapped_names, "unmapped_sheets": sorted(set(workbook["sheets"]) - set(mapped_names)),
        "selection_policy": (
            "Exact catalog month Day/Swing sheets (Swing only when include_swing=true); H exactly Long or Short, "
            "D instrument and I entry price nonempty. Other physical rows remain in the raw workbook and are not observations."
            if ident in _TOM_MONTHS else
            "Exact catalog Sheet1; physical row > 1 with nonempty mapped transaction_date and symbol. "
            "Other physical rows remain in the raw workbook and are not observations."
        ),
        "nonempty_physical_row_definition": "At least one nonblank decoded cell value or formula, including formula-only rows without cached values",
        "physical_row_selection_by_sheet": {
            name: {
                "selected_row_count": len(selected_rows_by_sheet[name]),
                "nonselected_nonempty_row_count": len(set(sheet["rows"]) - selected_rows_by_sheet[name]),
                "nonselected_nonempty_source_rows": sorted(set(sheet["rows"]) - selected_rows_by_sheet[name]),
            }
            for name, sheet in workbook["sheets"].items()
        },
        "row_count": len(observations), "record_kind_counts": dict(Counter(row["record_kind"] for row in observations)),
        "temporal_quarantined_rows": sum(row["temporal_quarantined"] for row in observations),
        "ambiguous_day_entry_link_groups": ambiguous_count,
        "training_ready": False, "full_history_verified": False, "broker_fill_verified": False,
        "include_swing": include_swing,
    }
    return {"source_meta": metadata, "observations": observations}
