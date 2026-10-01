"""Bounded, unauthenticated acquisition of one explicitly licensed WSE file.

Only the fixed depositor URL is exposed. This module does not follow redirects,
discover credentials, use proxies, resume partial files, or retry requests. Raw
availability and checksum verification do not establish trading readiness.
"""
from __future__ import annotations

import hashlib
import http.client
import os
import re
import socket
import ssl
import stat
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import (HTTPSHandler, HTTPRedirectHandler, ProxyHandler,
                            Request, build_opener)

from trading_intelligence.common import DataError, json_bytes
from . import __version__
from .market import _atomic_write, _now

MAX_ACQUISITION_BYTES = 192 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
SOCKET_TIMEOUT_SECONDS = 20
WSE_DATA_URL = ("https://data.mendeley.com/public-files/datasets/3g4mhdp899/"
                "files/63e3f3ab-f562-4389-a740-357446266a6c/file_downloaded")
WSE_EXPECTED_BYTES = 152_759_953
WSE_EXPECTED_SHA256 = "3c418a55a492ebe2e39c8513cd7fc7e3e6827dc1a176af09fdcaad9f3485bae6"


@dataclass(frozen=True)
class _SourceContract:
    source_url: str = WSE_DATA_URL
    expected_bytes: int = WSE_EXPECTED_BYTES
    expected_sha256: str = WSE_EXPECTED_SHA256
    source_id: str = "wselob_2017_pekao_v1"
    instrument: str = "PEKAO"
    filename: str = "PEKAO_lob_2017_zlib.h5"
    license: str = "CC-BY-4.0"
    license_url: str = "https://creativecommons.org/licenses/by/4.0/legalcode.en"
    source_record_url: str = "https://data.mendeley.com/datasets/3g4mhdp899/1"
    checksum_evidence_url: str = (
        "https://github.com/DeepCogNeural/microstructure-lab/blob/"
        "9ca395e591492e6c14cc52c4ac7f9599b1c978e8/configs/wselob_sources_v1.json")
    attribution: str = (
        "Marszałek, Adam (2023), WSELOB-2017, Mendeley Data V1, "
        "DOI 10.17632/3g4mhdp899.1; CC BY 4.0. "
        "Raw bytes unmodified; as-is, no warranty or endorsement.")
    synthetic_fixture: bool = False


_WSE_CONTRACT = _SourceContract()
WSE_SOURCE_CONTRACT_SHA256 = hashlib.sha256(json_bytes(asdict(_WSE_CONTRACT))).hexdigest()


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_source(url: str):
    """GET with system certificate verification and no alternate access path."""
    if url != WSE_DATA_URL:
        raise DataError("ACQUIRE_FIXED_SOURCE_REQUIRED")
    context = ssl.create_default_context()
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise DataError("ACQUIRE_TLS_VERIFICATION_REQUIRED")
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), _RejectRedirects())
    opener.addheaders = []
    request = Request(url, method="GET", headers={
        "Accept": "application/octet-stream", "Accept-Encoding": "identity",
        "User-Agent": "trading-intelligence-public-wse-acquisition/" + __version__,
    })
    return opener.open(request, timeout=SOCKET_TIMEOUT_SECONDS)


def _validate_contract(contract: _SourceContract) -> None:
    if contract.source_url != WSE_DATA_URL:
        raise DataError("ACQUIRE_FIXED_SOURCE_REQUIRED")
    if (type(contract.expected_bytes) is not int
            or not 0 < contract.expected_bytes <= MAX_ACQUISITION_BYTES):
        raise DataError("ACQUIRE_EXPECTED_SIZE_INVALID")
    if (not isinstance(contract.expected_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", contract.expected_sha256)):
        raise DataError("ACQUIRE_EXPECTED_HASH_INVALID")


def _file_receipt(path: Path, *, expected_bytes: int | None = None,
                  expected_sha256: str | None = None) -> tuple[int, str]:
    """Hash a regular bounded file without following a changed symlink."""
    preliminary = path.lstat()
    if not stat.S_ISREG(preliminary.st_mode):
        raise DataError("ACQUIRE_RAW_ARCHIVE_CONFLICT")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_ACQUISITION_BYTES:
            raise DataError("ACQUIRE_RAW_ARCHIVE_CONFLICT")
        digest, count = hashlib.sha256(), 0
        while True:
            chunk = source.read(CHUNK_BYTES)
            if not chunk:
                break
            count += len(chunk)
            if count > MAX_ACQUISITION_BYTES:
                raise DataError("ACQUIRE_RAW_ARCHIVE_CONFLICT")
            digest.update(chunk)
        after = os.fstat(source.fileno())
        current = path.lstat()
        if ((before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)
                or before.st_size != count or after.st_size != count
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns
                or before.st_mtime_ns != current.st_mtime_ns
                or before.st_ctime_ns != current.st_ctime_ns
                or stat.S_ISLNK(current.st_mode)):
            raise DataError("ACQUIRE_RAW_ARCHIVE_CONFLICT")
    actual_sha256 = digest.hexdigest()
    if (expected_bytes is not None and count != expected_bytes
            or expected_sha256 is not None and actual_sha256 != expected_sha256):
        raise DataError("ACQUIRE_RAW_ARCHIVE_CONFLICT")
    return count, actual_sha256


def _response_contract(response, contract: _SourceContract) -> None:
    if response.geturl() != contract.source_url:
        raise DataError("ACQUIRE_REDIRECT_REJECTED")
    if response.status != 200:
        raise DataError("ACQUIRE_HTTP_STATUS_INVALID")
    headers = response.headers
    lengths = headers.get_all("Content-Length") or []
    if len(lengths) > 1:
        raise DataError("ACQUIRE_CONTENT_LENGTH_INVALID")
    if lengths:
        value = lengths[0].strip()
        if len(value) > 12 or not value.isascii() or not value.isdigit():
            raise DataError("ACQUIRE_CONTENT_LENGTH_INVALID")
        declared = int(value)
        if declared > MAX_ACQUISITION_BYTES:
            raise DataError("ACQUIRE_RESPONSE_TOO_LARGE")
        if declared != contract.expected_bytes:
            raise DataError("ACQUIRE_CONTENT_LENGTH_MISMATCH")
    encoding = headers.get("Content-Encoding", "identity").strip().lower()
    if encoding not in ("", "identity"):
        raise DataError("ACQUIRE_CONTENT_ENCODING_UNSUPPORTED")
    if lengths and headers.get("Transfer-Encoding"):
        raise DataError("ACQUIRE_TRANSFER_ENCODING_CONFLICT")


def _stream_response(response, output, contract: _SourceContract, manifest: dict) -> str:
    digest = hashlib.sha256()

    def retain(chunk: bytes) -> None:
        if type(chunk) is not bytes:
            raise DataError("ACQUIRE_STREAM_INVALID")
        manifest["received_bytes"] += len(chunk)
        remaining = MAX_ACQUISITION_BYTES - manifest["stored_partial_bytes"]
        kept = chunk[:remaining]
        view = memoryview(kept)
        while view:
            try:
                count = output.write(view)
            except OSError:
                raise DataError("ACQUIRE_LOCAL_WRITE_FAILED") from None
            if not count:
                raise DataError("ACQUIRE_LOCAL_WRITE_FAILED")
            manifest["stored_partial_bytes"] += count
            view = view[count:]
        digest.update(kept)
        if len(chunk) > remaining:
            manifest["discarded_received_bytes"] += len(chunk) - remaining
            raise DataError("ACQUIRE_RESPONSE_TOO_LARGE")
        if manifest["received_bytes"] > contract.expected_bytes:
            raise DataError("ACQUIRE_DOWNLOADED_SIZE_MISMATCH")

    while True:
        requested = min(CHUNK_BYTES, MAX_ACQUISITION_BYTES - manifest["received_bytes"] + 1)
        try:
            chunk = response.read(requested)
        except http.client.IncompleteRead as error:
            # These are actual received bytes even though read() did not return.
            retain(error.partial)
            raise DataError("ACQUIRE_RESPONSE_INCOMPLETE") from None
        if type(chunk) is not bytes or len(chunk) > requested:
            raise DataError("ACQUIRE_STREAM_INVALID")
        if not chunk:
            manifest["response_eof_observed"] = True
            break
        retain(chunk)
    if manifest["received_bytes"] != contract.expected_bytes:
        raise DataError("ACQUIRE_DOWNLOADED_SIZE_MISMATCH")
    if digest.hexdigest() != contract.expected_sha256:
        raise DataError("ACQUIRE_DOWNLOADED_HASH_MISMATCH")
    try:
        output.flush()
        os.fsync(output.fileno())
    except OSError:
        raise DataError("ACQUIRE_LOCAL_SYNC_FAILED") from None
    return digest.hexdigest()


def _install_raw(partial: Path, target: Path, contract: _SourceContract) -> None:
    try:
        os.link(partial, target)
    except FileExistsError:
        _file_receipt(target, expected_bytes=contract.expected_bytes,
                      expected_sha256=contract.expected_sha256)
    target.chmod(0o400)
    partial.unlink()


def _acquire(out: Path, contract: _SourceContract, open_source: Callable) -> dict:
    """Private injectable contract/transport for entirely synthetic offline tests."""
    out = Path(out)
    run_id = uuid.uuid4().hex
    run_dir = out / "acquisition-runs" / run_id
    raw_dir = out / "raw" / "wse"
    for directory in (out, out / "acquisition-runs", run_dir, out / "raw", raw_dir):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    partial = run_dir / "download.partial"
    manifest_path = run_dir / "manifest.json"
    contract_bytes = json_bytes(asdict(contract))
    manifest = {
        "schema_version": 1, "software_version": __version__, "run_id": run_id,
        "record_kind": "public_order_history_acquisition", "status": "running",
        "started_at_utc": _now(), "completed_at_utc": None,
        "manifest_path": str(manifest_path), "source_contract": asdict(contract),
        "source_contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "source_contract_path": str(run_dir / "source_contract.json"),
        "source_url": contract.source_url, "source_id": contract.source_id,
        "license": contract.license, "license_url": contract.license_url,
        "attribution": contract.attribution,
        "expected_bytes": contract.expected_bytes, "expected_sha256": contract.expected_sha256,
        "max_acquisition_bytes": MAX_ACQUISITION_BYTES, "read_chunk_bytes": CHUNK_BYTES,
        "timeout_seconds": SOCKET_TIMEOUT_SECONDS,
        "timeout_basis": "per_blocking_socket_operation_not_total_download_deadline",
        "redirects_allowed": False, "authentication_used": False, "proxy_used": False,
        "network_attempted": False, "network_request_count": 0,
        "received_bytes": 0, "downloaded_bytes": 0, "stored_partial_bytes": 0,
        "received_bytes_basis": "body_bytes_yielded_or_retained_from_IncompleteRead_not_total_wire_bytes",
        "discarded_received_bytes": 0, "response_eof_observed": False,
        "partial_path": None, "partial_sha256": None, "partial_hash_basis": "stored_partial_file",
        "data_path": None, "data_bytes": None, "data_sha256": None,
        "verified_data_sha256": None, "acquisition_action": None,
        "actual_market_binary_downloaded": False,
        "synthetic_fixture": contract.synthetic_fixture,
        "tls_verification_required": True, "transport_tls_verified": False,
        "training_ready": False, "full_history_verified": False,
        "broker_verified": False, "trading_enabled": False, "model_trained": False,
        "errors": [], "phase": "contract",
    }
    _atomic_write(manifest_path, json_bytes(manifest))
    try:
        _atomic_write(run_dir / "source_contract.json", contract_bytes)
        _validate_contract(contract)
        target = raw_dir / (contract.expected_sha256 + ".h5")
        manifest["phase"] = "archive_check"
        if target.exists() or target.is_symlink():
            count, digest = _file_receipt(target, expected_bytes=contract.expected_bytes,
                                          expected_sha256=contract.expected_sha256)
            target.chmod(0o400)
            action = "verified_existing_archive"
        else:
            manifest["phase"] = "open_source"
            with partial.open("xb", buffering=0) as output:
                manifest["partial_path"] = str(partial)
                manifest["network_attempted"] = True
                manifest["network_request_count"] = 1
                with closing(open_source(contract.source_url)) as response:
                    _response_contract(response, contract)
                    manifest["phase"] = "response_body"
                    _stream_response(response, output, contract, manifest)
            manifest["phase"] = "archive_publish"
            count, digest = _file_receipt(partial, expected_bytes=contract.expected_bytes,
                                          expected_sha256=contract.expected_sha256)
            _install_raw(partial, target, contract)
            manifest["partial_path"] = None
            action = "downloaded_and_verified"
        manifest.update(
            status="completed", phase="completed", acquisition_action=action,
            data_path=str(target), data_bytes=count, data_sha256=digest,
            verified_data_sha256=digest,
            transport_tls_verified=manifest["network_attempted"] and not contract.synthetic_fixture,
            actual_market_binary_downloaded=manifest["network_attempted"] and not contract.synthetic_fixture,
        )
    except HTTPError as error:
        code = "ACQUIRE_REDIRECT_REJECTED" if 300 <= error.code < 400 else f"ACQUIRE_HTTP_{error.code}"
        manifest.update(status="failed", errors=[code])
        try:
            error.close()
        except OSError:
            pass
    except http.client.HTTPException:
        manifest.update(status="failed", errors=["ACQUIRE_HTTP_PROTOCOL_ERROR"])
    except (TimeoutError, socket.timeout):
        manifest.update(status="failed", errors=["ACQUIRE_TIMEOUT"])
    except ssl.SSLError:
        manifest.update(status="failed", errors=["ACQUIRE_TLS_FAILED"])
    except URLError:
        manifest.update(status="failed", errors=["ACQUIRE_NETWORK_BLOCKED_OR_UNAVAILABLE"])
    except DataError as error:
        manifest.update(status="failed", errors=[str(error)])
    except KeyboardInterrupt:
        manifest.update(status="failed", errors=["ACQUIRE_INTERRUPTED"])
    except OSError:
        code = ("ACQUIRE_NETWORK_BLOCKED_OR_UNAVAILABLE"
                if manifest["phase"] in ("open_source", "response_body")
                else "ACQUIRE_LOCAL_IO_ERROR")
        manifest.update(status="failed", errors=[code])
    except Exception:
        manifest.update(status="failed", errors=["ACQUIRE_INTERNAL_ERROR"])
    finally:
        if partial.exists():
            try:
                count, digest = _file_receipt(partial)
                partial.chmod(0o400)
                manifest.update(partial_path=str(partial), stored_partial_bytes=count,
                                partial_sha256=digest)
            except (OSError, DataError):
                manifest["partial_sha256"] = None
                manifest["errors"].append("ACQUIRE_PARTIAL_RECEIPT_UNAVAILABLE")
        manifest["downloaded_bytes"] = manifest["received_bytes"]
        manifest["completed_at_utc"] = _now()
        _atomic_write(manifest_path, json_bytes(manifest))
    return manifest


def acquire_wse(out: Path) -> dict:
    """Acquire only the fixed public PEKAO file, or report why it could not finish.

    A completed receipt has verified ``data_bytes``/``data_sha256``. On failure,
    only a bounded stored-prefix hash is reported, and ``data_path`` stays null.
    Existing complete archives are independently rehashed; partials never resume.
    """
    return _acquire(out, _WSE_CONTRACT, _open_source)
