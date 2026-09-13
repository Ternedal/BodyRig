import hashlib
from pathlib import Path

import bodyrig.rig_window_hfn_migration_authority as routing


HEAD = "a" * 40
OLD = "b" * 40
PERSON = "person-" + "1" * 32
BODY_JOB = "job-" + "2" * 32
PREVIEW = "hfpreview-" + "3" * 32


def _plan(failed: list[str]) -> dict:
    return {
        "format": "bodyrig-rig-window-plan",
        "version": 4,
        "read_only": True,
        "state": "blocked",
        "progress_rank": 1,
        "path": "human-fidelity-rework-blocked",
        "bodyrig_revision": HEAD,
        "scope": {
            "person_id": PERSON,
            "performer_id": "42",
            "body_id": "lauren-phillips-test-02",
        },
        "evidence_revision": OLD,
        "acceptance_dir": f"/evidence/{BODY_JOB}/acceptance",
        "gate": "windows-rejected",
        "failed_checks": failed,
        "unroutable_failed_checks": ["small_anatomical_detail"],
        "next_command": None,
    }


def _preview(status: str = "succeeded") -> dict:
    return {
        "job_id": PREVIEW,
        "person_id": PERSON,
        "body_job_id": BODY_JOB,
        "target_family": "female",
        "status": status,
        "bodyrig_revision": OLD,
    }


def test_small_detail_with_hair_and_eyes_starts_historical_preview_without_reconstruction(monkeypatch) -> None:
    monkeypatch.setattr(
        routing.component,
        "build_plan",
        lambda **_kwargs: _plan(["hair_appearance", "eye_appearance", "small_anatomical_detail"]),
    )
    monkeypatch.setattr(routing.component, "list_recent_previews", lambda **_kwargs: [])

    result = routing.build_plan(repo_root=Path("."), performer_id="42", body_id="lauren-phillips-test-02")

    assert result["state"] == "ready"
    assert result["path"] == "high-fidelity-component-rework"
    assert result["expensive_reconstruction_rerun"] is False
    assert result["fitter_rerun"] is False
    assert "start-high-fidelity-preview-from-body-job.ps1" in result["next_command"]
    assert "run-profiled-fidelity-convergence.ps1" not in result["next_command"]


def test_small_detail_waits_for_historical_legacy_components(monkeypatch) -> None:
    monkeypatch.setattr(routing.component, "build_plan", lambda **_kwargs: _plan(["small_anatomical_detail"]))
    monkeypatch.setattr(routing.component, "list_recent_previews", lambda **_kwargs: [_preview()])
    monkeypatch.setattr(
        routing.legacy_status,
        "inspect_continuation",
        lambda _job: {"high_fidelity_complete": False},
    )

    result = routing.build_plan(repo_root=Path("."), performer_id="42", body_id="lauren-phillips-test-02")

    command = result["next_command"]
    assert f"update-windows.ps1 -Revision '{OLD}' -NoBrowser" in command
    assert f"high-fidelity-physical-status.ps1 -PreviewJobId '{PREVIEW}'" in command
    assert "prepare-high-fidelity-hfn-migration.ps1" not in command


def test_legacy_complete_routes_to_current_hfn_migration(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"legacy-promoted")
    package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
    monkeypatch.setattr(
        routing.component,
        "build_plan",
        lambda **_kwargs: _plan(["hair_appearance", "eye_appearance", "small_anatomical_detail"]),
    )
    monkeypatch.setattr(routing.component, "list_recent_previews", lambda **_kwargs: [_preview()])
    monkeypatch.setattr(
        routing.legacy_status,
        "inspect_continuation",
        lambda _job: {
            "high_fidelity_complete": True,
            "current_package_path": str(package),
            "current_package_sha256": package_sha,
        },
    )
    monkeypatch.setattr(routing, "read_migration", lambda *_args, **_kwargs: None)

    result = routing.build_plan(repo_root=tmp_path, performer_id="42", body_id="lauren-phillips-test-02")

    assert result["hfn_migration_required"] is True
    assert result["next_command"] == f".\\prepare-high-fidelity-hfn-migration.ps1 -PreviewJobId '{PREVIEW}'"
    assert result["expensive_reconstruction_rerun"] is False


def test_existing_migration_routes_to_bound_integration_revision(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"legacy-promoted")
    package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
    monkeypatch.setattr(routing.component, "build_plan", lambda **_kwargs: _plan(["small_anatomical_detail"]))
    monkeypatch.setattr(routing.component, "list_recent_previews", lambda **_kwargs: [_preview()])
    monkeypatch.setattr(
        routing.legacy_status,
        "inspect_continuation",
        lambda _job: {
            "high_fidelity_complete": True,
            "current_package_path": str(package),
            "current_package_sha256": package_sha,
        },
    )
    monkeypatch.setattr(
        routing,
        "read_migration",
        lambda *_args, **_kwargs: {"integration_bodyrig_revision": HEAD},
    )

    result = routing.build_plan(repo_root=tmp_path, performer_id="42", body_id="lauren-phillips-test-02")

    assert result["hfn_migration_required"] is False
    assert result["hfn_integration_revision"] == HEAD
    assert result["next_command"] == f".\\high-fidelity-hfn-migrated-status.ps1 -PreviewJobId '{PREVIEW}'"


def test_small_detail_mixed_with_deformation_preserves_body_convergence(monkeypatch) -> None:
    monkeypatch.setattr(
        routing.component,
        "build_plan",
        lambda **_kwargs: _plan(["small_anatomical_detail", "upper_body_deformation"]),
    )

    result = routing.build_plan(repo_root=Path("."), performer_id="42", body_id="lauren-phillips-test-02")

    assert result["path"] == "human-fidelity-rework"
    assert result["expensive_reconstruction_rerun"] is True
    assert result["fitter_rerun"] is True
    assert "run-profiled-fidelity-convergence.ps1" in result["next_command"]


def test_hair_only_route_remains_owned_by_existing_component_router(monkeypatch) -> None:
    original = {
        **_plan(["hair_appearance"]),
        "state": "ready",
        "path": "high-fidelity-component-rework",
        "next_command": ".\\existing-component-route.ps1",
    }
    monkeypatch.setattr(routing.component, "build_plan", lambda **_kwargs: original)

    result = routing.build_plan(repo_root=Path("."), performer_id="42", body_id="lauren-phillips-test-02")

    assert result == original
