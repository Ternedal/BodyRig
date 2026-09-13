from pathlib import Path

import bodyrig.rig_window_component_authority as component


HEAD = "a" * 40
OLD = "b" * 40
PERSON = "person-" + "1" * 32
BODY_JOB = "job-" + "2" * 32
PREVIEW = "hfpreview-" + "3" * 32


def _plan(*, command: str = ".\\run-profiled-fidelity-convergence.ps1 -PerformerId '42' -BodyId 'lauren-phillips-test-02' -KeepPrivateWorkspaces") -> dict[str, object]:
    return {
        "format": "bodyrig-rig-window-plan",
        "version": 4,
        "read_only": True,
        "state": "ready",
        "priority": 1,
        "progress_rank": 1,
        "path": "human-fidelity-rework",
        "bodyrig_revision": HEAD,
        "scope": {
            "person_id": PERSON,
            "performer_id": "42",
            "body_id": "lauren-phillips-test-02",
        },
        "evidence_revision": OLD,
        "session_report": "/evidence/session.json",
        "acceptance_dir": f"/evidence/{BODY_JOB}/acceptance",
        "gate": "windows-rejected",
        "expensive_reconstruction_rerun": True,
        "fitter_rerun": True,
        "rationale": "body convergence",
        "next_command": command,
    }


def _preview(*, status: str, family: str = "female", revision: str = OLD, created: str = "2026-09-13T07:30:00Z") -> dict[str, object]:
    return {
        "job_id": PREVIEW,
        "person_id": PERSON,
        "body_job_id": BODY_JOB,
        "body_revision": "body-revision-test",
        "canonical_body_id": "lauren-phillips-test-02",
        "target_family": family,
        "status": status,
        "stage": "review-ready" if status == "succeeded" else status,
        "bodyrig_revision": revision,
        "created_utc": created,
        "completed_utc": created if status in {"succeeded", "failed", "interrupted"} else None,
    }


def _install_real_ui_rejection(
    tmp_path: Path,
    monkeypatch,
    *,
    payload_body_id: str = "lauren-phillips-test-02",
) -> Path:
    acceptance = tmp_path / "ui-jobs" / BODY_JOB / "acceptance"
    acceptance.mkdir(parents=True)
    (acceptance / "bodyrig-acceptance.json").write_text("{}\n", encoding="utf-8")
    rows = [
        {
            "job_id": BODY_JOB,
            "person_id": PERSON,
            "status": "succeeded",
            "error": "",
            "resume_source_error": "",
            "acceptance_dir": str(acceptance),
            "bodyrig_revision": OLD,
            "stamp": "2026-09-13T07:00:00Z",
        }
    ]
    base = component.authority.policy.base
    monkeypatch.setattr(base, "_head", lambda _root: HEAD)
    monkeypatch.setattr(base, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(base, "_job_rows", lambda _root: rows)
    monkeypatch.setattr(base, "resolve_person_scope", lambda **_kwargs: (PERSON, "42"))
    monkeypatch.setattr(base, "_historical_revision_is_safe", lambda _root, revision: revision == OLD)
    monkeypatch.setattr(component.authority.policy, "_scope_sessions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(component.authority, "_automatic_run_candidates", lambda **_kwargs: ([], []))
    monkeypatch.setattr(
        base,
        "inspect_for_rig_window",
        lambda _acceptance: {
            "state": "blocked",
            "gate": "windows-rejected",
            "body_id": payload_body_id,
            "bodyrig_revision": OLD,
            "progress_rank": 0,
        },
    )
    return acceptance


def test_component_only_rejection_without_preview_emits_revision_bound_mutating_start(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(component.authority, "build_plan", lambda **_kwargs: _plan())
    monkeypatch.setattr(
        component,
        "_validated_failed_checks",
        lambda _acceptance: frozenset({"hair_appearance", "eye_appearance", "face_secondary"}),
    )
    monkeypatch.setattr(component, "list_recent_previews", lambda **_kwargs: [])

    plan = component.build_plan(
        repo_root=tmp_path,
        performer_id="42",
        body_id="lauren-phillips-test-02",
    )

    assert plan["path"] == "high-fidelity-component-rework"
    assert plan["expensive_reconstruction_rerun"] is False
    assert plan["fitter_rerun"] is False
    assert plan["component_failed_checks"] == [
        "eye_appearance",
        "face_secondary",
        "hair_appearance",
    ]
    assert plan["body_job_id"] == BODY_JOB
    assert plan["operator_input_required"] is True
    assert plan["required_operator_input"] == {"target_family": ["female", "male", "neutral"]}
    command = str(plan["next_command"])
    assert "start-high-fidelity-preview-from-body-job.ps1" in command
    assert f"-PersonId '{PERSON}'" in command
    assert f"-BodyJobId '{BODY_JOB}'" in command
    assert "-TargetFamily '<TARGET_FAMILY>'" in command
    assert f"-Revision '{OLD}'" in command
    assert "list-high-fidelity-previews.ps1" not in command
    assert "run-profiled-fidelity-convergence.ps1" not in command


def test_succeeded_preview_reenters_exact_revision_and_routes_to_continuation_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(component.authority, "build_plan", lambda **_kwargs: _plan())
    monkeypatch.setattr(component, "_validated_failed_checks", lambda _acceptance: frozenset({"hair_appearance"}))
    monkeypatch.setattr(component, "list_recent_previews", lambda **_kwargs: [_preview(status="succeeded")])

    plan = component.build_plan(repo_root=tmp_path, performer_id="42", body_id="lauren-phillips-test-02")

    assert plan["preview_job_id"] == PREVIEW
    assert plan["target_family"] == "female"
    assert plan["operator_input_required"] is False
    command = str(plan["next_command"])
    assert f"update-windows.ps1 -Revision '{OLD}' -NoBrowser" in command
    assert f"high-fidelity-physical-status.ps1 -PreviewJobId '{PREVIEW}'" in command
    assert "start-high-fidelity-preview-from-body-job.ps1" not in command


def test_failed_preview_reuses_explicit_family_and_restarts_preview(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(component.authority, "build_plan", lambda **_kwargs: _plan())
    monkeypatch.setattr(component, "_validated_failed_checks", lambda _acceptance: frozenset({"eye_appearance"}))
    monkeypatch.setattr(component, "list_recent_previews", lambda **_kwargs: [_preview(status="failed", family="female")])

    plan = component.build_plan(repo_root=tmp_path, performer_id="42", body_id="lauren-phillips-test-02")

    assert plan["operator_input_required"] is False
    assert plan["target_family"] == "female"
    command = str(plan["next_command"])
    assert "start-high-fidelity-preview-from-body-job.ps1" in command
    assert "-TargetFamily 'female'" in command
    assert f"-Revision '{OLD}'" in command


def test_running_preview_resumes_instead_of_starting_body_convergence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(component.authority, "build_plan", lambda **_kwargs: _plan())
    monkeypatch.setattr(component, "_validated_failed_checks", lambda _acceptance: frozenset({"face_secondary"}))
    monkeypatch.setattr(component, "list_recent_previews", lambda **_kwargs: [_preview(status="running", family="neutral")])

    plan = component.build_plan(repo_root=tmp_path, performer_id="42", body_id="lauren-phillips-test-02")

    assert plan["preview_job_id"] == PREVIEW
    assert plan["target_family"] == "neutral"
    assert "-TargetFamily 'neutral'" in str(plan["next_command"])
    assert "run-profiled-fidelity-convergence.ps1" not in str(plan["next_command"])


def test_preview_from_other_revision_is_not_reused_as_family_authority(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(component.authority, "build_plan", lambda **_kwargs: _plan())
    monkeypatch.setattr(component, "_validated_failed_checks", lambda _acceptance: frozenset({"hair_appearance"}))
    monkeypatch.setattr(component, "list_recent_previews", lambda **_kwargs: [_preview(status="failed", revision="c" * 40)])

    plan = component.build_plan(repo_root=tmp_path, performer_id="42", body_id="lauren-phillips-test-02")

    assert plan["operator_input_required"] is True
    assert "-TargetFamily '<TARGET_FAMILY>'" in str(plan["next_command"])


def test_real_ui_rejection_survives_rank_zero_and_routes_to_mutating_component_start(tmp_path: Path, monkeypatch) -> None:
    acceptance = _install_real_ui_rejection(tmp_path, monkeypatch)
    monkeypatch.setattr(component, "_validated_failed_checks", lambda path: frozenset({"hair_appearance"}) if Path(path) == acceptance else frozenset())
    monkeypatch.setattr(component, "list_recent_previews", lambda **_kwargs: [])

    plan = component.build_plan(
        repo_root=tmp_path,
        performer_id="42",
        body_id="lauren-phillips-test-02",
    )

    assert plan["path"] == "high-fidelity-component-rework"
    assert plan["gate"] == "windows-rejected"
    assert plan["acceptance_dir"] == str(acceptance.resolve())
    assert plan["body_job_id"] == BODY_JOB
    assert plan["evidence_revision"] == OLD
    assert plan["expensive_reconstruction_rerun"] is False
    assert plan["fitter_rerun"] is False
    assert "start-high-fidelity-preview-from-body-job.ps1" in str(plan["next_command"])
    assert f"-PersonId '{PERSON}'" in str(plan["next_command"])
    assert f"-BodyJobId '{BODY_JOB}'" in str(plan["next_command"])


def test_ui_rejection_from_other_body_scope_is_not_reused(tmp_path: Path, monkeypatch) -> None:
    _install_real_ui_rejection(tmp_path, monkeypatch, payload_body_id="some-other-body")

    plan = component.build_plan(
        repo_root=tmp_path,
        performer_id="42",
        body_id="lauren-phillips-test-02",
    )

    assert plan["path"] == "fresh-profiled-physical-preflight"
    assert plan["progress_rank"] == 0
    assert "start-high-fidelity-preview-from-body-job.ps1" not in str(plan.get("next_command") or "")


def test_higher_ranked_valid_evidence_is_not_overridden_by_ui_rejection(tmp_path: Path, monkeypatch) -> None:
    original = {
        **_plan(),
        "path": "existing-gate-a-acceptance",
        "progress_rank": 20,
        "priority": 20,
        "gate": "windows-probe",
        "next_command": ".\\run-reference-windows-renderer-probe.ps1",
    }
    monkeypatch.setattr(component.authority, "build_plan", lambda **_kwargs: original)
    monkeypatch.setattr(
        component,
        "_select_ui_rejection_rework",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("rank-1 rejection must not override higher evidence")),
    )

    plan = component.build_plan(repo_root=tmp_path, performer_id="42", body_id="lauren-phillips-test-02")

    assert plan == original


def test_mixed_component_and_body_rejection_preserves_profiled_convergence(tmp_path: Path, monkeypatch) -> None:
    original = _plan()
    monkeypatch.setattr(component.authority, "build_plan", lambda **_kwargs: original)
    monkeypatch.setattr(
        component,
        "_validated_failed_checks",
        lambda _acceptance: frozenset({"hair_appearance", "upper_body_deformation"}),
    )

    plan = component.build_plan(
        repo_root=tmp_path,
        performer_id="42",
        body_id="lauren-phillips-test-02",
    )

    assert plan == original
    assert "run-profiled-fidelity-convergence.ps1" in str(plan["next_command"])


def test_geometry_only_rejection_preserves_profiled_convergence(tmp_path: Path, monkeypatch) -> None:
    original = _plan()
    monkeypatch.setattr(component.authority, "build_plan", lambda **_kwargs: original)
    monkeypatch.setattr(
        component,
        "_validated_failed_checks",
        lambda _acceptance: frozenset({"geometry_proportions", "upper_body_deformation"}),
    )

    plan = component.build_plan(
        repo_root=tmp_path,
        performer_id="42",
        body_id="lauren-phillips-test-02",
    )

    assert plan == original
    assert "run-profiled-fidelity-convergence.ps1" in str(plan["next_command"])


def test_small_anatomical_detail_fails_closed_until_package_application_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(component.authority, "build_plan", lambda **_kwargs: _plan())
    monkeypatch.setattr(
        component,
        "_validated_failed_checks",
        lambda _acceptance: frozenset({"small_anatomical_detail"}),
    )

    plan = component.build_plan(
        repo_root=tmp_path,
        performer_id="42",
        body_id="lauren-phillips-test-02",
    )

    assert plan["state"] == "blocked"
    assert plan["path"] == "human-fidelity-rework-blocked"
    assert plan["next_command"] is None
    assert plan["unroutable_failed_checks"] == ["small_anatomical_detail"]
    assert plan["expensive_reconstruction_rerun"] is False
    assert plan["fitter_rerun"] is False
    assert "hands/feet/nails" in str(plan["rationale"])


def test_component_rejection_without_exact_person_or_body_job_fails_closed(tmp_path: Path, monkeypatch) -> None:
    candidate = _plan()
    candidate["scope"] = {"person_id": None, "performer_id": "42", "body_id": "lauren-phillips-test-02"}
    monkeypatch.setattr(component.authority, "build_plan", lambda **_kwargs: candidate)
    monkeypatch.setattr(component, "_validated_failed_checks", lambda _acceptance: frozenset({"hair_appearance"}))

    plan = component.build_plan(repo_root=tmp_path, performer_id="42", body_id="lauren-phillips-test-02")

    assert plan["state"] == "blocked"
    assert plan["next_command"] is None
    assert "exact Person/body job/producer revision" in str(plan["rationale"])


def test_unverifiable_rejection_fails_closed_instead_of_guessing_rework(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(component.authority, "build_plan", lambda **_kwargs: _plan())
    monkeypatch.setattr(
        component,
        "_validated_failed_checks",
        lambda _acceptance: (_ for _ in ()).throw(ValueError("tampered rejection")),
    )

    plan = component.build_plan(
        repo_root=tmp_path,
        performer_id="42",
        body_id="lauren-phillips-test-02",
    )

    assert plan["state"] == "blocked"
    assert plan["path"] == "human-fidelity-rework-blocked"
    assert plan["next_command"] is None
    assert "tampered rejection" in str(plan["rationale"])
