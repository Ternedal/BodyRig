"""bodyrig.hashing reproduces the historical private helpers byte for byte.

The three functions replace 99 module-private copies (#1386, recommendation
B, slice 1). The copies were pure, so the oracle is the historical code
itself: hashlib on the whole buffer, the 1 MiB / 8 MiB streaming loops, and
the canonical ``json.dumps`` encoding every receipt digest used.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from bodyrig import hashing


def _historical_stream(path: Path, block: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(block), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _historical_digest(value, *, omit=None) -> str:
    payload = value if omit is None else {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("size", [0, 1, 1024 * 1024 - 1, 1024 * 1024, 1024 * 1024 + 1, 3 * 1024 * 1024 + 7])
def test_sha256_file_matches_whole_buffer_and_both_historical_block_sizes(tmp_path: Path, size: int) -> None:
    path = tmp_path / "blob.bin"
    payload = (b"\x00\x01\x02\xfe\xff" * (size // 5 + 1))[:size]
    path.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    assert hashing.sha256_file(path) == expected
    assert hashing.sha256_file(str(path)) == expected
    assert hashing.sha256_file(path, chunk_size=8 * 1024 * 1024) == expected
    assert hashing.sha256_file(path, chunk_size=7) == expected
    assert _historical_stream(path, 1024 * 1024) == expected
    assert _historical_stream(path, 8 * 1024 * 1024) == expected
    assert hashing.sha256_bytes(payload) == expected
    assert hashing.sha256_bytes(bytearray(payload)) == expected
    assert hashing.sha256_bytes(memoryview(payload)) == expected


def test_sha256_file_propagates_os_errors_and_rejects_bad_chunk_size(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        hashing.sha256_file(tmp_path / "absent.bin")
    with pytest.raises(IsADirectoryError):
        hashing.sha256_file(tmp_path)
    path = tmp_path / "x.bin"
    path.write_bytes(b"x")
    for bad in (0, -1):
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            hashing.sha256_file(path, chunk_size=bad)


def test_canonical_json_digest_matches_historical_encoding() -> None:
    value = {"zeta": 1, "alpha": {"y": [1, 2.5, "ø", None, True], "x": "æå"}, "omit_me": "secret"}
    assert hashing.canonical_json_sha256(value) == _historical_digest(value)
    assert hashing.canonical_json_sha256(value, omit="omit_me") == _historical_digest(value, omit="omit_me")
    assert hashing.canonical_json_sha256(value, omit="omit_me") == _historical_digest({"zeta": 1, "alpha": value["alpha"]})
    # Key order never matters; a missing omit key is a no-op, like the comprehension.
    reordered = {"omit_me": "secret", "alpha": value["alpha"], "zeta": 1}
    assert hashing.canonical_json_sha256(reordered) == hashing.canonical_json_sha256(value)
    assert hashing.canonical_json_sha256(value, omit="absent") == hashing.canonical_json_sha256(value)
    # ensure_ascii=False keeps non-ASCII bytes; separators are compact.
    raw = hashing.canonical_json_bytes({"k": "æ"})
    assert raw == '{"k":"æ"}'.encode("utf-8")
    # allow_nan=False fails closed exactly like the historical copies.
    with pytest.raises(ValueError):
        hashing.canonical_json_sha256({"k": math.nan})
    with pytest.raises(ValueError):
        hashing.canonical_json_sha256({"k": math.inf})


def test_hashing_module_is_standard_library_only() -> None:
    import ast

    source = Path(hashing.__file__).read_text(encoding="utf-8")
    modules = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert (node.level or 0) == 0
            modules.add((node.module or "").split(".")[0])
    assert modules == {"__future__", "hashlib", "json", "collections", "pathlib", "typing"}
