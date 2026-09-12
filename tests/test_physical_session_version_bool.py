from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.physical_session import (
    PhysicalSessionError,
    mark_readiness_pass,
    start_session,
    validate_session,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
REVISION = "c" * 40


def _start(report: Path) -> dict[str, object]:
    return start_session(
        report,
        performer_id="123",
        body_id="performer-123",
        bodyrig_revision=REVISION,
        bodyrig_checkout_clean=True,
        rig_setup_sha256=HASH_A,
    )


def test_validate_session_rejects_boolean_version(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    value = _start(report)
    value["version"] = True

    with pytest.raises(PhysicalSessionError, match="unsupported physical clone session format/version"):
        validate_session(value)


def test_persisted_boolean_version_fails_closed_before_transition(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    value = _start(report)
    value["version"] = True
    report.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(PhysicalSessionError, match="unsupported physical clone session format/version"):
        mark_readiness_pass(report, readiness_sha256=HASH_B)

    persisted = json.loads(report.read_text(encoding="utf-8"))
    assert persisted["version"] is True
    assert persisted["stage"] == "initializing"
    assert persisted["readiness_sha256"] is None


def test_numeric_float_v1_remains_compatible_through_transition(tmp_path: Path) -> None:
    report = tmp_path / "session.json"
    value = _start(report)
    value["version"] = 1.0

    validated = validate_session(value)
    assert validated["version"] == 1
    assert type(validated["version"]) is int

    report.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    ready = mark_readiness_pass(report, readiness_sha256=HASH_B)

    assert ready["version"] == 1
    assert type(ready["version"]) is int
    assert ready["stage"] == "clone"
    assert ready["readiness_sha256"] == HASH_B

    persisted = json.loads(report.read_text(encoding="utf-8"))
    assert persisted["version"] == 1
    assert type(persisted["version"]) is int
    assert persisted["stage"] == "clone"
