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


def test_physical_session_pass_flow(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    started = start_session(report, performer_id="123", body_id="performer-123", rig_setup_sha256=HASH_A)
    assert started["status"] == "running"
    assert started["stage"] == "initializing"
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


def test_physical_session_failure_preserves_stage(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    start_session(report, performer_id="456", body_id="performer-456", rig_setup_sha256=HASH_A)
    failed = mark_fail(report, stage="readiness", message="OpenPose digest mismatch")
    assert failed["status"] == "fail"
    assert failed["stage"] == "readiness"
    assert failed["error"] == "OpenPose digest mismatch"
    assert failed["completed_utc"] is not None


def test_clone_failure_requires_readiness_evidence(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    start_session(report, performer_id="789", body_id="performer-789", rig_setup_sha256=HASH_A)
    with pytest.raises(PhysicalSessionError, match="clone failure requires readiness evidence"):
        mark_fail(report, stage="clone", message="fit failed")


def test_pass_requires_readiness(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    start_session(report, performer_id="123", body_id="performer-123", rig_setup_sha256=HASH_A)
    with pytest.raises(PhysicalSessionError, match="after readiness"):
        mark_pass(report, clone_output=str(tmp_path / "clone-run"))


def test_session_report_is_create_only(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    start_session(report, performer_id="123", body_id="performer-123", rig_setup_sha256=HASH_A)
    with pytest.raises(PhysicalSessionError, match="already exists"):
        start_session(report, performer_id="123", body_id="performer-123", rig_setup_sha256=HASH_A)


def test_validator_rejects_extra_fields_and_bad_hashes(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    value = start_session(report, performer_id="123", body_id="performer-123", rig_setup_sha256=HASH_A)

    extra = dict(value)
    extra["stash_url"] = "http://secret.local"
    with pytest.raises(PhysicalSessionError, match="fields must match"):
        validate_session(extra)

    bad_hash = dict(value)
    bad_hash["rig_setup_sha256"] = "A" * 64
    with pytest.raises(PhysicalSessionError, match="lowercase SHA-256"):
        validate_session(bad_hash)


def test_validator_rejects_invalid_body_id(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    value = start_session(report, performer_id="123", body_id="performer-123", rig_setup_sha256=HASH_A)
    value["body_id"] = "../escape"
    with pytest.raises(PhysicalSessionError, match="invalid characters"):
        validate_session(value)
