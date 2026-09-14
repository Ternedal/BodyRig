from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import bodyrig.fidelity_component_gap_executor as executor


REVISION = "a" * 40
BODY_ID = "performer-42"


def plan() -> dict:
    return {
        "format": "bodyrig-fidelity-component-gap-plan",
        "version": 1,
        "bodyrig_revision": REVISION,
        "body_id": BODY_ID,
        "package_sha256": "b" * 64,
        "state": "composition-required",
        "drawable_components": ["hair", "eyes"],
        "missing_components": ["face-secondary", "fingernails", "toenails"],
        "next_actions": [
            {
                "id": "face-secondary-review-composition",
                "components": ["face-secondary"],
                "operator_input_required": False,
                "implementation_required": False,
                "reason": "run existing comparison-only face composer",
            },
            {
                "id": "source-bound-hfn-continuation",
                "components": ["fingernails", "toenails"],
                "operator_input_required": True,
                "implementation_required": False,
                "reason": "operator-bound HFN continuation",
            },
        ],
        "strict_machine_scoring_ready": False,
        "human_visual_authority_required": True,
        "production_activation": False,
        "semantics": "physical-component-gap-planning-not-visual-or-release-acceptance",
    }


def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "build-high-fidelity-face-secondary-review-runtime.ps1").write_text("exit 0\n", encoding="utf-8")
    (root / "run-high-fidelity-face-secondary-windows-preview.ps1").write_text("exit 0\n", encoding="utf-8")
    return root


def preview(*, body_id: str = BODY_ID, revision: str = REVISION, status: str = "succeeded") -> dict:
    return {
        "job_id": "hfpreview-" + "1" * 32,
        "person_id": "person-7",
        "canonical_body_id": body_id,
        "bodyrig_revision": revision,
        "status": status,
        "comparison_only": True,
        "production_activation": False,
    }


def configure_continuation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    current_package = tmp_path / "eyes-promoted.mrbody"
    current_package.write_bytes(b"eyes-promoted")
    current_sha = hashlib.sha256(b"eyes-promoted").hexdigest()
    face_runtime = tmp_path / "continuation" / "face-secondary" / "runtime"
    face_preview = tmp_path / "continuation" / "face-secondary" / "windows-preview"
    monkeypatch.setattr(
        executor,
        "inspect_continuation",
        lambda _job: {
            "production_activation": False,
            "production_ready": False,
            "current_package_path": str(current_package),
            "current_package_sha256": current_sha,
            "next_gate": {"gate": "face_secondary_runtime", "operator_input_required": False},
        },
    )
    monkeypatch.setattr(
        executor,
        "continuation_paths",
        lambda _job: {"face_runtime": face_runtime, "face_preview_root": face_preview},
    )
    return current_package, face_runtime


def test_face_execution_binds_preview_person_body_and_revision_before_continuation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = repo(tmp_path)
    current_package, face_runtime = configure_continuation(monkeypatch, tmp_path)
    monkeypatch.setattr(executor.preview_manager, "get", lambda _job: preview())

    result = executor.build_execution(
        plan(),
        context={"preview_job_id": "hfpreview-" + "1" * 32},
        repo_root=root,
    )

    assert result["person_id"] == "person-7"
    assert result["canonical_body_id"] == BODY_ID
    assert result["preview_bodyrig_revision"] == REVISION
    assert result["preview_job_id"] == "hfpreview-" + "1" * 32
    assert str(current_package.resolve()) in result["commands"][0]
    assert str(face_runtime.resolve()) in result["commands"][0]
    assert result["production_activation"] is False
    assert result["human_visual_authority_required"] is True


def test_face_execution_rejects_cross_body_preview_before_continuation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = repo(tmp_path)
    monkeypatch.setattr(executor.preview_manager, "get", lambda _job: preview(body_id="other-body"))
    called = False

    def inspect(_job: str) -> dict:
        nonlocal called
        called = True
        raise AssertionError("continuation must not be inspected for the wrong body")

    monkeypatch.setattr(executor, "inspect_continuation", inspect)
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="different canonical body"):
        executor.build_execution(plan(), context={"preview_job_id": "hfpreview-" + "1" * 32}, repo_root=root)
    assert called is False


def test_face_execution_rejects_cross_revision_or_incomplete_preview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = repo(tmp_path)
    monkeypatch.setattr(executor.preview_manager, "get", lambda _job: preview(revision="c" * 40))
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="different BodyRig revision"):
        executor.build_execution(plan(), context={"preview_job_id": "hfpreview-" + "1" * 32}, repo_root=root)

    monkeypatch.setattr(executor.preview_manager, "get", lambda _job: preview(status="running"))
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="succeeded high-fidelity preview"):
        executor.build_execution(plan(), context={"preview_job_id": "hfpreview-" + "1" * 32}, repo_root=root)
