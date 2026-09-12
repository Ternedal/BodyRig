from __future__ import annotations

import json

import pytest

from bodyrig.proof import ProofError, load_recovery_proof, validate_recovery_proof


def _proof(*, version: object = 1) -> dict[str, object]:
    return {
        "format": "bodyrig-recovery-proof",
        "version": version,
        "source_count": 1,
        "adapter": "fixture",
        "revision": "fixture-v1",
        "track_id": "person-1",
        "observed_frames": 2,
        "bodyprint": {
            "format": "modelrig-bodyprint",
            "version": 1,
            "shape": {"height_scale": 1.0},
        },
    }


def test_recovery_proof_rejects_boolean_version_but_accepts_numeric_v1() -> None:
    with pytest.raises(ProofError, match="unsupported recovery proof format/version"):
        validate_recovery_proof(_proof(version=True))

    validated = validate_recovery_proof(_proof(version=1.0))
    assert validated["version"] == 1.0


def test_load_recovery_proof_rejects_boolean_version_but_accepts_numeric_v1(tmp_path) -> None:
    path = tmp_path / "recovery-proof.json"
    path.write_text(json.dumps(_proof(version=True)), encoding="utf-8")
    with pytest.raises(ProofError, match="unsupported recovery proof format/version"):
        load_recovery_proof(path)

    path.write_text(json.dumps(_proof(version=1.0)), encoding="utf-8")
    loaded = load_recovery_proof(path)
    assert loaded["version"] == 1.0
