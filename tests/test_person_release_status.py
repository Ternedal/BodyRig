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
        "unity_version": "6000.3.13f1",
        "device_model": device,
        "graphics_device": "test-gpu",
        "active_renderer": {"name": "BodyRig Reference Renderer", "version": "1"},
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
            "renderer_name": probe["active_renderer"]["name"],
            "renderer_version": probe["active_renderer"]["version"],
            "unity_platform": unity_platform,
            "unity_version": probe["unity_version"],
            "graphics_device": probe["graphics_device"],
            "quality_review": dict(QUALITY_REVIEW),
            "quality_note": "physical review passed",
        },
    )


def _status(gate: str, state: str = "ready") -> AcceptanceStatus:
    return AcceptanceStatus(
        state=state,
        gate=gate,
        acceptance_dir="unused",
        body_id=BODY_ID,
        bodyrig_revision=BODYRIG_REVISION,
        message="test status",
        next_command="test command" if state != "complete" else None,
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
    assert set(value["stages"].values()) == {"unknown"}


def test_release_status_rejects_gate_a_package_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _gate(acceptance, package_sha="5" * 64)
    monkeypatch.setattr("bodyrig.person_release_status.inspect_acceptance_dir", lambda _: _status("windows-probe"))

    with pytest.raises(PersonReleaseStatusError, match="Gate A package SHA no longer matches"):
        inspect_candidate_release_status(
            [_job(acceptance)],
            person_id=PERSON_ID,
            body_revision=BODY_REVISION,
            body_id=BODY_ID,
            package_sha256=PACKAGE_SHA,
        )


def test_windows_complete_status_requires_structured_operator_quality_review(
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
    monkeypatch.setattr("bodyrig.person_release_status.inspect_acceptance_dir", lambda _: _status("quest-probe"))

    with pytest.raises(PersonReleaseStatusError, match="canonical structured human quality review"):
        inspect_candidate_release_status(
            [_job(acceptance)],
            person_id=PERSON_ID,
            body_revision=BODY_REVISION,
            body_id=BODY_ID,
            package_sha256=PACKAGE_SHA,
        )


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
    monkeypatch.setattr("bodyrig.person_release_status.inspect_acceptance_dir", lambda _: _status("quest-probe"))

    with pytest.raises(PersonReleaseStatusError, match="not operator-supplied"):
        inspect_candidate_release_status(
            [_job(acceptance)],
            person_id=PERSON_ID,
            body_revision=BODY_REVISION,
            body_id=BODY_ID,
            package_sha256=PACKAGE_SHA,
        )


def test_candidate_status_maps_physical_gates_without_granting_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _gate(acceptance)
    _platform(acceptance, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    monkeypatch.setattr("bodyrig.person_release_status.inspect_acceptance_dir", lambda _: _status("quest-probe"))

    value = inspect_candidate_release_status(
        [_job(acceptance)],
        person_id=PERSON_ID,
        body_revision=BODY_REVISION,
        body_id=BODY_ID,
        package_sha256=PACKAGE_SHA,
    )
    assert value["stages"] == {
        "gate_a": "pass",
        "windows": "pass",
        "quest": "machine-probe-required",
        "release": "pending",
    }
    assert value["production_activation"] is False


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
def test_person_studio_next_commands_use_canonical_reference_wrappers(
    tmp_path: Path, gate: str, state: str, expected_script: str
) -> None:
    acceptance = (tmp_path / "acceptance").resolve()
    command = _operator_next_command(gate=gate, state=state, acceptance_dir=acceptance)
    assert command is not None
    assert command.startswith(f".\\{expected_script}")
    assert f'-AcceptanceDir "{acceptance}"' in command
    assert ".\\run-windows-renderer-probe.ps1" not in command
    assert ".\\run-quest-renderer-probe.ps1" not in command
    assert ".\\record-renderer-acceptance.ps1" not in command
    assert ".\\complete-acceptance.ps1" not in command
    if gate in {"windows-attestation", "quest-attestation"}:
        assert "-ConfirmQualityChecklist" in command
        assert "-QualityNote " in command


def test_candidate_status_ignores_core_next_command_and_renders_reference_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _gate(acceptance)
    status = AcceptanceStatus(
        state="ready",
        gate="windows-probe",
        acceptance_dir=str(acceptance),
        body_id=BODY_ID,
        bodyrig_revision=BODYRIG_REVISION,
        message="probe required",
        next_command='.\\run-windows-renderer-probe.ps1 -AcceptanceDir "wrong-core-path"',
    )
    monkeypatch.setattr("bodyrig.person_release_status.inspect_acceptance_dir", lambda _: status)

    value = inspect_candidate_release_status(
        [_job(acceptance)],
        person_id=PERSON_ID,
        body_revision=BODY_REVISION,
        body_id=BODY_ID,
        package_sha256=PACKAGE_SHA,
    )
    assert value["next_command"] == (
        f'.\\run-reference-windows-renderer-probe.ps1 -AcceptanceDir "{acceptance.resolve()}"'
    )
    assert "wrong-core-path" not in value["next_command"]


def test_complete_person_release_has_no_next_operator_command(tmp_path: Path) -> None:
    assert _operator_next_command(
        gate="release",
        state="complete",
        acceptance_dir=(tmp_path / "acceptance").resolve(),
    ) is None


def test_complete_release_requires_strict_windows_and_quest_platform_attestations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _gate(acceptance)
    _platform(acceptance, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    _platform(acceptance, "quest", "android-quest-class", "Android", "Meta Quest 2")
    monkeypatch.setattr("bodyrig.person_release_status.inspect_acceptance_dir", lambda _: _status("release", "complete"))

    value = inspect_candidate_release_status(
        [_job(acceptance)],
        person_id=PERSON_ID,
        body_revision=BODY_REVISION,
        body_id=BODY_ID,
        package_sha256=PACKAGE_SHA,
    )
    assert value["production_activation"] is True
    assert value["stages"] == {"gate_a": "pass", "windows": "pass", "quest": "pass", "release": "pass"}
