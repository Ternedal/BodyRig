from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoidentity_sweep import (
    PhotoIdentitySweepError,
    _read_baseline_source_manifest,
)


def _write_manifest(path: Path, *, version: object) -> bytes:
    payload = {
        "format": "bodyrig-stash-source-manifest",
        "version": version,
        "performer": {"id": "performer-530"},
        "sources": [],
    }
    raw = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def test_photoidentity_sweep_rejects_boolean_v1_baseline_manifest(tmp_path: Path) -> None:
    path = tmp_path / "bodyrig-stash-source-manifest.json"
    _write_manifest(path, version=True)

    with pytest.raises(PhotoIdentitySweepError, match="format/version is invalid"):
        _read_baseline_source_manifest(path, "performer-530")


def test_photoidentity_sweep_accepts_numeric_float_v1_and_preserves_exact_byte_sha(tmp_path: Path) -> None:
    path = tmp_path / "bodyrig-stash-source-manifest.json"
    raw = _write_manifest(path, version=1.0)

    manifest, observed_sha = _read_baseline_source_manifest(path, "performer-530")

    assert manifest["version"] == 1.0
    assert not isinstance(manifest["version"], bool)
    assert manifest["performer"]["id"] == "performer-530"
    assert observed_sha == hashlib.sha256(raw).hexdigest()
    assert path.read_bytes() == raw
