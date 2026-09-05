from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import bodyrig.high_fidelity_continuation_status as status


JOB_ID = "hfpreview-" + "a" * 32


def test_gate_order_is_complete_and_stable() -> None:
    assert status.GATE_ORDER == (
        "preview",
        "component_review",
        "anatomy_promotion",
        "hair_deformation_review",
        "hair_promotion",
        "iris_candidate",
        "iris_review",
        "iris_reviewed_runtime",
        "eyes_eligibility",
        "eye_fingerprint",
        "eye_only_rebuild",
        "eyes_promotion",
        "face_secondary_runtime",
        "face_secondary_preview",
        "face_secondary_review",
        "face_secondary_promotion",
    )


def test_continuation_paths_stay_inside_one_preview_job(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / JOB_ID
    monkeypatch.setattr(status, "_preview_root", lambda _job_id: root)

    paths = status.continuation_paths(JOB_ID)

    assert paths["preview_root"] == root
    assert paths["source_eye_appearance"] == root / "components" / "eye-appearance"
    assert paths["base_runtime"] == root / "components" / "runtime"
    assert paths["iris_candidate"] == root / "continuation" / "iris-candidate"
    assert paths["eye_only_runtime"] == root / "continuation" / "eye-only-runtime"
    assert paths["face_promotion"] == root / "continuation" / "face-secondary" / "promotion"
    for key, path in paths.items():
        if key != "preview_root":
            path.relative_to(root)


def test_result_stops_at_first_unpassed_gate_and_never_grants_production(tmp_path: Path) -> None:
    paths = status.continuation_paths(JOB_ID)
    gates = [
        status._gate("preview", "pass"),
        status._gate("component_review", "pass"),
        status._gate("anatomy_promotion", "pass"),
        status._gate("hair_deformation_review", "required", reason="physical review required"),
    ]

    result = status._result(JOB_ID, gates, paths, None, None, {})

    assert result["state"] == "incomplete"
    assert result["next_gate"]["gate"] == "hair_deformation_review"
    assert result["next_gate"]["operator_input_required"] is True
    assert result["high_fidelity_complete"] is False
    assert result["production_ready"] is False
    assert result["production_activation"] is False
    assert result["physical_windows_acceptance_required"] is True
    assert result["quest_acceptance_required"] is True
    assert result["final_release_required"] is True


def test_all_component_gates_can_be_high_fidelity_complete_without_becoming_production_ready(
    monkeypatch, tmp_path: Path
) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"package")
    paths = status.continuation_paths(JOB_ID)
    gates = [status._gate(name, "pass") for name in status.GATE_ORDER]
    components = {
        "body_anatomy": "complete",
        "skin_appearance": "complete",
        "hair": "complete",
        "eyes": "complete",
        "face_secondary": "complete",
    }
    monkeypatch.setattr(
        status,
        "audit_high_fidelity_package",
        lambda _path: {
            "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
            "components": components,
            "high_fidelity_ready": True,
            "production_ready": False,
        },
    )

    result = status._result(JOB_ID, gates, paths, package, hashlib.sha256(package.read_bytes()).hexdigest(), {})

    assert result["state"] == "complete"
    assert result["next_gate"] is None
    assert result["components"] == components
    assert result["high_fidelity_complete"] is True
    assert result["high_fidelity_human_review_required"] is True
    assert result["production_ready"] is False
    assert result["production_activation"] is False
    assert result["physical_windows_acceptance_required"] is True
    assert result["quest_acceptance_required"] is True
    assert result["final_release_required"] is True


def test_final_audit_cannot_turn_partial_components_into_complete(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"package")
    paths = status.continuation_paths(JOB_ID)
    gates = [status._gate(name, "pass") for name in status.GATE_ORDER]
    monkeypatch.setattr(
        status,
        "audit_high_fidelity_package",
        lambda _path: {
            "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
            "components": {
                "body_anatomy": "complete",
                "skin_appearance": "complete",
                "hair": "complete",
                "eyes": "complete",
                "face_secondary": "partial",
            },
            "high_fidelity_ready": False,
            "production_ready": False,
        },
    )

    result = status._result(JOB_ID, gates, paths, package, hashlib.sha256(package.read_bytes()).hexdigest(), {})

    assert result["state"] == "blocked"
    assert result["high_fidelity_complete"] is False
    assert result["next_gate"]["gate"] == "face_secondary_promotion"
    assert result["next_gate"]["command"] is None
    assert result["production_ready"] is False


def test_human_input_next_actions_stay_explicit() -> None:
    paths = status.continuation_paths(JOB_ID)

    iris = status._next_action(JOB_ID, "iris_candidate", paths)
    face = status._next_action(JOB_ID, "face_secondary_review", paths)

    assert iris["operator_input_required"] is True
    assert "<LEFT_CX>" in iris["command"]
    assert "<RIGHT_RADIUS>" in iris["command"]
    assert face["operator_input_required"] is True
    assert "<QUALITY_NOTE>" in face["command"]
    assert "-NeutralFacePreserved" in face["command"]
    assert "-MouthOpenPoseReviewed" in face["command"]
    assert "-EyelashesNoObviousEyeSurfaceClipping" in face["command"]


@pytest.mark.parametrize("stage,switch", [
    ("component_review", "-ConfirmVisualChecklist"),
    ("hair_deformation_review", "-ConfirmHairDeformationChecklist"),
])
def test_review_commands_name_actual_operator_inputs(stage: str, switch: str) -> None:
    action = status._next_action(JOB_ID, stage, status.continuation_paths(JOB_ID))

    assert switch in action["command"]
    assert "-QualityNote <QUALITY_NOTE>" in action["command"]
    assert "<EXPLICIT_" not in action["command"]
    assert action["operator_input_required"] is True


@pytest.mark.parametrize("value", [
    {"state": "pass", "passed": False},
    {"state": "invalid", "passed": True},
    {"state": "pass"},
])
def test_inconsistent_review_state_cannot_pass(value: dict) -> None:
    assert status._simple_state(value) == "invalid"


def test_corrupt_component_review_returns_blocked_status(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"candidate")
    monkeypatch.setattr(status.preview_manager, "get", lambda _job: {"status": "succeeded"})
    monkeypatch.setattr(status, "_candidate_package", lambda *_args: package)

    def corrupt(_job: str) -> dict:
        raise status.HighFidelityComponentReviewError("stored review no longer matches preview")

    monkeypatch.setattr(status, "component_review_status", corrupt)
    result = status.inspect_continuation(JOB_ID)

    assert result["state"] == "blocked"
    assert result["gates"][-1]["id"] == "component_review"
    assert result["gates"][-1]["state"] == "invalid"
    assert result["next_gate"]["command"] is None
    assert "no longer matches" in result["next_gate"]["reason"]


def test_missing_nested_evidence_does_not_offer_to_overwrite_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "runtime"
    error = RuntimeError("runtime receipt is missing")
    assert status._missing_or_invalid(error, output) == "required"
    output.mkdir()
    assert status._missing_or_invalid(error, output) == "invalid"


@pytest.mark.parametrize("change", ["before", "during", "missing", "audit_sha"])
def test_final_component_status_binds_exact_package_through_audit(monkeypatch, tmp_path: Path, change: str) -> None:
    package = tmp_path / "final.mrbody"
    package.write_bytes(b"reviewed package")
    expected = hashlib.sha256(package.read_bytes()).hexdigest()
    if change == "before":
        package.write_bytes(b"replacement")
    elif change == "missing":
        package.unlink()

    def audit(path: Path) -> dict:
        if change == "during":
            path.write_bytes(b"replacement during audit")
        return {"package_sha256": "0" * 64 if change == "audit_sha" else expected,
                "high_fidelity_ready": True, "components": {"face_secondary": "complete"}}

    monkeypatch.setattr(status, "audit_high_fidelity_package", audit)
    gates = [status._gate(name, "pass") for name in status.GATE_ORDER]
    result = status._result(JOB_ID, gates, status.continuation_paths(JOB_ID), package, expected, {})

    assert result["state"] == "blocked"
    assert result["high_fidelity_complete"] is False
    assert result["next_gate"]["command"] is None
    assert result["final_audit"] is None
    assert result["components"] == {}


@pytest.mark.parametrize("receipt", [[], {}, {"candidate_workspace": ""}])
def test_invalid_discovery_receipt_cannot_resolve_process_working_directory(monkeypatch, tmp_path: Path, receipt) -> None:
    monkeypatch.setattr(status, "_preview_root", lambda _job: tmp_path)
    paths = status.continuation_paths(JOB_ID)
    paths["component_root"].mkdir()
    (paths["component_root"] / "subject-component-discovery.json").write_text(json.dumps(receipt))
    with pytest.raises(status.HighFidelityContinuationStatusError, match="no candidate workspace"):
        status._candidate_workspace(paths)


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell is exercised in canonical CI")
def test_operator_path_quoting_round_trips_through_powershell() -> None:
    from bodyrig.high_fidelity_release_readiness import _review_command

    value = "C:\\Users\\O'Brien\\$USER\\$(throw 'expanded')\\`n\\body.mrbody"
    script = "$value = & { param($Path) $Path } " + status._quote(value) + "; ConvertTo-Json -Compress -InputObject $value"
    completed = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout) == value
    assert status._quote(value) in _review_command(Path(value))
