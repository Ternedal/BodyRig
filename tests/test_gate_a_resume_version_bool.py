from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.gate_a_resume as gate
from bodyrig.physical_session import mark_pass, mark_readiness_pass, start_session


RIG_HASH = "a" * 64
PRODUCER_REVISION = "b" * 40
VALIDATOR_REVISION = "c" * 40
BODY_ID = "performer-123"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _completed_session(
    tmp_path: Path,
    *,
    readiness_version: object,
    create_clone_dir: bool,
) -> tuple[Path, Path]:
    session_path = tmp_path / "physical-session.json"
    readiness_path = session_path.with_suffix(".readiness.json")
    clone_root = tmp_path / "clone-output"
    clone_dir = clone_root / "clone"
    if create_clone_dir:
        clone_dir.mkdir(parents=True)

    _write_json(
        readiness_path,
        {
            "format": "bodyrig-rig-readiness",
            "version": readiness_version,
            "ready": True,
            "rig_setup_sha256": RIG_HASH,
        },
    )
    start_session(
        session_path,
        performer_id="123",
        body_id=BODY_ID,
        bodyrig_revision=PRODUCER_REVISION,
        bodyrig_checkout_clean=True,
        rig_setup_sha256=RIG_HASH,
    )
    mark_readiness_pass(session_path, readiness_sha256=_sha256(readiness_path))
    mark_pass(session_path, clone_output=str(clone_root))
    return session_path, clone_dir


def _stub_runtime_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    runtime_version: object,
) -> None:
    monkeypatch.setattr(
        gate,
        "_validate_package_lineage",
        lambda **_: {
            "body_id": BODY_ID,
            "body_name": "Test Body",
            "payload_names": ["avatar.vrm", "bodyprint.json"],
            "source_count": 2,
            "recovery_adapter": "test-recovery",
            "recovery_revision": "1",
            "track_id": "track-1",
            "observed_frames": 2,
            "shape_present": True,
            "motion_present": True,
            "adjustment_sha256": None,
        },
    )
    monkeypatch.setattr(
        gate,
        "analyze_skin",
        lambda _: {
            "structural_pass": True,
            "manual_review_required": True,
            "automated_assessment": "low-risk",
        },
    )
    monkeypatch.setattr(
        gate,
        "write_skin_report",
        lambda path, value: _write_json(path, value),
    )
    monkeypatch.setattr(
        gate,
        "analyze_topology",
        lambda _: {
            "structural_pass": True,
            "manual_review_required": True,
            "automated_assessment": "pass",
        },
    )

    def _materialize(command, **_) -> SimpleNamespace:
        package_path = Path(command[3])
        runtime_dir = Path(command[-1])
        _write_json(
            runtime_dir / "runtime-manifest.json",
            {
                "format": "bodyrig-runtime-assets",
                "version": runtime_version,
                "body_id": BODY_ID,
                "package_sha256": _sha256(package_path),
            },
        )
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(gate.subprocess, "run", _materialize)


def _prepare_clone_artifacts(clone_dir: Path) -> None:
    (clone_dir / f"{BODY_ID}.mrbody").write_bytes(b"gate-a-resume-package")
    _write_json(clone_dir / "bodyrig-recovery-preflight.json", {"ok": True})
    _write_json(clone_dir / "bodyrig-portable-identity.json", {"body_id": BODY_ID})


def test_gate_a_resume_rejects_boolean_readiness_version(tmp_path: Path) -> None:
    session_path, _ = _completed_session(
        tmp_path,
        readiness_version=True,
        create_clone_dir=False,
    )

    with pytest.raises(gate.GateAResumeError, match="READY v1 evidence"):
        gate.resume_gate_a(
            session_report=session_path,
            validator_revision=VALIDATOR_REVISION,
            output_dir=tmp_path / "gate-a",
            python_executable="python",
        )

    assert not (tmp_path / "gate-a").exists()


def test_gate_a_resume_rejects_boolean_runtime_manifest_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_path, clone_dir = _completed_session(
        tmp_path,
        readiness_version=1,
        create_clone_dir=True,
    )
    _prepare_clone_artifacts(clone_dir)
    _stub_runtime_dependencies(monkeypatch, runtime_version=True)

    with pytest.raises(gate.GateAResumeError, match="runtime manifest format/version mismatch"):
        gate.resume_gate_a(
            session_report=session_path,
            validator_revision=VALIDATOR_REVISION,
            output_dir=tmp_path / "gate-a",
            python_executable="python",
        )

    assert not (tmp_path / "gate-a").exists()


def test_gate_a_resume_preserves_numeric_float_v1_at_both_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_path, clone_dir = _completed_session(
        tmp_path,
        readiness_version=1.0,
        create_clone_dir=True,
    )
    _prepare_clone_artifacts(clone_dir)
    _stub_runtime_dependencies(monkeypatch, runtime_version=1.0)

    result = gate.resume_gate_a(
        session_report=session_path,
        validator_revision=VALIDATOR_REVISION,
        output_dir=tmp_path / "gate-a",
        python_executable="python",
    )

    assert Path(result["acceptance"]).is_file()
    assert Path(result["validation_authority"]).is_file()
    assert result["body_id"] == BODY_ID
    assert result["recovery_rerun"] is False
    assert result["fitter_rerun"] is False
