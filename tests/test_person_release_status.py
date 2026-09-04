from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.acceptance_status import AcceptanceStatus
from bodyrig.person_release_status import (
    PersonReleaseStatusError,
    _operator_next_command,
    inspect_candidate_release_status,
)

PERSON_ID = "person-" + "1" * 32
BODY_REVISION = "body-r0001"
BODY_ID = "bodyid-" + "2" * 24
PACKAGE_SHA = "3" * 64
BODYRIG_REVISION = "4" * 40
RENDERER_NAME = "BodyRig Reference Renderer"
RENDERER_VERSION = "reference-v1/univrm-0.131.2"
UNITY_VERSION = "6000.3.13f1"
DEFORMATION_REVISION = "humanoid-muscle-sweep-v1"
REFERENCE_OPERATOR_FILES = (
    "run-reference-windows-renderer-probe.ps1",
    "record-reference-renderer-acceptance.ps1",
    "run-reference-quest-renderer-probe.ps1",
    "complete-reference-acceptance.ps1",
    "reference-renderer/renderer-contract.json",
    "reference-renderer/build-reference-renderer.ps1",
    "reference-renderer/ProjectSettings/ProjectVersion.txt",
    "reference-renderer/Packages/manifest.json",
)
QUALITY_REVIEW = {
    "revision": "bodyrig-human-quality-v1",
    "full_deformation_sequence_reviewed": True,
    "source_identity_texture_acceptable": True,
    "geometry_proportions_acceptable": True,
    "upper_body_deformation_acceptable": True,
    "lower_body_deformation_acceptable": True,
    "cross_limb_leakage_absent": True,
    "skin_qa_considered": True,
}


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _job(acceptance_dir: Path) -> dict:
    return {
        "format": "bodyrig-ui-job",
        "version": 1,
        "kind": "body-build",
        "job_id": "job-test",
        "person_id": PERSON_ID,
        "body_revision": BODY_REVISION,
        "canonical_body_id": BODY_ID,
        "acceptance_dir": str(acceptance_dir),
        "created_utc": "2026-09-02T10:00:00Z",
        "status": "succeeded",
    }


def _gate(acceptance_dir: Path, package_sha: str = PACKAGE_SHA) -> None:
    _write(
        acceptance_dir / "bodyrig-acceptance.json",
        {"package": {"body_id": BODY_ID, "package_sha256": package_sha}},
    )


def _platform(acceptance_dir: Path, prefix: str, platform: str, unity_platform: str, device: str) -> None:
    probe = {
        "format": "bodyrig-renderer-probe",
        "version": 1,
        "platform": platform,
        "unity_platform": unity_platform,
        "unity_version": UNITY_VERSION,
        "device_model": device,
        "graphics_device": "test-gpu",
        "active_renderer": {"name": RENDERER_NAME, "version": RENDERER_VERSION},
    }
    _write(acceptance_dir / f"{prefix}-evidence" / f"{prefix}-probe.json", probe)
    _write(
        acceptance_dir / f"bodyrig-renderer-acceptance-{prefix}.json",
        {
            "format": "bodyrig-renderer-acceptance",
            "version": 1,
            "platform": platform,
            "result": "pass",
            "attestation": "operator-supplied",
            "machine_probe": True,
            "deformation_probe": True,
            "production_activation": False,
            "renderer_name": RENDERER_NAME,
            "renderer_version": RENDERER_VERSION,
            "unity_platform": unity_platform,
            "unity_version": UNITY_VERSION,
            "graphics_device": "test-gpu",
            "deformation_sequence_revision": DEFORMATION_REVISION,
            "quality_review": dict(QUALITY_REVIEW),
            "quality_note": "physical review passed",
        },
    )


def _status(
    gate: str,
    state: str = "ready",
    *,
    acceptance_dir: Path | str | None = None,
) -> AcceptanceStatus:
    return AcceptanceStatus(
        state=state,
        gate=gate,
        acceptance_dir=str(acceptance_dir) if acceptance_dir is not None else "unused",
        body_id=BODY_ID,
        bodyrig_revision=BODYRIG_REVISION,
        message="test status",
        next_command="test command" if state != "complete" else None,
    )


def _authority(tmp_path: Path, *, revision: str = BODYRIG_REVISION, omit: str | None = None) -> dict:
    root = tmp_path / "operator"
    for name in REFERENCE_OPERATOR_FILES:
        if name == omit:
            continue
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test\n", encoding="utf-8")
    return {"ok": True, "revision": revision, "root": str(root)}


def _inspect(
    acceptance: Path,
    tmp_path: Path,
    *,
    authority: dict | None = None,
) -> dict:
    return inspect_candidate_release_status(
        [_job(acceptance)],
        person_id=PERSON_ID,
        body_revision=BODY_REVISION,
        body_id=BODY_ID,
        package_sha256=PACKAGE_SHA,
        operator_authority=authority if authority is not None else _authority(tmp_path),
    )


def test_release_status_is_unavailable_without_originating_body_job() -> None:
    value = inspect_candidate_release_status(
        [],
        person_id=PERSON_ID,
        body_revision=BODY_REVISION,
        body_id=BODY_ID,
        package_sha256=PACKAGE_SHA,
    )
    assert value["state"] == "unavailable"
    assert value["production_activation"] is False
    assert value["operator_checkout"]["required"] is False
    assert set(value["stages"].values()) == {"unknown"}


def test_release_status_rejects_gate_a_package_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _gate(acceptance, package_sha="5" * 64)
    monkeypatch.setattr(
        "bodyrig.person_release_status.inspect_acceptance_dir",
        lambda _: _status("windows-probe", acceptance_dir=acceptance),
    )

    with pytest.raises(PersonReleaseStatusError, match="Gate A package SHA no longer matches"):
        _inspect(acceptance, tmp_path)


def test_reference_policy_blocks_missing_structured_quality_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _gate(acceptance)
    _platform(acceptance, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    attestation = acceptance / "bodyrig-renderer-acceptance-windows.json"
    value = json.loads(attestation.read_text(encoding="utf-8"))
    value.pop("quality_review")
    _write(attestation, value)
    monkeypatch.setattr(
        "bodyrig.person_release_status.inspect_acceptance_dir",
        lambda _: _status("quest-probe", acceptance_dir=acceptance),
    )

    result = _inspect(acceptance, tmp_path)
    assert result["state"] == "blocked"
    assert result["gate"] == "reference-contract"
    assert result["next_command"] is None
    assert result["production_activation"] is False
    assert set(result["stages"].values()) == {"pass", "blocked"}


def test_windows_complete_status_requires_operator_supplied_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _gate(acceptance)
    _platform(acceptance, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    attestation = acceptance / "bodyrig-renderer-acceptance-windows.json"
    value = json.loads(attestation.read_text(encoding="utf-8"))
    value["attestation"] = "synthetic"
    _write(attestation, value)
    monkeypatch.setattr(
        "bodyrig.person_release_status.inspect_acceptance_dir",
        lambda _: _status("quest-probe", acceptance_dir=acceptance),
    )

    with pytest.raises(PersonReleaseStatusError, match="not operator-supplied"):
        _inspect(acceptance, tmp_path)


def test_candidate_status_maps_physical_gates_without_granting_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _gate(acceptance)
    _platform(acceptance, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    monkeypatch.setattr(
        "bodyrig.person_release_status.inspect_acceptance_dir",
        lambda _: _status("quest-probe", acceptance_dir=acceptance),
    )

    value = _inspect(acceptance, tmp_path)
    assert value["stages"] == {
        "gate_a": "pass",
        "windows": "pass",
        "quest": "machine-probe-required",
        "release": "pending",
    }
    assert value["production_activation"] is False
    assert value["operator_checkout"]["ready"] is True
    assert "run-reference-quest-renderer-probe.ps1" in value["next_command"]


@pytest.mark.parametrize(
    ("gate", "state", "expected_script"),
    [
        ("windows-probe", "ready", "run-reference-windows-renderer-probe.ps1"),
        ("windows-attestation", "human-review", "record-reference-renderer-acceptance.ps1"),
        ("quest-probe", "ready", "run-reference-quest-renderer-probe.ps1"),
        ("quest-attestation", "human-review", "record-reference-renderer-acceptance.ps1"),
        ("release", "ready", "complete-reference-acceptance.ps1"),
    ],
)
def test_person_studio_next_commands_use_checkout_bound_reference_wrappers(
    tmp_path: Path, gate: str, state: str, expected_script: str
) -> None:
    acceptance = (tmp_path / "acceptance").resolve()
    operator_root = (tmp_path / "operator").resolve()
    command = _operator_next_command(
        gate=gate,
        state=state,
        acceptance_dir=acceptance,
        operator_root=operator_root,
    )
    assert command is not None
    expected_path = (operator_root / expected_script).resolve()
    assert command.startswith(f'& "{expected_path}"')
    assert f'-AcceptanceDir "{acceptance}"' in command
    assert "run-windows-renderer-probe.ps1 -AcceptanceDir" not in command
    assert "run-quest-renderer-probe.ps1 -AcceptanceDir" not in command
    assert "record-renderer-acceptance.ps1 -AcceptanceDir" not in command
    assert "complete-acceptance.ps1 -AcceptanceDir" not in command
    if gate in {"windows-attestation", "quest-attestation"}:
        assert "-ConfirmQualityChecklist" in command
        assert "-QualityNote " in command


def test_candidate_status_ignores_core_next_command_and_renders_checkout_bound_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _gate(acceptance)
    status = _status("windows-probe", acceptance_dir=acceptance)
    status = AcceptanceStatus(
        state=status.state,
        gate=status.gate,
        acceptance_dir=status.acceptance_dir,
        body_id=status.body_id,
        bodyrig_revision=status.bodyrig_revision,
        message="probe required",
        next_command='.\\run-windows-renderer-probe.ps1 -AcceptanceDir "wrong-core-path"',
    )
    monkeypatch.setattr("bodyrig.person_release_status.inspect_acceptance_dir", lambda _: status)
    authority = _authority(tmp_path)

    value = _inspect(acceptance, tmp_path, authority=authority)
    expected_script = (Path(authority["root"]) / "run-reference-windows-renderer-probe.ps1").resolve()
    assert value["next_command"] == f'& "{expected_script}" -AcceptanceDir "{acceptance.resolve()}"'
    assert "wrong-core-path" not in value["next_command"]


def test_operator_revision_mismatch_withholds_executable_next_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _gate(acceptance)
    monkeypatch.setattr(
        "bodyrig.person_release_status.inspect_acceptance_dir",
        lambda _: _status("windows-probe", acceptance_dir=acceptance),
    )

    value = _inspect(acceptance, tmp_path, authority=_authority(tmp_path, revision="9" * 40))
    assert value["next_command"] is None
    assert value["operator_checkout"]["ready"] is False
    assert "does not match acceptance revision" in value["operator_checkout"]["reason"]
    assert "Executable next command withheld" in value["message"]


def test_missing_reference_dependency_withholds_executable_next_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _gate(acceptance)
    monkeypatch.setattr(
        "bodyrig.person_release_status.inspect_acceptance_dir",
        lambda _: _status("windows-probe", acceptance_dir=acceptance),
    )

    value = _inspect(
        acceptance,
        tmp_path,
        authority=_authority(tmp_path, omit="run-reference-windows-renderer-probe.ps1"),
    )
    assert value["next_command"] is None
    assert value["operator_checkout"]["ready"] is False
    assert "missing canonical reference dependencies" in value["operator_checkout"]["reason"]


def test_legacy_root_renderer_evidence_is_blocked_in_person_studio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _gate(acceptance)
    (acceptance / "windows-probe.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        "bodyrig.person_release_status.inspect_acceptance_dir",
        lambda _: _status("windows-attestation", "human-review", acceptance_dir=acceptance),
    )

    value = _inspect(acceptance, tmp_path)
    assert value["state"] == "blocked"
    assert value["gate"] == "reference-layout"
    assert value["next_command"] is None
    assert value["production_activation"] is False


def test_complete_person_release_has_no_next_operator_command(tmp_path: Path) -> None:
    assert _operator_next_command(
        gate="release",
        state="complete",
        acceptance_dir=(tmp_path / "acceptance").resolve(),
        operator_root=(tmp_path / "operator").resolve(),
    ) is None


def test_complete_release_requires_strict_windows_and_quest_platform_attestations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _gate(acceptance)
    _platform(acceptance, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    _platform(acceptance, "quest", "android-quest-class", "Android", "Meta Quest 2")
    monkeypatch.setattr(
        "bodyrig.person_release_status.inspect_acceptance_dir",
        lambda _: _status("release", "complete", acceptance_dir=acceptance),
    )

    value = _inspect(acceptance, tmp_path)
    assert value["production_activation"] is True
    assert value["next_command"] is None
    assert value["operator_checkout"]["required"] is False
    assert value["stages"] == {"gate_a": "pass", "windows": "pass", "quest": "pass", "release": "pass"}
