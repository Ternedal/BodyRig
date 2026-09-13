from pathlib import Path

import bodyrig.rig_window_component_authority as component


HEAD = "a" * 40
OLD = "b" * 40
PERSON = "person-" + "1" * 32
BODY_JOB = "job-" + "2" * 32
PREVIEW = "hfpreview-" + "3" * 32


def _plan() -> dict[str, object]:
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
        "next_command": ".\\run-profiled-fidelity-convergence.ps1 -PerformerId '42' -BodyId 'lauren-phillips-test-02' -KeepPrivateWorkspaces",
    }


def _succeeded_preview() -> dict[str, object]:
    return {
        "job_id": PREVIEW,
        "person_id": PERSON,
        "body_job_id": BODY_JOB,
        "body_revision": "body-revision-test",
        "canonical_body_id": "lauren-phillips-test-02",
        "target_family": "female",
        "status": "succeeded",
        "stage": "review-ready",
        "bodyrig_revision": OLD,
        "created_utc": "2026-09-13T07:30:00Z",
        "completed_utc": "2026-09-13T07:30:00Z",
    }


def test_rejection_rebuild_seed_is_stable_non_default_and_authority_bound() -> None:
    first = component._rejection_rebuild_seed(
        body_job_id=BODY_JOB,
        preview_job_id=PREVIEW,
        revision=OLD,
    )
    repeated = component._rejection_rebuild_seed(
        body_job_id=BODY_JOB,
        preview_job_id=PREVIEW,
        revision=OLD,
    )
    different_preview = component._rejection_rebuild_seed(
        body_job_id=BODY_JOB,
        preview_job_id="hfpreview-" + "4" * 32,
        revision=OLD,
    )

    assert first == repeated
    assert first != 1337
    assert 0 <= first <= 2147483647
    assert different_preview != first


def test_repeated_hair_eye_small_detail_failure_escalates_past_succeeded_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(component.authority, "build_plan", lambda **_kwargs: _plan())
    monkeypatch.setattr(
        component,
        "_validated_failed_checks",
        lambda _acceptance: frozenset(
            {"hair_appearance", "eye_appearance", "small_anatomical_detail"}
        ),
    )
    monkeypatch.setattr(
        component,
        "list_recent_previews",
        lambda **_kwargs: [_succeeded_preview()],
    )

    plan = component.build_plan(
        repo_root=tmp_path,
        performer_id="42",
        body_id="lauren-phillips-test-02",
    )

    assert plan["path"] == "human-fidelity-rework"
    assert plan["preview_job_id"] == PREVIEW
    assert plan["component_failed_checks"] == [
        "eye_appearance",
        "hair_appearance",
        "small_anatomical_detail",
    ]
    assert plan["expensive_reconstruction_rerun"] is True
    assert plan["fitter_rerun"] is True
    assert plan["operator_input_required"] is False
    expected_seed = component._rejection_rebuild_seed(
        body_job_id=BODY_JOB,
        preview_job_id=PREVIEW,
        revision=OLD,
    )
    assert plan["rebuild_seed"] == expected_seed
    command = str(plan["next_command"])
    assert "run-profiled-fidelity-convergence.ps1" in command
    assert f"-BaseSithSeed {expected_seed}" in command
    assert "-BaseSithSeed 1337" not in command
    assert "high-fidelity-physical-status.ps1" not in command
    assert "repeat the rejected visual base" in str(plan["rationale"])
