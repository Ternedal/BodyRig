from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.fidelity_component_gap_executor as executor


REVISION = "a" * 40
PACKAGE_SHA = hashlib.sha256(b"package").hexdigest()
FINE_AUTHORITY_SHA = "1" * 64
FINE_ATTESTATION_SHA = "2" * 64


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
        "fine_identity_authority_sha256": FINE_AUTHORITY_SHA,
        "fine_identity_attestation_sha256": FINE_ATTESTATION_SHA,
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
            "fine_identity_authority_sha256": FINE_AUTHORITY_SHA,
            "fine_identity_attestation_sha256": FINE_ATTESTATION_SHA,
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
            "fine_identity_authority_sha256": FINE_AUTHORITY_SHA,
            "fine_identity_attestation_sha256": FINE_ATTESTATION_SHA,
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
        "fine_identity_authority_sha256": FINE_AUTHORITY_SHA,
        "fine_identity_attestation_sha256": FINE_ATTESTATION_SHA,
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


def test_hfn_and_human_review_are_hard_operator_stops(tmp_path: Path) -> None:
    root = repo(tmp_path)
    hfn = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
        context={},
        repo_root=root,
    )
    assert hfn["mode"] == "operator-stop"
    assert hfn["commands"] == []
    assert hfn["operator_input_required"] is True
    assert hfn["reprobe_required_after_execution"] is False
    assert hfn["production_activation"] is False

    human = executor.build_execution(
        plan("human-visual-qa", missing=[]),
        context={},
        repo_root=root,
    )
    assert human["mode"] == "operator-stop"
    assert human["commands"] == []
    assert human["operator_input_required"] is True


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


def _hfn_context(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    package = tmp_path / "hfn-source.mrbody"
    package.write_bytes(b"package")
    root = tmp_path / "hfn-library"
    root.mkdir()
    render_dir = root / "render-review"
    human_dir = root / "human-review"
    return {
        "package_path": str(package),
        "hfn_root": str(root),
        "person_id": "person-" + "1" * 32,
        "body_revision": "body-r0007",
        "hfn_render_dir": str(render_dir),
        "hfn_human_review_dir": str(human_dir),
    }, package, root


def test_hfn_exact_source_selection_and_human_review_remain_operator_stops(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    context, package, _hfn_root = _hfn_context(tmp_path)
    source_action = {
        "gate": executor.HFN_CANDIDATE_GATE,
        "command": ".\\prepare-hands-feet-nails-detail-candidate.ps1 -CaptureId <CAPTURE_ID> -UvEvidence <UV_EVIDENCE_PATH>",
        "operator_input_required": True,
        "reason": "select exact HFN source evidence",
    }
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **_kwargs: {
        "actions": {executor.HFN_CANDIDATE_GATE: source_action},
        "package_path": package,
        "package_sha256": PACKAGE_SHA,
    })
    stopped = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
        context=context,
        repo_root=root,
    )
    assert stopped["mode"] == "operator-stop"
    assert stopped["hfn_gate"] == executor.HFN_CANDIDATE_GATE
    assert stopped["operator_command"] == source_action["command"]
    assert stopped["commands"] == []
    assert stopped["reprobe_required_after_execution"] is False

    human_action = {
        "gate": executor.HFN_HUMAN_GATE,
        "command": ".\\record-high-fidelity-hfn-review.ps1 -ConfirmDetailChecklist -QualityNote <QUALITY_NOTE>",
        "operator_input_required": True,
        "reason": "human HFN review required",
    }
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **_kwargs: {
        "actions": {executor.HFN_HUMAN_GATE: human_action},
        "package_path": package,
        "package_sha256": PACKAGE_SHA,
    })
    stopped = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
        context=context,
        repo_root=root,
    )
    assert stopped["mode"] == "operator-stop"
    assert stopped["hfn_gate"] == executor.HFN_HUMAN_GATE
    assert stopped["operator_command"] == human_action["command"]
    assert stopped["production_activation"] is False


def test_hfn_source_bound_geometry_substeps_are_machine_executable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    context, package, _hfn_root = _hfn_context(tmp_path)
    candidate = {
        "capture_id": "hfncap-" + "2" * 32,
        "candidate_id": "hfncand-" + "3" * 32,
    }
    action = {
        "gate": executor.HFN_CANDIDATE_GATE,
        "command": ".\\prepare-hands-feet-nails-fingernail-geometry-candidate.ps1 ...",
        "operator_input_required": False,
        "reason": "materialize fingernails",
    }
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **_kwargs: {
        "actions": {executor.HFN_CANDIDATE_GATE: action},
        "package_path": package,
        "package_sha256": PACKAGE_SHA,
        "candidate": candidate,
    })
    result = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
        context=context,
        repo_root=root,
    )
    assert result["mode"] == "machine-executable"
    assert result["hfn_substep"] == "fingernail-geometry"
    assert result["commands"][0][3] == str(root / "prepare-hands-feet-nails-fingernail-geometry-candidate.ps1")
    assert result["reprobe_required_after_execution"] is True

    toenail_candidate = {**candidate, "fingernail_geometry_package_sha256": "4" * 64}
    toenail_action = {**action, "command": ".\\prepare-hands-feet-nails-toenail-geometry-candidate.ps1 ...", "reason": "materialize toenails"}
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **_kwargs: {
        "actions": {executor.HFN_CANDIDATE_GATE: toenail_action},
        "package_path": package,
        "package_sha256": PACKAGE_SHA,
        "candidate": toenail_candidate,
    })
    result = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["toenails"]),
        context=context,
        repo_root=root,
    )
    assert result["hfn_substep"] == "toenail-geometry"
    assert result["commands"][0][3] == str(root / "prepare-hands-feet-nails-toenail-geometry-candidate.ps1")


def test_hfn_source_bound_render_review_is_machine_executable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    context, package, _hfn_root = _hfn_context(tmp_path)
    action = {
        "gate": executor.HFN_RENDER_GATE,
        "command": ".\\prepare-hands-feet-nails-render-review.ps1 ...",
        "operator_input_required": False,
        "reason": "render exact HFN candidate",
    }
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **_kwargs: {
        "actions": {executor.HFN_RENDER_GATE: action},
        "package_path": package,
        "package_sha256": PACKAGE_SHA,
        "candidate": {"candidate_id": "hfncand-" + "3" * 32},
    })
    result = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
        context=context,
        repo_root=root,
    )
    assert result["mode"] == "machine-executable"
    assert result["hfn_substep"] == "render-review"
    command = result["commands"][0]
    assert command[3] == str(root / "prepare-hands-feet-nails-render-review.ps1")
    assert str(package.resolve()) in command
    assert str(Path(context["hfn_render_dir"]).resolve()) in command
    assert result["production_activation"] is False


def test_hfn_context_rejects_cross_package_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    context, package, _hfn_root = _hfn_context(tmp_path)
    package.write_bytes(b"wrong-package")
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **_kwargs: pytest.fail("continuation must not run"))
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="differ from the Unity gap-plan package SHA"):
        executor.build_execution(
            plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
            context=context,
            repo_root=root,
        )


def test_cli_execute_surfaces_operator_stop_without_calling_execute(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(executor, "_read_json", lambda *args, **kwargs: {})
    stop = {
        "mode": "operator-stop",
        "commands": [],
        "operator_input_required": True,
        "reason": "human/source input required",
    }
    monkeypatch.setattr(executor, "build_execution", lambda *args, **kwargs: dict(stop))

    def forbidden(*args, **kwargs):
        raise AssertionError("operator-stop must never reach execute()")

    monkeypatch.setattr(executor, "execute", forbidden)
    rc = executor.main(["--plan", "plan.json", "--context", "context.json", "--execute"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == stop


def test_cli_execute_runs_machine_route_once(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(executor, "_read_json", lambda *args, **kwargs: {})
    route = {
        "mode": "machine-executable",
        "commands": [["pwsh", "-NoProfile", "-File", "operator.ps1"]],
        "operator_input_required": False,
    }
    monkeypatch.setattr(executor, "build_execution", lambda *args, **kwargs: dict(route))
    calls = []

    def fake_execute(value, **kwargs):
        calls.append(dict(value))
        return {**dict(value), "executed": True, "exit_code": 0}

    monkeypatch.setattr(executor, "execute", fake_execute)
    rc = executor.main(["--plan", "plan.json", "--context", "context.json", "--execute"])
    assert rc == 0
    assert calls == [route]
    output = json.loads(capsys.readouterr().out)
    assert output["executed"] is True
    assert output["exit_code"] == 0
