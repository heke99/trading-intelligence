"""Bounded public acquisition of reviewed publisher spreadsheets, never training.

The caller supplies the already reviewed catalog. URLs are not discovered or
constructed here; every downloaded byte is checked with the read-only adapter.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener
from uuid import uuid4

from .common import DataError, MAX_BYTES, json_bytes, read_limited, sha256
from .publisher_pipeline import _catalog, source_identifier
from .trader_xlsx import _validate_source, normalize_workbook

_EXPORT_PATH = re.compile(r"/spreadsheets/d/[A-Za-z0-9_-]{20,120}/export")
# Only Google's public spreadsheet-export redirect host family is permitted.
_EXPORT_REDIRECT_HOST = re.compile(r"doc-[a-z0-9-]+-sheets\.googleusercontent\.com")
_TIMEOUT = 20


def _export_url(value: object) -> str:
    if not isinstance(value, str):
        raise DataError("TRADER_SOURCE_URL_INVALID")
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.netloc == "docs.google.com"
                 and _EXPORT_PATH.fullmatch(parsed.path) and parsed.query == "format=xlsx"
                 and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise DataError("TRADER_SOURCE_URL_INVALID")
    return value


def _public_destination(value: str) -> None:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.port is not None or parsed.fragment):
            raise DataError("SOURCE_REDIRECT_NOT_PUBLIC_EXPORT")
        if parsed.hostname == "docs.google.com":
            _export_url(value)
            return
        path = unquote(parsed.path)
        if (_EXPORT_REDIRECT_HOST.fullmatch(parsed.hostname or "")
                and path.startswith("/export/") and "\\" not in path
                and not any(part.casefold() in {".", "..", "login", "signin", "servicelogin", "accounts"}
                            for part in path.split("/"))):
            return
    except (ValueError, DataError):
        pass
    raise DataError("SOURCE_REDIRECT_NOT_PUBLIC_EXPORT")


class _PublicExportRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Check before following; a final-response check alone is too late.
        _public_destination(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_transport(url: str, timeout: int):
    # No cookies, authorization, custom headers, proxy overrides or retries.
    return build_opener(_PublicExportRedirects()).open(url, timeout=timeout)


def _read_response(response, expected_url: str) -> bytes:
    status = getattr(response, "status", None)
    if status is None:
        status = response.getcode()
    if status in {401, 403, 429}:
        raise DataError(f"SOURCE_HTTP_{status}")
    if status != 200:
        raise DataError("SOURCE_HTTP_NOT_200")
    _public_destination(response.geturl() or expected_url)
    headers = response.headers
    if "text/html" in headers.get("Content-Type", "").lower():
        raise DataError("SOURCE_RESPONSE_NOT_XLSX")
    length = headers.get("Content-Length")
    if isinstance(length, str) and length.isascii() and length.isdigit():
        if len(length) > 20 or int(length) > MAX_BYTES:
            raise DataError("SOURCE_RESPONSE_TOO_LARGE")
    chunks, size = [], 0
    while True:
        chunk = response.read(min(64 * 1024, MAX_BYTES + 1 - size))
        if not isinstance(chunk, bytes):
            raise DataError("SOURCE_RESPONSE_INVALID")
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_BYTES:
            raise DataError("SOURCE_RESPONSE_TOO_LARGE")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw.startswith(b"PK\x03\x04"):
        raise DataError("SOURCE_RESPONSE_NOT_XLSX")
    return raw


def _failure(error: Exception | KeyboardInterrupt) -> str:
    if isinstance(error, KeyboardInterrupt):
        return "INTERRUPTED"
    if isinstance(error, DataError):
        return str(error)
    if isinstance(error, HTTPError):
        return f"SOURCE_HTTP_{error.code}" if error.code in {401, 403, 429} else "SOURCE_HTTP_ERROR"
    if isinstance(error, TimeoutError):
        return "SOURCE_NETWORK_TIMEOUT"
    if isinstance(error, URLError):
        return "SOURCE_NETWORK_ERROR"
    return "SOURCE_IO_OR_INTERNAL_ERROR"


def _validate_catalog(catalog_path: Path, source_ids: list[str] | None) -> list[dict]:
    sources = _catalog(read_limited(catalog_path))
    if len(sources) > 8:
        raise DataError("TRADER_CATALOG_TOO_MANY_SOURCES")
    filenames = set()
    for source in sources:
        _validate_source(source)
        _export_url(source.get("xlsx_url"))
        if source["local_filename"] in filenames:
            raise DataError("TRADER_SOURCE_FILENAME_DUPLICATE")
        filenames.add(source["local_filename"])
    if source_ids is not None:
        if not isinstance(source_ids, list) or not source_ids:
            raise DataError("TRADER_SOURCE_SELECTION_EMPTY")
        identifiers = [source_identifier(value) for value in source_ids]
        if len(set(identifiers)) != len(identifiers):
            raise DataError("TRADER_SOURCE_SELECTION_DUPLICATE")
        selected = set(identifiers)
        if selected - {source["id"] for source in sources}:
            raise DataError("TRADER_SOURCE_NOT_IN_CATALOG")
        sources = [source for source in sources if source["id"] in selected]
    return sources


def _acquire(source: dict, out_dir: Path, transport) -> dict:
    path = out_dir / source["local_filename"]
    if path.is_symlink():
        raise DataError("SOURCE_FILE_CONFLICT")
    if path.exists():
        raw = read_limited(path)
        metadata = normalize_workbook(path, source)["source_meta"]
        # mtime is neither a retrieval clock nor a publisher's trade timestamp.
        clock, mode = None, "existing_file_revalidated"
    else:
        with transport(source["xlsx_url"], _TIMEOUT) as response:
            raw = _read_response(response, source["xlsx_url"])
        clock = datetime.now(timezone.utc).isoformat()
        mode = "public_http_download"
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=out_dir, prefix=".source-", suffix=".xlsx", delete=False) as staged:
                temporary_path = Path(staged.name)
                staged.write(raw)
                staged.flush()
                os.fsync(staged.fileno())
            metadata = normalize_workbook(temporary_path, source)["source_meta"]
            try:
                # Atomic creation without an overwrite, including competing runs.
                os.link(temporary_path, path)
            except FileExistsError:
                if path.is_symlink() or sha256(read_limited(path)) != sha256(raw):
                    raise DataError("SOURCE_FILE_CONFLICT") from None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    digest = sha256(raw)
    if metadata["raw_sha256"] != digest:
        raise DataError("RAW_HASH_MISMATCH")
    return {"id": source["id"], "source_url": source["xlsx_url"],
            "local_filename": source["local_filename"], "status": "succeeded",
            "sha256": digest, "size_bytes": len(raw), "retrieved_at_utc": clock,
            "acquisition_mode": mode, "semantic_sha256": metadata["semantic_sha256"],
            "source_rows": metadata["row_count"], "broker_fill_verified": False}


def _write_receipt(out_dir: Path, entries: list[dict]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = out_dir / f"download_manifest_{stamp}_{uuid4().hex[:8]}.json"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=out_dir, prefix=".receipt-", delete=False) as staged:
            temporary_path = Path(staged.name)
            staged.write(json_bytes(entries))
            staged.flush()
            os.fsync(staged.fileno())
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return target


def download_trader_sources(catalog_path: Path, out_dir: Path, *,
                            source_ids: list[str] | None = None, transport=None) -> dict:
    """Fetch exact catalog exports or revalidate local originals; fail closed.

    Injected transports take ``(url, timeout)`` and return a context-managed
    urllib-style response. Tests use synthetic bytes only. Any source failure
    stops the batch, preserves prior files, and is recorded in a new receipt.
    """
    out_dir = Path(out_dir)
    entries, errors = [], []
    result = {"status": "failed", "entries": entries, "errors": errors,
              "receipt_path": None, "training_ready": False,
              "full_history_verified": False, "trading_enabled": False}
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        sources = _validate_catalog(Path(catalog_path), source_ids)
        for source in sources:
            if errors:
                entries.append({"id": source["id"], "source_url": source["xlsx_url"],
                                "local_filename": source["local_filename"], "status": "not_attempted",
                                "reason": "NOT_ATTEMPTED_AFTER_FAILURE", "retrieved_at_utc": None})
                continue
            try:
                entries.append(_acquire(source, out_dir, transport or _default_transport))
            except (Exception, KeyboardInterrupt) as error:
                reason = _failure(error)
                errors.append(reason)
                entries.append({"id": source["id"], "source_url": source["xlsx_url"],
                                "local_filename": source["local_filename"], "status": "failed",
                                "reason": reason, "retrieved_at_utc": None})
    except (Exception, KeyboardInterrupt) as error:
        reason = _failure(error)
        errors.append(reason)
        entries.append({"status": "failed", "reason": reason, "retrieved_at_utc": None})
    try:
        result["receipt_path"] = str(_write_receipt(out_dir, entries))
    except Exception:
        errors.append("DOWNLOAD_RECEIPT_WRITE_FAILED")
    result["status"] = "failed" if errors else "completed"
    return result
