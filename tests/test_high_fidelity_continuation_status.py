from __future__ import annotations

from pathlib import Path

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
            "components": components,
            "high_fidelity_ready": True,
            "production_ready": False,
        },
    )

    result = status._result(JOB_ID, gates, paths, package, "1" * 64, {})

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

    result = status._result(JOB_ID, gates, paths, package, "2" * 64, {})

    assert result["state"] == "blocked"
    assert result["high_fidelity_complete"] is False
    assert result["next_gate"]["gate"] == "face_secondary_promotion"
    assert result["production_ready"] is False


def test_human_input_next_actions_stay_explicit() -> None:
    paths = status.continuation_paths(JOB_ID)

    iris = status._next_action(JOB_ID, "iris_candidate", paths)
    face = status._next_action(JOB_ID, "face_secondary_review", paths)

    assert iris["operator_input_required"] is True
    assert "<LEFT_CX>" in iris["command"]
    assert "<RIGHT_RADIUS>" in iris["command"]
    assert face["operator_input_required"] is True
    assert "EXPLICIT_REVIEW_FLAGS" in face["command"]
