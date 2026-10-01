"""Offline adapters for dated image rows, journal summaries and teaching cards.

These records preserve publisher evidence; they never become execution fills or
point-in-time model features. Source receipts are syntax checked, not independently
authenticated. Raw archives and receipt-to-asset checks belong to the caller.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlsplit

from .common import DataError, MAX_BYTES, MAX_ROWS, decimal_text, json_bytes, load_json, sha256

NORMALIZER_VERSION = 1
ADAPTER_VERSION = NORMALIZER_VERSION
KINDS = {"image_transactions", "journal_summaries", "strategy_cards"}
IMAGE_RECORD_KIND = "dated_transaction_row_transcribed_from_publisher_shared_broker_screenshot"
JOURNAL_RECORD_KIND = "publisher_reported_closed_trade_summary"
IMAGE_COLUMNS = {"TradeDate", "Symbol", "QTY", "Price", "Fees", "NetAmount"}
COMMON_FLAGS = ["BROKER_NOT_INDEPENDENTLY_AUTHENTICATED", "FULL_HISTORY_UNVERIFIED",
                "TRAINING_RIGHTS_NOT_VERIFIED", "POINT_IN_TIME_FEATURES_NOT_BUILT"]


def _text(value, code: str, *, limit: int = 300) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise DataError(code)
    return value


def _identifier(value, code: str) -> str:
    value = _text(value, code, limit=200)
    if value != value.strip():
        raise DataError(code)
    return value


def _url(value) -> str:
    value = _text(value, "EVIDENCE_SOURCE_URL_INVALID", limit=2048)
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname and
                 parsed.username is None and parsed.password is None and not parsed.fragment and
                 value == value.strip() and not any(c.isspace() for c in value))
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise DataError("EVIDENCE_SOURCE_URL_INVALID")
    return value


def _digest(value) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise DataError("EVIDENCE_RECEIPT_HASH_INVALID")
    return value.lower()


def _positive_int(value, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DataError(code)
    return value


def _iso_date(value) -> str:
    value = _text(value, "EVIDENCE_DATE_INVALID", limit=10)
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise DataError("EVIDENCE_DATE_INVALID") from None
    return value


def _date_pair(raw, parsed) -> None:
    _iso_date(parsed)
    raw = _text(raw, "EVIDENCE_DATE_INVALID", limit=20)
    try:
        if datetime.strptime(raw, "%m/%d/%Y").date().isoformat() != parsed:
            raise ValueError
    except ValueError:
        raise DataError("EVIDENCE_DATE_MAPPING_MISMATCH") from None


def _receipt_time(value) -> str:
    value = _text(value, "EVIDENCE_RECEIPT_TIME_INVALID", limit=100)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError
    except ValueError:
        raise DataError("EVIDENCE_RECEIPT_TIME_INVALID") from None
    return value


def _null_fields(row: dict, names: tuple[str, ...]) -> None:
    # Missing evidence is preserved as null. A newly populated field requires a
    # separate adapter/policy; it cannot silently change the meaning of this one.
    if any(name not in row or row[name] is not None for name in names):
        raise DataError("EVIDENCE_UNSUPPORTED_EXECUTION_OR_TIME_CLAIM")


def _rectangle(value, width: int, height: int) -> list[int]:
    if not isinstance(value, list) or len(value) != 4 or any(isinstance(n, bool) or not isinstance(n, int) for n in value):
        raise DataError("EVIDENCE_IMAGE_LOCATOR_INVALID")
    x1, y1, x2, y2 = value
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise DataError("EVIDENCE_IMAGE_LOCATOR_INVALID")
    return value


def _base(row: dict, *, source_id: str, publisher_source_id: str, ordinal: int,
          record_kind: str, sheet: str, identity: str, identity_basis: str,
          cells: dict, mapped: dict, provenance: dict, usage_role: str,
          flags: list[str], temporal_quarantined: bool) -> dict:
    trader = _text(row.get("trader"), "EVIDENCE_TRADER_INVALID")
    semantic = {"publisher_source_id": publisher_source_id, "trader": trader,
                "record_kind": record_kind, "source_row_identity": identity,
                "raw_cells": cells, "mapped_raw_fields": mapped}
    return {"normalizer_version": NORMALIZER_VERSION, "source": "publisher_evidence",
            "source_id": source_id, "publisher_source_id": publisher_source_id,
            "trader": trader, "record_kind": record_kind, "sheet": sheet,
            "source_row": ordinal, "source_row_identity": identity,
            "identity_basis": identity_basis, "raw_cells": cells,
            "mapped_raw_fields": mapped, "row_semantic_sha256": sha256(json_bytes(semantic)),
            "provenance": provenance, "usage_role": usage_role,
            "data_origin": "publisher_reported_unverified",
            "quality_flags": sorted(set(COMMON_FLAGS + flags)),
            "training_ready": False, "full_history_verified": False,
            "broker_verified": False, "independently_broker_authenticated": False,
            "temporal_quarantined": temporal_quarantined}


def _image(row: dict, source_id: str, ordinal: int) -> dict:
    if row.get("schema_version") != "1.0" or row.get("record_kind") != IMAGE_RECORD_KIND:
        raise DataError("EVIDENCE_IMAGE_SCHEMA_UNSUPPORTED")
    publisher_id = _identifier(row.get("source_id"), "EVIDENCE_SOURCE_ID_INVALID")
    source_url, asset_url = _url(row.get("source_url")), _url(row.get("source_asset_url"))
    asset_hash = _digest(row.get("source_asset_sha256"))
    retrieved_at = _receipt_time(row.get("source_retrieved_at_utc"))
    image_row = _positive_int(row.get("source_row"), "EVIDENCE_IMAGE_ROW_INVALID")
    width = _positive_int(row.get("source_asset_width"), "EVIDENCE_IMAGE_SIZE_INVALID")
    height = _positive_int(row.get("source_asset_height"), "EVIDENCE_IMAGE_SIZE_INVALID")
    rectangle = _rectangle(row.get("source_rectangle_xyxy"), width, height)
    expected_ref = f"sha256:{asset_hash}#image-data-row={image_row}&rect=" + ",".join(map(str, rectangle))
    if row.get("physical_row_ref") != expected_ref:
        raise DataError("EVIDENCE_IMAGE_LOCATOR_RECEIPT_MISMATCH")
    cells = row.get("raw_cells_display_text")
    if not isinstance(cells, dict) or set(cells) != IMAGE_COLUMNS or any(not isinstance(v, str) for v in cells.values()):
        raise DataError("EVIDENCE_IMAGE_CELLS_INVALID")
    verified = row.get("verified_columns")
    if (not isinstance(verified, list) or len(verified) != len(IMAGE_COLUMNS) or
            any(not isinstance(v, str) for v in verified) or set(verified) != IMAGE_COLUMNS):
        raise DataError("EVIDENCE_IMAGE_COLUMNS_NOT_VERIFIED")
    column_rectangles = row.get("source_column_rectangles_xyxy")
    if not isinstance(column_rectangles, dict) or set(column_rectangles) != IMAGE_COLUMNS:
        raise DataError("EVIDENCE_IMAGE_LOCATOR_INVALID")
    for value in column_rectangles.values():
        x1, y1, x2, y2 = _rectangle(value, width, height)
        if not (rectangle[0] <= x1 < x2 <= rectangle[2] and rectangle[1] <= y1 < y2 <= rectangle[3]):
            raise DataError("EVIDENCE_IMAGE_LOCATOR_INVALID")
    _null_fields(row, ("entry_clock_raw", "exit_clock_raw", "entry_at_utc", "exit_at_utc",
                       "timezone", "side", "transaction_action", "entry_price", "exit_price",
                       "currency", "strategy_identifier", "stop", "source_sheet", "source_spreadsheet_row"))
    _date_pair(row.get("date_raw"), row.get("date_local"))
    if cells["TradeDate"] != row["date_raw"] or cells["Symbol"] != row.get("instrument"):
        raise DataError("EVIDENCE_DISPLAY_MAPPING_MISMATCH")
    for column, field_name in (("QTY", "quantity"), ("Price", "transaction_price"),
                               ("Fees", "fees_reported"), ("NetAmount", "net_cash_amount_reported")):
        left = decimal_text(cells[column], required=True)
        right = decimal_text(row.get(field_name), required=True)
        if Decimal(left) != Decimal(right):
            raise DataError("EVIDENCE_DISPLAY_MAPPING_MISMATCH")
    _text(row.get("quantity_definition"), "EVIDENCE_QUANTITY_BASIS_MISSING", limit=1000)
    _text(row.get("verification_method"), "EVIDENCE_VERIFICATION_METHOD_MISSING", limit=1000)
    _text(row.get("source_asset_path"), "EVIDENCE_ASSET_PATH_MISSING", limit=2048)
    mapped = {key: row[key] for key in ("date_raw", "date_local", "instrument", "quantity",
              "transaction_price", "fees_reported", "net_cash_amount_reported", "quantity_definition")}
    # The asset hash is a receipt, not a trade identifier. Re-saving the same
    # image should not manufacture another semantic version of unchanged cells.
    identity = f"{publisher_id}#image-data-row={image_row}&rect=" + ",".join(map(str, rectangle))
    provenance = {"source_url": source_url, "source_asset_url": asset_url,
                  "source_asset_sha256": asset_hash, "source_retrieved_at_utc": retrieved_at,
                  "physical_row_ref": expected_ref, "publisher_source_row": image_row,
                  "source_rectangle_xyxy": rectangle, "source_column_rectangles_xyxy": column_rectangles,
                  "source_asset_width": width, "source_asset_height": height,
                  "source_asset_path_reported": row.get("source_asset_path"),
                  "verified_columns": verified, "verification_method": row["verification_method"],
                  "receipt_authentication": "syntax_checked_not_independently_authenticated"}
    return _base(row, source_id=source_id, publisher_source_id=publisher_id, ordinal=ordinal,
                 record_kind="image_transaction", sheet="evidence/image", identity=identity,
                 identity_basis="publisher_image_source_and_visible_row_locator",
                 cells=cells, mapped=mapped, provenance=provenance,
                 usage_role="transaction_evidence_not_closed_trade", temporal_quarantined=True,
                 flags=["MANUAL_SCREENSHOT_TRANSCRIPTION", "DISPLAY_PRECISION_ONLY", "NO_INTRADAY_TIME",
                        "TIMEZONE_UNVERIFIED", "CASH_AMOUNT_NOT_TRADE_PNL", "SIGNED_QUANTITY_NOT_POSITION_SIDE",
                        "OPEN_CLOSE_AND_OPENING_INVENTORY_UNKNOWN"])


def _journal(row: dict, source_id: str, ordinal: int) -> dict:
    if row.get("record_type") != JOURNAL_RECORD_KIND:
        raise DataError("EVIDENCE_JOURNAL_SCHEMA_UNSUPPORTED")
    record_id = _identifier(row.get("record_id"), "EVIDENCE_RECORD_ID_INVALID")
    source_url = _url(row.get("source_url"))
    post_id = urlsplit(source_url).path.rstrip("/").rsplit("/", 1)[-1]
    if not post_id or not (record_id == post_id or record_id.endswith("_" + post_id)):
        raise DataError("EVIDENCE_PUBLISHER_POST_ID_MISMATCH")
    source_hash, page_hash = _digest(row.get("source_sha256")), _digest(row.get("profile_page_sha256"))
    page_url = _url(row.get("profile_page_url"))
    _text(row.get("publisher_profile"), "EVIDENCE_PUBLISHER_PROFILE_INVALID")
    _null_fields(row, ("market_entry_timestamp", "market_exit_timestamp", "timezone", "order_id",
                       "execution_fills", "stop_price", "decision_reason"))
    if row.get("independently_broker_authenticated") is not False:
        raise DataError("EVIDENCE_UNSUPPORTED_BROKER_AUTHENTICATION_CLAIM")
    for field_name in ("entry_price_display", "exit_price_display", "position_size_display", "pnl_display_usd_rounded"):
        decimal_text(row.get(field_name), required=True, positive=field_name == "position_size_display")
    _date_pair(row.get("entry_date_raw"), row.get("entry_date"))
    _date_pair(row.get("exit_date_raw"), row.get("exit_date"))
    _text(row.get("ticker"), "EVIDENCE_TICKER_INVALID")
    _text(row.get("direction_raw"), "EVIDENCE_DIRECTION_INVALID")
    _text(row.get("broker_label"), "EVIDENCE_BROKER_LABEL_INVALID")
    # Only the two explicitly observed display labels are supported. They are
    # preserved as publisher labels, not converted to order actions.
    if row["direction_raw"] not in {"Short Stock", "Long Stock"}:
        raise DataError("EVIDENCE_JOURNAL_DIRECTION_UNSUPPORTED")
    if not isinstance(row.get("publisher_verification_badge"), bool):
        raise DataError("EVIDENCE_BADGE_SCHEMA_INVALID")
    _text(row.get("published_timestamp_raw"), "EVIDENCE_PUBLICATION_TIME_INVALID", limit=100)
    currency_marker = row.get("source_currency_marker")
    if currency_marker is not None:
        _text(currency_marker, "EVIDENCE_CURRENCY_MARKER_INVALID", limit=20)
    request_retrieved_at = row.get("source_request_retrieved_at_utc")
    if request_retrieved_at is not None:
        _receipt_time(request_retrieved_at)
    batch_date = row.get("batch_date")
    if batch_date is not None:
        _iso_date(batch_date)
    cells = {key: row[key] for key in ("ticker", "direction_raw", "entry_date_raw", "exit_date_raw",
              "entry_price_display", "exit_price_display", "position_size_display", "pnl_display_usd_rounded", "broker_label")}
    mapped = {key: row.get(key) for key in ("entry_date", "exit_date", "publisher_profile",
              "publisher_verification_badge", "aggregation_of_scaling_fills", "ai_training_rights")}
    # The collector's legacy field name and a dollar display marker do not
    # independently authenticate an ISO currency. Preserve the reported number
    # while leaving normalized PNL currency unresolved.
    mapped.update(pnl_currency=None, source_currency_marker=currency_marker)
    flags = ["PUBLISHER_CLOSED_TRADE_SUMMARY_NOT_EXECUTION_FILLS", "DISPLAY_PRICES_MAY_AGGREGATE_FILLS",
             "PUBLICATION_TIME_NOT_MARKET_ENTRY_TIME", "NO_INTRADAY_TIME", "TIMEZONE_UNVERIFIED",
             "STOP_AND_CONTEMPORANEOUS_DECISION_UNKNOWN", "PUBLISHER_BADGE_NOT_INDEPENDENT_BROKER_AUTHENTICATION",
             "PNL_CURRENCY_NOT_AUTHENTICATED"]
    if row["exit_date"] < row["entry_date"]:
        flags.append("REPORTED_EXIT_DATE_BEFORE_ENTRY_DATE")
    elif row["exit_date"] > row["entry_date"]:
        flags.append("REPORTED_OVERNIGHT_NOT_CLASSIFIED_AS_SCALPING")
    provenance = {"source_url": source_url, "source_sha256": source_hash,
                  "profile_page_url": page_url, "profile_page_sha256": page_hash,
                  "publisher_post_id": post_id, "published_timestamp_raw": row["published_timestamp_raw"],
                  "source_request_retrieved_at_utc": request_retrieved_at, "batch_date": batch_date,
                  "receipt_authentication": "syntax_checked_not_independently_authenticated"}
    return _base(row, source_id=source_id, publisher_source_id=record_id, ordinal=ordinal,
                 record_kind="publisher_closed_trade_summary", sheet="evidence/journal", identity=record_id,
                 identity_basis="publisher_post_id", cells=cells, mapped=mapped, provenance=provenance,
                 usage_role="publisher_summary_not_execution_fills", flags=flags, temporal_quarantined=True)


def _teaching(row: dict, source_id: str, ordinal: int) -> dict:
    card_id = _identifier(row.get("id"), "EVIDENCE_CARD_ID_INVALID")
    publisher_id = _identifier(row.get("source_id"), "EVIDENCE_SOURCE_ID_INVALID")
    _text(row.get("class"), "EVIDENCE_CARD_CLASS_MISSING", limit=1000)
    # No card-specific rule is inferred. The source text and numeric settings
    # remain teaching metadata, including unresolved and contradictory rules.
    cells = {key: value for key, value in row.items() if key not in {"id", "source_id", "trader"}}
    return _base(row, source_id=source_id, publisher_source_id=publisher_id, ordinal=ordinal,
                 record_kind="strategy_card", sheet="evidence/teaching", identity=card_id,
                 identity_basis="strategy_card_id", cells=cells, mapped={"class": row["class"]},
                 provenance={"source_catalog_id": publisher_id, "strategy_card_id": card_id,
                             "source_url": None, "source_receipt_sha256": None,
                             "receipt_authentication": "source_catalog_reference_only"},
                 usage_role="education_not_trade", temporal_quarantined=False,
                 flags=["EDUCATION_NOT_OBSERVED_TRADE", "DISCRETIONARY_RULES_NOT_VALIDATED",
                        "TEACHING_TIME_NOT_EXECUTION_TIME", "STRATEGY_LOG_MAPPING_UNVERIFIED"])


def normalize_evidence(raw: bytes, *, kind: str, source_id: str) -> list[dict]:
    """Normalize an acquired artifact without network, disk or trading actions.

    ``source_id`` is the caller's explicit batch/source namespace. Publisher IDs
    remain separate. JSONL line ordinals (including blank lines) are physical
    provenance; they do not affect stable publisher identities or semantic hashes.
    """
    if kind not in KINDS:
        raise DataError("EVIDENCE_KIND_NOT_ALLOWED")
    source_id = _identifier(source_id, "EVIDENCE_SOURCE_ID_INVALID")
    if not isinstance(raw, bytes):
        raise DataError("EVIDENCE_INPUT_BYTES_REQUIRED")
    if len(raw) > MAX_BYTES:
        raise DataError("INPUT_TOO_LARGE")
    if kind == "strategy_cards":
        document = load_json(raw)
        if (not isinstance(document, dict) or document.get("schema_version") != "1.0" or
                document.get("training_ready") is not False or not isinstance(document.get("cards"), list)):
            raise DataError("EVIDENCE_CARD_SCHEMA_UNSUPPORTED")
        rows = list(enumerate(document["cards"], 1))
        adapter = _teaching
    else:
        rows = [(ordinal, load_json(line)) for ordinal, line in enumerate(raw.splitlines(), 1) if line.strip()]
        adapter = _image if kind == "image_transactions" else _journal
    if not rows:
        raise DataError("EVIDENCE_EMPTY_ARTIFACT")
    if len(rows) > MAX_ROWS:
        raise DataError("TOO_MANY_ROWS")
    output = []
    for ordinal, row in rows:
        if not isinstance(row, dict):
            raise DataError("EVIDENCE_ROW_OBJECT_REQUIRED")
        output.append(adapter(row, source_id, ordinal))
    return output
