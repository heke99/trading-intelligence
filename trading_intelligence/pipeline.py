"""Import orchestration. Raw acquisition is deliberately separate from learning."""
from __future__ import annotations

import csv
import io
from pathlib import Path

from .collective2 import C2Client, parse_envelope
from .common import DataError, MAX_ROWS, load_json, positive_id, read_limited
from .normalize import normalize_record
from .store import DatasetStore


def _ingest(store: DatasetStore, manifest: dict, rows: list[dict], digest: str, kind: str,
            *, context: dict) -> None:
    for row_number, raw in enumerate(rows, 1):
        manifest["source_rows"] += 1
        try:
            normalized = normalize_record(raw, kind, int(manifest["strategy_id"]), **context)
        except DataError as error:
            store.quarantine(manifest, digest, kind, row_number, str(error))
        else:
            store.add_record(manifest, normalized, raw, digest, row_number, context=context)
    store.save_manifest(manifest)


def _failure_code(error: BaseException) -> str:
    return str(error) if isinstance(error, DataError) else ("INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "IMPORT_IO_OR_INTERNAL_ERROR")


def import_json(path: Path, out: Path, *, kind: str, strategy_id: int,
                synthetic: bool = False, naive_timezone: str | None = None,
                timezone_evidence: str | None = None) -> dict:
    strategy_id = positive_id(strategy_id)
    if kind not in ("orders", "closed_trades"):
        raise DataError("KIND_NOT_ALLOWED")
    context = dict(synthetic=synthetic, naive_timezone=naive_timezone, timezone_evidence=timezone_evidence)
    with DatasetStore(out) as store:
        m = store.start_run(strategy_id, "local_api_json", synthetic=synthetic)
        m["endpoint_traversal"][kind] = "unverified_local_file"
        try:
            raw = read_limited(Path(path))
            digest = store.archive(raw, m, kind)
            rows, cursor = parse_envelope(raw)
            _ingest(store, m, rows, digest, kind, context=context)
            if cursor:
                m["endpoint_traversal"][kind] = "incomplete"
            # A locally supplied terminal page does not prove all preceding pages were supplied.
            return store.finish(m)
        except BaseException as error:
            store.finish(m, _failure_code(error))
            raise


def fetch_history(client: C2Client, out: Path, *, strategy_id: int,
                  commission_plan: str = "0", naive_timezone: str | None = None,
                  timezone_evidence: str | None = None) -> dict:
    strategy_id = positive_id(strategy_id)
    # Keep the version identity identical to importing the saved API response.
    context = dict(synthetic=False, naive_timezone=naive_timezone,
                   timezone_evidence=timezone_evidence)
    with DatasetStore(out) as store:
        m = store.start_run(strategy_id, "api4")
        m["commission_plan_requested"] = commission_plan
        m["endpoint_traversal"] = {"closed_trades": "incomplete", "orders": "incomplete"}
        store.save_manifest(m)
        try:
            for kind in ("closed_trades", "orders"):
                for page in client.pages(kind, strategy_id, commission_plan=commission_plan):
                    digest = store.archive(page.body, m, kind)
                    _ingest(store, m, page.rows, digest, kind, context=context)
                m["endpoint_traversal"][kind] = "complete"
                store.save_manifest(m)
            # Exhausted cursors do NOT establish inception coverage, rights or execution quality.
            return store.finish(m)
        except BaseException as error:
            store.finish(m, _failure_code(error))
            raise


def _csv_rows(raw: bytes, delimiter: str | None = None) -> tuple[list[str], list[dict], str]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise DataError("CSV_ENCODING_USE_UTF8") from None
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:65536], delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
    if delimiter not in (",", ";", "\t"):
        raise DataError("CSV_DELIMITER_INVALID")
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        header = next(reader, None)
        if not header or any(not h.strip() or len(h) > 200 for h in header):
            raise DataError("CSV_HEADER_INVALID")
        if len({h.casefold() for h in header}) != len(header):
            raise DataError("CSV_DUPLICATE_HEADER")
        rows = []
        for cells in reader:
            if not cells:
                continue
            if len(cells) != len(header):
                raise DataError("CSV_ROW_WIDTH_MISMATCH")
            if len(rows) >= MAX_ROWS:
                raise DataError("CSV_ROW_LIMIT")
            rows.append(dict(zip(header, cells)))
    except csv.Error:
        raise DataError("CSV_PARSE_ERROR") from None
    return header, rows, delimiter


def inspect_csv(path: Path) -> dict:
    header, rows, delimiter = _csv_rows(read_limited(Path(path)))
    # No private row values printed; the user supplies a reviewed field mapping next.
    return {"columns": header, "row_count": len(rows), "detected_delimiter": delimiter,
            "mapping_required": True, "source_format_verified": False}


CSV_FIELDS = {
    "Id", "TradeId", "StrategyId", "OpenDate", "CloseDate", "AvgOpenFillPrice", "AvgCloseFillPrice",
    "OpenedQuantity", "ClosedQuantity", "OpenSide", "CloseSide", "ProfitLoss", "Commission",
    "SignalId", "PostedDate", "Side", "OpenClose", "OrderStatus", "OrderQuantity", "FilledQuantity",
    "AvgFillPrice", "OrderType", "TIF", "Limit", "Stop", "StopLoss", "ProfitTarget",
    "C2Symbol.FullSymbol", "C2Symbol.SymbolType", "C2Symbol.Expiry", "C2Symbol.Underlying",
    "C2Symbol.PutOrCall", "C2Symbol.StrikePrice", "ExchangeSymbol.Currency",
    "ExchangeSymbol.SecurityExchange", "ExchangeSymbol.SecurityType", "ExchangeSymbol.PriceMultiplier",
    "ExchangeSymbol.MaturityMonthYear",
}


def import_csv(path: Path, mapping_path: Path, out: Path, *, strategy_id: int, synthetic: bool = False) -> dict:
    strategy_id = positive_id(strategy_id)
    with DatasetStore(out) as store:
        m = store.start_run(strategy_id, "mapped_csv", synthetic=synthetic)
        try:
            raw = read_limited(Path(path))
            digest = store.archive(raw, m, "csv", suffix="csv")
            mapping_raw = read_limited(Path(mapping_path))
            store.archive(mapping_raw, m, "csv_mapping")
            mapping = load_json(mapping_raw)
            if not isinstance(mapping, dict) or mapping.get("version") != 1:
                raise DataError("CSV_MAPPING_VERSION_INVALID")
            kind = mapping.get("kind")
            if kind not in ("orders", "closed_trades"):
                raise DataError("CSV_MAPPING_KIND_INVALID")
            header, source_rows, _ = _csv_rows(raw, mapping.get("delimiter"))
            fields = mapping.get("fields")
            if not isinstance(fields, dict) or not fields:
                raise DataError("CSV_MAPPING_FIELDS_REQUIRED")
            for target, col in fields.items():
                if target not in CSV_FIELDS or not isinstance(col, str) or col not in header:
                    raise DataError("CSV_MAPPING_UNKNOWN_COLUMN_OR_FIELD")
            required = ({"C2Symbol.FullSymbol", "OpenDate", "CloseDate", "OpenSide", "OpenedQuantity", "ClosedQuantity", "AvgOpenFillPrice", "AvgCloseFillPrice"}
                        if kind == "closed_trades" else {"C2Symbol.FullSymbol", "PostedDate", "Side", "OrderStatus", "OrderQuantity"})
            id_options = {"Id", "TradeId"} if kind == "closed_trades" else {"Id", "SignalId"}
            if not required.issubset(fields) or not id_options.intersection(fields):
                raise DataError("CSV_MAPPING_REQUIRED_FIELDS_MISSING")
            side_values = mapping.get("side_values", {})
            if not isinstance(side_values, dict) or any(v not in ("1", "2") for v in side_values.values()):
                raise DataError("CSV_SIDE_MAPPING_INVALID")
            context = dict(synthetic=synthetic, naive_timezone=mapping.get("naive_timezone"),
                           timezone_evidence=mapping.get("timezone_evidence"),
                           date_format=mapping.get("datetime_format"), posted_utc_documented=False)
            rows = []
            for source in source_rows:
                row: dict = {"StrategyId": strategy_id, "__csv_source_row__": source}
                for target, col in fields.items():
                    value = source[col] if source[col] != "" else None
                    if target in ("Side", "OpenSide", "CloseSide") and value in side_values:
                        value = side_values[value]
                    if "." in target:
                        parent, key = target.split(".", 1)
                        row.setdefault(parent, {})[key] = value
                    else:
                        row[target] = value
                rows.append(row)
            m["endpoint_traversal"][kind] = "unverified_local_file"
            _ingest(store, m, rows, digest, kind, context=context)
            return store.finish(m)
        except BaseException as error:
            store.finish(m, _failure_code(error))
            raise
