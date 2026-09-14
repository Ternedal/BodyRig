from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import bodyrig.fidelity_component_gap_executor as executor


REVISION = "a" * 40
PACKAGE_SHA = hashlib.sha256(b"package").hexdigest()


def plan(action_id: str, *, missing: list[str] | None = None) -> dict:
    missing = list(missing if missing is not None else ["hair"])
    ready = not missing
    action = {
        "id": action_id,
        "components": ["hair"] if action_id == "retained-source-hair-eye-composition" else (
            ["face-secondary"] if action_id == "face-secondary-review-composition" else (
                ["fingernails", "toenails"] if action_id == "source-bound-hfn-continuation" else ["hair", "eyes", "face-secondary", "fingernails", "toenails"]
            )
        ),
        "operator_input_required": action_id in {"source-bound-hfn-continuation", "human-visual-qa"},
        "implementation_required": False,
        "reason": "test route",
    }
    return {
        "format": "bodyrig-fidelity-component-gap-plan",
        "version": 1,
        "bodyrig_revision": REVISION,
        "body_id": "performer-42",
        "package_sha256": PACKAGE_SHA,
        "state": "machine-component-complete-human-review-required" if ready else "composition-required",
        "drawable_components": [] if missing else ["hair", "eyes", "face-secondary", "fingernails", "toenails"],
        "missing_components": missing,
        "next_actions": [action],
        "strict_machine_scoring_ready": ready,
        "human_visual_authority_required": True,
        "production_activation": False,
        "semantics": "physical-component-gap-planning-not-visual-or-release-acceptance",
    }


def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for name in (
        "run-retained-hair-eye-preview.ps1",
        "build-high-fidelity-face-secondary-review-runtime.ps1",
        "run-high-fidelity-face-secondary-windows-preview.ps1",
        "prepare-hands-feet-nails-fingernail-geometry-candidate.ps1",
        "prepare-hands-feet-nails-toenail-geometry-candidate.ps1",
        "prepare-hands-feet-nails-render-review.ps1",
    ):
        (root / name).write_text("exit 0\n", encoding="utf-8")
    return root


def preview_lineage() -> dict:
    return {
        "job_id": "preview-42",
        "person_id": "person-42",
        "canonical_body_id": "performer-42",
        "bodyrig_revision": REVISION,
        "candidate_package_sha256": PACKAGE_SHA,
        "status": "succeeded",
        "comparison_only": True,
        "production_activation": False,
    }


def test_validate_plan_is_bool_safe_and_preserves_authority_boundaries() -> None:
    value = plan("retained-source-hair-eye-composition")
    assert executor.validate_plan(value)["version"] == 1

    for bad in (True, False, "1", None, 2):
        invalid = dict(value)
        invalid["version"] = bad
        with pytest.raises(executor.FidelityComponentGapExecutionError, match="format/version"):
            executor.validate_plan(invalid)

    invalid = dict(value)
    invalid["production_activation"] = True
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="authority boundary"):
        executor.validate_plan(invalid)


def test_hair_eye_execution_is_bound_to_exact_unity_gap_package(tmp_path: Path) -> None:
    root = repo(tmp_path)
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"package")
    workspace = tmp_path / "identity"
    workspace.mkdir()
    output = tmp_path / "out" / "hair-eye"
    output.parent.mkdir()

    result = executor.build_execution(
        plan("retained-source-hair-eye-composition"),
        context={
            "package_path": str(package),
            "identity_workspace": str(workspace),
            "output_root": str(output),
        },
        repo_root=root,
    )

    assert result["mode"] == "machine-executable"
    assert result["action_id"] == "retained-source-hair-eye-composition"
    assert result["commands"][0][0:4] == ["pwsh", "-NoProfile", "-File", str(root / "run-retained-hair-eye-preview.ps1")]
    assert "-PackagePath" in result["commands"][0]
    assert str(package.resolve()) in result["commands"][0]
    assert result["reprobe_required_after_execution"] is True
    assert result["human_visual_authority_required"] is True
    assert result["production_activation"] is False

    package.write_bytes(b"changed")
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="differ from the Unity gap-plan package SHA"):
        executor.build_execution(
            plan("retained-source-hair-eye-composition"),
            context={
                "package_path": str(package),
                "identity_workspace": str(workspace),
                "output_root": str(output),
            },
            repo_root=root,
        )


def test_face_secondary_routes_only_through_canonical_machine_safe_continuation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    current_package = tmp_path / "eyes-promoted.mrbody"
    current_package.write_bytes(b"eyes-promoted")
    current_sha = hashlib.sha256(b"eyes-promoted").hexdigest()
    continuation = tmp_path / "continuation"
    face_runtime = continuation / "face-secondary" / "runtime"
    face_preview = continuation / "face-secondary" / "windows-preview"

    monkeypatch.setattr(executor.preview_manager, "get", lambda _job: preview_lineage())
    monkeypatch.setattr(
        executor,
        "inspect_continuation",
        lambda _job: {
            "production_activation": False,
            "production_ready": False,
            "current_package_path": str(current_package),
            "current_package_sha256": current_sha,
            "next_gate": {
                "gate": "face_secondary_runtime",
                "operator_input_required": False,
            },
        },
    )
    monkeypatch.setattr(
        executor,
        "continuation_paths",
        lambda _job: {
            "face_runtime": face_runtime,
            "face_preview_root": face_preview,
        },
    )

    result = executor.build_execution(
        plan("face-secondary-review-composition", missing=["face-secondary"]),
        context={"preview_job_id": "preview-42"},
        repo_root=root,
    )
    command = result["commands"][0]
    assert result["continuation_gate"] == "face_secondary_runtime"
    assert command[3] == str(root / "build-high-fidelity-face-secondary-review-runtime.ps1")
    assert str(current_package.resolve()) in command
    assert str(face_runtime.resolve()) in command

    monkeypatch.setattr(
        executor,
        "inspect_continuation",
        lambda _job: {
            "production_activation": False,
            "production_ready": False,
            "current_package_path": str(current_package),
            "current_package_sha256": current_sha,
            "next_gate": {
                "gate": "face_secondary_review",
                "operator_input_required": True,
            },
        },
    )
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="not at a machine-safe face-secondary gate"):
        executor.build_execution(
            plan("face-secondary-review-composition", missing=["face-secondary"]),
            context={"preview_job_id": "preview-42"},
            repo_root=root,
        )


def test_face_secondary_preview_uses_existing_runtime_and_refuses_reuse(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    current_package = tmp_path / "eyes-promoted.mrbody"
    current_package.write_bytes(b"eyes-promoted")
    current_sha = hashlib.sha256(b"eyes-promoted").hexdigest()
    continuation = tmp_path / "continuation"
    face_runtime = continuation / "face-secondary" / "runtime"
    face_runtime.mkdir(parents=True)
    face_preview = continuation / "face-secondary" / "windows-preview"

    monkeypatch.setattr(executor.preview_manager, "get", lambda _job: preview_lineage())
    monkeypatch.setattr(executor, "inspect_continuation", lambda _job: {
        "production_activation": False,
        "production_ready": False,
        "current_package_path": str(current_package),
        "current_package_sha256": current_sha,
        "next_gate": {"gate": "face_secondary_preview", "operator_input_required": False},
    })
    monkeypatch.setattr(executor, "continuation_paths", lambda _job: {
        "face_runtime": face_runtime,
        "face_preview_root": face_preview,
    })

    result = executor.build_execution(
        plan("face-secondary-review-composition", missing=["face-secondary"]),
        context={"preview_job_id": "preview-42"},
        repo_root=root,
    )
    command = result["commands"][0]
    assert command[3] == str(root / "run-high-fidelity-face-secondary-windows-preview.ps1")
    assert str(face_runtime.resolve()) in command
    assert str(face_preview.resolve()) in command

    face_preview.mkdir()
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="preview output already exists"):
        executor.build_execution(
            plan("face-secondary-review-composition", missing=["face-secondary"]),
            context={"preview_job_id": "preview-42"},
            repo_root=root,
        )


def test_hfn_requires_explicit_context_and_human_review_remains_operator_stop(tmp_path: Path) -> None:
    root = repo(tmp_path)
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"package")
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="appearance source package"):
        executor.build_execution(
            plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
            context={"package_path": str(package)},
            repo_root=root,
        )

    human = executor.build_execution(
        plan("human-visual-qa", missing=[]),
        context={},
        repo_root=root,
    )
    assert human["mode"] == "operator-stop"
    assert human["commands"] == []
    assert human["operator_input_required"] is True


def _hfn_context(tmp_path: Path) -> dict[str, str]:
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"package")
    source = tmp_path / "source.mrbody"
    source.write_bytes(b"source")
    return {
        "package_path": str(package),
        "appearance_source_package_path": str(source),
        "hfn_root": str(tmp_path / "people"),
        "person_id": "person-" + "1" * 32,
        "body_revision": "body-r0001",
        "render_dir": str(tmp_path / "render"),
        "human_review_dir": str(tmp_path / "human-review"),
    }


def test_hfn_preserves_appearance_authority_and_stops_at_source_selection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    context = _hfn_context(tmp_path)
    appearance_sha = "d" * 64
    monkeypatch.setattr(executor, "_appearance_transfer_authority", lambda path: (
        appearance_sha,
        "performer-42",
        executor._sha256_file(path),
    ))
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **kwargs: {
        "gates": [{"id": executor.HFN_CANDIDATE_GATE, "state": "required", "reason": "source selection required"}],
        "actions": {executor.HFN_CANDIDATE_GATE: {
            "gate": executor.HFN_CANDIDATE_GATE,
            "command": ".\\prepare-hands-feet-nails-detail-candidate.ps1 -CaptureId <CAPTURE_ID> -UvEvidence <UV_EVIDENCE_PATH>",
            "operator_input_required": True,
            "reason": "Select exact source-grounded HFN evidence.",
        }},
    })

    result = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
        context=context,
        repo_root=root,
    )
    assert result["mode"] == "operator-stop"
    assert result["commands"] == []
    assert result["operator_input_required"] is True
    assert "<CAPTURE_ID>" in result["operator_command"]
    assert "<UV_EVIDENCE_PATH>" in result["operator_command"]
    assert result["appearance_transfer_sha256"] == appearance_sha
    assert result["reprobe_required_after_execution"] is False
    assert result["production_activation"] is False


def test_hfn_rejects_appearance_transfer_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    context = _hfn_context(tmp_path)
    calls = iter([
        ("a" * 64, "performer-42", executor._sha256_file(Path(context["appearance_source_package_path"]))),
        ("b" * 64, "performer-42", PACKAGE_SHA),
    ])
    monkeypatch.setattr(executor, "_appearance_transfer_authority", lambda _path: next(calls))
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="changed canonical appearanceTransfer authority"):
        executor.build_execution(
            plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
            context=context,
            repo_root=root,
        )


@pytest.mark.parametrize(
    ("gate_id", "script"),
    [
        (executor.HFN_CANDIDATE_GATE, ".\\prepare-hands-feet-nails-fingernail-geometry-candidate.ps1"),
        (executor.HFN_CANDIDATE_GATE, ".\\prepare-hands-feet-nails-toenail-geometry-candidate.ps1"),
        (executor.HFN_RENDER_GATE, ".\\prepare-hands-feet-nails-render-review.ps1"),
    ],
)
def test_hfn_executes_exactly_one_canonical_machine_step(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, gate_id: str, script: str) -> None:
    root = repo(tmp_path)
    context = _hfn_context(tmp_path)
    appearance_sha = "d" * 64
    monkeypatch.setattr(executor, "_appearance_transfer_authority", lambda path: (
        appearance_sha,
        "performer-42",
        executor._sha256_file(path),
    ))
    command = script + " -Root 'C:\\hfn'"
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **kwargs: {
        "gates": [{"id": gate_id, "state": "required", "reason": "machine gate"}],
        "actions": {gate_id: {
            "gate": gate_id,
            "command": command,
            "operator_input_required": False,
            "reason": "Run one canonical HFN machine step.",
        }},
    })
    result = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
        context=context,
        repo_root=root,
    )
    assert result["mode"] == "machine-executable"
    assert result["commands"] == [["pwsh", "-NoProfile", "-Command", command]]
    assert result["hfn_gate"] == gate_id
    assert result["hfn_status_reinspect_required_after_execution"] is True
    assert result["reprobe_required_after_execution"] is True
    assert result["human_visual_authority_required"] is True
    assert result["production_activation"] is False


def test_hfn_human_review_never_auto_executes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    context = _hfn_context(tmp_path)
    monkeypatch.setattr(executor, "_appearance_transfer_authority", lambda path: (
        "d" * 64,
        "performer-42",
        executor._sha256_file(path),
    ))
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **kwargs: {
        "gates": [
            {"id": executor.HFN_CANDIDATE_GATE, "state": "pass"},
            {"id": executor.HFN_RENDER_GATE, "state": "pass"},
            {"id": executor.HFN_HUMAN_GATE, "state": "required", "reason": "human review"},
        ],
        "actions": {executor.HFN_HUMAN_GATE: {
            "gate": executor.HFN_HUMAN_GATE,
            "command": ".\\record-high-fidelity-hfn-review.ps1 -ConfirmDetailChecklist",
            "operator_input_required": True,
            "reason": "Human HFN review is required.",
        }},
    })
    result = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
        context=context,
        repo_root=root,
    )
    assert result["mode"] == "operator-stop"
    assert result["commands"] == []
    assert "record-high-fidelity-hfn-review.ps1" in result["operator_command"]
    assert result["reprobe_required_after_execution"] is False


def test_execute_runs_exactly_one_command_and_requires_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    execution = {
        "mode": "machine-executable",
        "commands": [["pwsh", "-NoProfile", "-File", "operator.ps1"]],
    }
    monkeypatch.setattr(executor.os, "name", "nt")
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def runner(argv: list[str], *, check: bool):
        assert check is False
        calls.append(argv)
        return Result()

    result = executor.execute(execution, runner=runner)
    assert calls == [["pwsh", "-NoProfile", "-File", "operator.ps1"]]
    assert result["executed"] is True
    assert result["exit_code"] == 0

    with pytest.raises(executor.FidelityComponentGapExecutionError, match="operator/human input"):
        executor.execute({"mode": "operator-stop", "commands": []}, runner=runner)
