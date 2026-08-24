from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.physical_session import (
    PhysicalSessionError,
    mark_fail,
    mark_pass,
    mark_readiness_pass,
    start_session,
    validate_session,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
REVISION = "c" * 40


def _start(report: Path, *, performer_id: str = "123", body_id: str = "performer-123", clean: bool = True):
    return start_session(
        report,
        performer_id=performer_id,
        body_id=body_id,
        bodyrig_revision=REVISION,
        bodyrig_checkout_clean=clean,
        rig_setup_sha256=HASH_A,
    )


def test_physical_session_pass_flow(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    started = _start(report)
    assert started["status"] == "running"
    assert started["stage"] == "initializing"
    assert started["bodyrig_revision"] == REVISION
    assert started["bodyrig_checkout_clean"] is True
    assert started["readiness_sha256"] is None

    ready = mark_readiness_pass(report, readiness_sha256=HASH_B)
    assert ready["stage"] == "clone"
    assert ready["readiness_sha256"] == HASH_B

    passed = mark_pass(report, clone_output=str(tmp_path / "clone-run"))
    assert passed["status"] == "pass"
    assert passed["stage"] == "complete"
    assert passed["completed_utc"] is not None
    assert passed["error"] is None

    persisted = json.loads(report.read_text(encoding="utf-8"))
    assert validate_session(persisted) == passed


def test_physical_session_can_record_explicit_dirty_checkout(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    value = _start(report, clean=False)
    assert value["bodyrig_checkout_clean"] is False


def test_physical_session_failure_preserves_stage(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    _start(report, performer_id="456", body_id="performer-456")
    failed = mark_fail(report, stage="readiness", message="OpenPose digest mismatch")
    assert failed["status"] == "fail"
    assert failed["stage"] == "readiness"
    assert failed["error"] == "OpenPose digest mismatch"
    assert failed["completed_utc"] is not None


def test_clone_failure_requires_readiness_evidence(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    _start(report, performer_id="789", body_id="performer-789")
    with pytest.raises(PhysicalSessionError, match="clone failure requires readiness evidence"):
        mark_fail(report, stage="clone", message="fit failed")


def test_pass_requires_readiness(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    _start(report)
    with pytest.raises(PhysicalSessionError, match="after readiness"):
        mark_pass(report, clone_output=str(tmp_path / "clone-run"))


def test_session_report_is_create_only(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    _start(report)
    with pytest.raises(PhysicalSessionError, match="already exists"):
        _start(report)


def test_validator_rejects_extra_fields_and_bad_hashes(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    value = _start(report)

    extra = dict(value)
    extra["stash_url"] = "http://secret.local"
    with pytest.raises(PhysicalSessionError, match="fields must match"):
        validate_session(extra)

    bad_hash = dict(value)
    bad_hash["rig_setup_sha256"] = "A" * 64
    with pytest.raises(PhysicalSessionError, match="lowercase SHA-256"):
        validate_session(bad_hash)


def test_validator_rejects_bad_revision_and_checkout_type(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    value = _start(report)

    bad_revision = dict(value)
    bad_revision["bodyrig_revision"] = "C" * 40
    with pytest.raises(PhysicalSessionError, match="Git SHA"):
        validate_session(bad_revision)

    bad_clean = dict(value)
    bad_clean["bodyrig_checkout_clean"] = "true"
    with pytest.raises(PhysicalSessionError, match="must be boolean"):
        validate_session(bad_clean)


def test_validator_rejects_invalid_body_id(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    value = _start(report)
    value["body_id"] = "../escape"
    with pytest.raises(PhysicalSessionError, match="invalid characters"):
        validate_session(value)
