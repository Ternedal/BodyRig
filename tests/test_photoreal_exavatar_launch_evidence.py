from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_exavatar_launch_evidence import (
    PhotorealExAvatarLaunchEvidenceError,
    validate_teacher_launch_evidence,
)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    teacher = tmp_path / "teacher"
    teacher.mkdir()
    teacher_input = teacher / "teacher-input.json"
    teacher_config = teacher / "exavatar-teacher-config.json"
    teacher_manifest = teacher / "exavatar-teacher-output" / "output" / "teacher-manifest.json"
    _write_json(teacher_input, {"input": 1})
    _write_json(teacher_config, {"config": 1})
    _write_json(teacher_manifest, {"manifest": 1})

    run_id = "20260928-120000-" + ("a" * 32)
    launch_dir = teacher / "exavatar-teacher-launch-evidence" / run_id
    launch_dir.mkdir(parents=True)
    readiness = launch_dir / "readiness.json"
    _write_json(
        readiness,
        {
            "exavatar_launch_prerequisites_ready": True,
            "bodyrig_revision": "b" * 40,
            "bodyrig_branch": "main",
            "bodyrig_checkout_clean": True,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        },
    )
    launch = launch_dir / "launch-authority.json"
    _write_json(
        launch,
        {
            "format": "bodyrig-photoreal-exavatar-teacher-launch-authority",
            "version": 1,
            "run_id": run_id,
            "bodyrig_revision": "b" * 40,
            "readiness_relative_path": "readiness.json",
            "readiness_sha256": _sha(readiness),
            "teacher_config_sha256": _sha(teacher_config),
            "teacher_input_sha256": _sha(teacher_input),
            "training_authorized": True,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        },
    )
    completion = launch_dir / "completion.json"
    _write_json(
        completion,
        {
            "format": "bodyrig-photoreal-exavatar-teacher-completion-evidence",
            "version": 1,
            "run_id": run_id,
            "bodyrig_revision": "b" * 40,
            "launch_authority_sha256": _sha(launch),
            "teacher_manifest_sha256": _sha(teacher_manifest),
            "training_complete": True,
            "human_visual_acceptance_required": True,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        },
    )
    return teacher, launch_dir


def test_validate_teacher_launch_evidence_accepts_exact_bound_chain(tmp_path: Path) -> None:
    teacher, launch_dir = _fixture(tmp_path)

    result = validate_teacher_launch_evidence(teacher)

    assert result["evidence_root"] == str(launch_dir)
    assert result["training_complete"] is True
    assert result["human_visual_acceptance_required"] is True
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False


def test_validate_teacher_launch_evidence_rejects_tampered_readiness(tmp_path: Path) -> None:
    teacher, launch_dir = _fixture(tmp_path)
    readiness = launch_dir / "readiness.json"
    readiness.write_text(readiness.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(
        PhotorealExAvatarLaunchEvidenceError,
        match="bound readiness bytes changed after launch",
    ):
        validate_teacher_launch_evidence(teacher)


def test_validate_teacher_launch_evidence_rejects_tampered_teacher_manifest(tmp_path: Path) -> None:
    teacher, _launch_dir = _fixture(tmp_path)
    manifest = teacher / "exavatar-teacher-output" / "output" / "teacher-manifest.json"
    _write_json(manifest, {"manifest": 2})

    with pytest.raises(
        PhotorealExAvatarLaunchEvidenceError,
        match="no completed ExAvatar launch evidence matches",
    ):
        validate_teacher_launch_evidence(teacher)


def test_validate_teacher_launch_evidence_rejects_ambiguous_matching_completions(tmp_path: Path) -> None:
    teacher, launch_dir = _fixture(tmp_path)
    other = launch_dir.parent / ("20260928-120001-" + ("c" * 32))
    other.mkdir()
    for name in ("readiness.json", "launch-authority.json", "completion.json"):
        value = json.loads((launch_dir / name).read_text(encoding="utf-8"))
        value["run_id"] = other.name
        if name == "launch-authority.json":
            value["readiness_sha256"] = _sha(other / "readiness.json") if (other / "readiness.json").exists() else value["readiness_sha256"]
        _write_json(other / name, value)
    launch = json.loads((other / "launch-authority.json").read_text(encoding="utf-8"))
    launch["readiness_sha256"] = _sha(other / "readiness.json")
    _write_json(other / "launch-authority.json", launch)
    completion = json.loads((other / "completion.json").read_text(encoding="utf-8"))
    completion["launch_authority_sha256"] = _sha(other / "launch-authority.json")
    _write_json(other / "completion.json", completion)

    with pytest.raises(
        PhotorealExAvatarLaunchEvidenceError,
        match="multiple completed ExAvatar launch evidence chains",
    ):
        validate_teacher_launch_evidence(teacher)
