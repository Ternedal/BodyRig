"""Shared SHA-256 helpers.

Every module used to carry its own copy of these three functions (#1386,
recommendation B: 351 private definitions in 226 textual variants, all
producing the same digests). The copies differed only in local names, chunk
size and variable names, never in output. This module is the single
implementation; the modules keep their private names as one-line delegates so
call sites, tests and monkeypatches are unchanged.

Rules that keep this module safe to import from anywhere:

- standard library only, no bodyrig imports, no I/O at import time;
- hashing never swallows errors: an unreadable file raises the OSError the
  caller's fail-closed wrapper expects, exactly as the old copies did;
- the canonical JSON digest is byte-for-byte the historical encoding
  (sort_keys, compact separators, ensure_ascii=False, allow_nan=False).

Modules that run standalone inside external environments (SiTH/ExAvatar
bridges, WSL-side scripts) deliberately keep their own copies, because
``bodyrig`` is not importable there.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DEFAULT_CHUNK_SIZE = 1024 * 1024


def sha256_bytes(value: bytes | bytearray | memoryview) -> str:
    """Lowercase hex SHA-256 of an in-memory buffer."""
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Lowercase hex SHA-256 of a file, streamed in ``chunk_size`` blocks.

    Raises whatever ``open``/``read`` raise (OSError family); callers wrap it
    in their own module error when they want to fail closed with context.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Mapping[str, Any] | Any, *, omit: str | None = None) -> bytes:
    """The historical canonical encoding used for every receipt/evidence digest."""
    payload = value
    if omit is not None:
        payload = {key: item for key, item in value.items() if key != omit}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical_json_sha256(value: Mapping[str, Any] | Any, *, omit: str | None = None) -> str:
    """Lowercase hex SHA-256 of :func:`canonical_json_bytes`."""
    return hashlib.sha256(canonical_json_bytes(value, omit=omit)).hexdigest()
