"""Filename sanitization and upload destination rules for node-local files."""

from __future__ import annotations

import re
from pathlib import Path

ALLOWED_UPLOAD_SUFFIXES = {".csv", ".tsv", ".parquet", ".pq", ".json", ".jsonl", ".ndjson"}
DEFAULT_UPLOAD_MAX_BYTES = 100 * 1024 * 1024
UPLOADS_DIRNAME = "uploads"


class UploadRejected(ValueError):
    """Invalid upload filename, type, size, or destination."""

    def __init__(self, message: str, receipt: object | None = None) -> None:
        self.receipt = receipt
        super().__init__(message)


def enforce_upload_size(total_bytes: int, max_bytes: int) -> None:
    if total_bytes > max_bytes:
        raise UploadRejected(f"file exceeds max upload size ({max_bytes} bytes)")


async def read_upload_bytes(file, max_bytes: int, chunk_size: int = 1024 * 1024) -> bytes:
    """Read an UploadFile-like object, rejecting once the cap is exceeded."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        enforce_upload_size(total, max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


def sanitize_upload_filename(filename: str | None) -> str:
    """Return a safe basename. Reject absolute paths, traversal, and bad suffixes."""
    if filename is None or not str(filename).strip():
        raise UploadRejected("filename is required")
    raw = str(filename).strip().replace("\\", "/")
    if raw.startswith("/") or raw.startswith("~"):
        raise UploadRejected("absolute paths are not allowed")
    if len(raw) >= 2 and raw[1] == ":":
        raise UploadRejected("absolute paths are not allowed")
    parts = Path(raw).parts
    if ".." in parts:
        raise UploadRejected("path traversal is not allowed")
    if len(parts) != 1:
        raise UploadRejected("path separators are not allowed")
    name = parts[0]
    if name in {".", ".."} or name.startswith("."):
        raise UploadRejected("invalid filename")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    cleaned = cleaned.strip("._")
    if not cleaned or cleaned in {".", ".."}:
        raise UploadRejected("invalid filename")
    suffix = Path(cleaned).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise UploadRejected(f"unsupported extension: {suffix or '(none)'}")
    stem = Path(cleaned).stem
    if not stem:
        raise UploadRejected("invalid filename")
    return f"{stem}{suffix}"


def unique_destination(directory: Path, filename: str) -> Path:
    dest = directory / filename
    if not dest.exists():
        return dest
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    index = 2
    while True:
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def resolve_uploads_dir(root: Path | str, uploads_path: Path | str | None = None) -> Path:
    """Destination directory. Default is ``<root>/uploads``. Must stay under root."""
    base = Path(root).resolve()
    if uploads_path is None:
        dest = (base / UPLOADS_DIRNAME).resolve()
    else:
        extra = Path(uploads_path)
        dest = extra.resolve() if extra.is_absolute() else (base / extra).resolve()
    try:
        dest.relative_to(base)
    except ValueError as exc:
        raise UploadRejected("uploads path must stay under the local_files root") from exc
    return dest
