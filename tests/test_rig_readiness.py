from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.rig_readiness import RigReadinessError, load_readiness, validate_readiness

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
REVISION = "d" * 40
SESSION_ID = "12345678-1234-5678-1234-567812345678"


def _report() -> dict:
    return {
        "format": "bodyrig-rig-readiness",
        "version": 1,
        "session_id": SESSION_ID,
        "bodyrig_revision": REVISION,
        "observed_utc": "2026-08-24T14:00:00Z",
        "rig_setup_report": r"C:\BodyRig\bodyrig-rig-setup.json",
        "rig_setup_sha256": HASH_A,
        "checks": {
            "master_setup": True,
            "recovery": True,
            "sith_openpose": True,
            "openpose_binary": True,
            "openpose_models": True,
            "diffusion_model": True,
            "stash": True,
            "stash_performer_read": True,
        },
        "environment": {
            "stash_version": "v0.30.1",
            "openpose_sha256": HASH_A,
            "openpose_byte_count": 10,
            "openpose_models_sha256": HASH_B,
            "openpose_models_file_count": 2,
            "openpose_models_byte_count": 20,
            "diffusion_model_sha256": HASH_C,
            "diffusion_model_file_count": 3,
            "diffusion_model_byte_count": 30,
        },
        "ready": True,
    }


def test_readiness_accepts_exact_all_green_evidence() -> None:
    assert validate_readiness(_report()) == _report()


def test_readiness_rejects_missing_performer_read_and_extra_fields() -> None:
    missing = _report()
    del missing["checks"]["stash_performer_read"]
    with pytest.raises(RigReadinessError, match="checks must match"):
        validate_readiness(missing)

    extra = _report()
    extra["stash_url"] = "http://secret.invalid"
    with pytest.raises(RigReadinessError, match="fields must match"):
        validate_readiness(extra)


def test_readiness_rejects_false_checks_bad_revision_and_boolean_counts() -> None:
    false_check = _report()
    false_check["checks"]["stash_performer_read"] = False
    with pytest.raises(RigReadinessError, match="must be true"):
        validate_readiness(false_check)

    bad_revision = _report()
    bad_revision["bodyrig_revision"] = "D" * 40
    with pytest.raises(RigReadinessError, match="Git SHA"):
        validate_readiness(bad_revision)

    bool_count = _report()
    bool_count["environment"]["openpose_byte_count"] = True
    with pytest.raises(RigReadinessError, match="positive integer"):
        validate_readiness(bool_count)


def test_readiness_rejects_naive_timestamp_and_invalid_session_id() -> None:
    naive = _report()
    naive["observed_utc"] = "2026-08-24T14:00:00"
    with pytest.raises(RigReadinessError, match="timezone"):
        validate_readiness(naive)

    bad_session = _report()
    bad_session["session_id"] = "not-a-uuid"
    with pytest.raises(RigReadinessError, match="UUID"):
        validate_readiness(bad_session)


def test_load_readiness_rejects_nonfinite_json(tmp_path: Path) -> None:
    report = tmp_path / "readiness.json"
    report.write_text(json.dumps(_report()).replace("10", "NaN", 1), encoding="utf-8")
    with pytest.raises(RigReadinessError, match="invalid JSON"):
        load_readiness(report)
