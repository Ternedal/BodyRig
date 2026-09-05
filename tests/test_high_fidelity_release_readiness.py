from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import bodyrig.high_fidelity_release_readiness as readiness


JOB_ID = "hfpreview-" + "b" * 32


def _base(package: Path | None, *, complete: bool) -> dict:
    return {
        "format": "bodyrig-high-fidelity-continuation-status",
        "version": 1,
        "preview_job_id": JOB_ID,
        "state": "complete" if complete else "incomplete",
        "gates": [{"id": "preview", "label": "preview", "state": "pass", "passed": True, "reason": "", "evidence": {}}],
        "next_gate": None if complete else {"gate": "hair_promotion"},
        "current_package_path": str(package) if package is not None else None,
        "current_package_sha256": hashlib.sha256(package.read_bytes()).hexdigest() if package is not None and package.is_file() else None,
        "components": {"body_anatomy": "complete"} if complete else {},
        "high_fidelity_complete": complete,
        "high_fidelity_human_review_required": complete,
        "physical_windows_acceptance_required": True,
        "quest_acceptance_required": True,
        "final_release_required": True,
        "production_ready": False,
        "production_activation": False,
        "final_audit": None,
    }


def _review_pass() -> dict:
    return {
        "state": "pass",
        "passed": True,
        "reviewed_utc": "2026-09-04T21:00:00Z",
        "policy_revision": "bodyrig-high-fidelity-human-review-v1",
    }


def test_incomplete_component_package_does_not_invent_final_human_review(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(None, complete=False))

    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["component_package_complete"] is False
    assert result["high_fidelity_human_review_complete"] is False
    assert result["software_ready_for_physical_acceptance"] is False
    assert result["next_gate"]["gate"] == "hair_promotion"
    assert result["production_ready"] is False
    assert result["production_activation"] is False


def test_component_complete_requires_review_of_exact_promoted_package(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-package")
    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(package, complete=True))
    monkeypatch.setattr(
        readiness,
        "high_fidelity_human_review_status",
        lambda _package: {"state": "required", "passed": False, "reason": "explicit review required"},
    )

    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["state"] == "human-review-required"
    assert result["component_package_complete"] is True
    assert result["high_fidelity_human_review_complete"] is False
    assert result["software_ready_for_physical_acceptance"] is False
    assert result["gates"][-1]["id"] == "high_fidelity_human_review"
    assert result["gates"][-1]["state"] == "required"
    assert result["next_gate"]["gate"] == "high_fidelity_human_review"
    assert f"-PackagePath '{package.resolve()}'" in result["next_gate"]["command"]
    assert "-ConfirmQualityChecklist" in result["next_gate"]["command"]
    assert result["production_ready"] is False


def test_human_review_pass_requires_fresh_promoted_package_gate_a(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-package")
    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(package, complete=True))
    monkeypatch.setattr(readiness, "high_fidelity_human_review_status", lambda _package: _review_pass())
    monkeypatch.setattr(
        readiness,
        "physical_acceptance_status",
        lambda *args, **kwargs: {
            "state": "required",
            "gate": "physical-gate-a",
            "acceptance_dir": str(tmp_path / "physical-acceptance"),
            "message": "fresh Gate A required",
            "next_command": f".\\prepare-high-fidelity-physical-acceptance.ps1 -PreviewJobId '{JOB_ID}'",
            "production_activation": False,
        },
    )

    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["state"] == "physical-gate-a-required"
    assert result["component_package_complete"] is True
    assert result["high_fidelity_human_review_complete"] is True
    assert result["high_fidelity_human_review_required"] is False
    assert result["software_ready_for_physical_acceptance"] is True
    assert result["gates"][-1]["id"] == "physical_gate_a"
    assert result["gates"][-1]["state"] == "required"
    assert result["next_gate"]["gate"] == "physical_gate_a"
    assert "prepare-high-fidelity-physical-acceptance.ps1" in result["next_gate"]["command"]
    assert result["physical_windows_acceptance_required"] is True
    assert result["quest_acceptance_required"] is True
    assert result["final_release_required"] is True
    assert result["production_ready"] is False
    assert result["production_activation"] is False


@pytest.mark.parametrize(
    ("physical", "expected_gate", "windows_required", "quest_required", "release_required"),
    [
        (
            {
                "state": "ready",
                "gate": "windows-probe",
                "acceptance_dir": "C:/hf/physical",
                "bodyrig_revision": "c" * 40,
                "message": "run Windows probe",
                "next_command": ".\\run-windows-renderer-probe.ps1",
                "production_activation": False,
            },
            "physical_windows_acceptance",
            True,
            True,
            True,
        ),
        (
            {
                "state": "ready",
                "gate": "quest-probe",
                "acceptance_dir": "C:/hf/physical",
                "bodyrig_revision": "c" * 40,
                "message": "run Quest probe",
                "next_command": ".\\run-quest-renderer-probe.ps1",
                "production_activation": False,
            },
            "physical_quest_acceptance",
            False,
            True,
            True,
        ),
        (
            {
                "state": "ready",
                "gate": "release",
                "acceptance_dir": "C:/hf/physical",
                "bodyrig_revision": "c" * 40,
                "message": "complete release",
                "next_command": ".\\complete-acceptance.ps1",
                "production_activation": False,
            },
            "final_release",
            False,
            False,
            True,
        ),
    ],
)
def test_physical_state_machine_is_exposed_without_inventing_passes(
    monkeypatch,
    tmp_path: Path,
    physical: dict,
    expected_gate: str,
    windows_required: bool,
    quest_required: bool,
    release_required: bool,
) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-package")
    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(package, complete=True))
    monkeypatch.setattr(readiness, "high_fidelity_human_review_status", lambda _package: _review_pass())
    monkeypatch.setattr(readiness, "physical_acceptance_status", lambda *args, **kwargs: physical)

    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["next_gate"]["gate"] == expected_gate
    assert result["physical_windows_acceptance_required"] is windows_required
    assert result["quest_acceptance_required"] is quest_required
    assert result["final_release_required"] is release_required
    assert result["production_ready"] is False
    assert result["production_activation"] is False


def test_canonical_final_release_is_only_path_to_production_ready(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-package")
    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(package, complete=True))
    monkeypatch.setattr(readiness, "high_fidelity_human_review_status", lambda _package: _review_pass())
    monkeypatch.setattr(
        readiness,
        "physical_acceptance_status",
        lambda *args, **kwargs: {
            "state": "complete",
            "gate": "release",
            "acceptance_dir": "C:/hf/physical",
            "bodyrig_revision": "c" * 40,
            "message": "canonical final release PASS",
            "next_command": None,
            "production_activation": True,
        },
    )

    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["state"] == "production-ready"
    assert result["physical_windows_acceptance_required"] is False
    assert result["quest_acceptance_required"] is False
    assert result["final_release_required"] is False
    assert result["next_gate"] is None
    assert result["production_ready"] is True
    assert result["production_activation"] is True
    assert [gate["id"] for gate in result["gates"][-4:]] == [
        "physical_gate_a",
        "physical_windows_acceptance",
        "physical_quest_acceptance",
        "final_release",
    ]
    assert all(gate["state"] == "pass" for gate in result["gates"][-4:])


def test_missing_component_complete_package_fails_closed(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "missing.mrbody"
    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(package, complete=True))

    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["state"] == "blocked"
    assert result["gates"][-1]["id"] == "high_fidelity_human_review"
    assert result["gates"][-1]["state"] == "invalid"
    assert result["software_ready_for_physical_acceptance"] is False
    assert result["production_ready"] is False


@pytest.mark.parametrize("change", ["before", "during", "deleted", "missing_sha"])
def test_release_readiness_rejects_stale_package_even_when_review_passes(monkeypatch, tmp_path: Path, change: str) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact reviewed package")
    base = _base(package, complete=True)
    if change == "before":
        package.write_bytes(b"another reviewed package")
    elif change == "missing_sha":
        base["current_package_sha256"] = None
    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: base)

    def review(path: Path) -> dict:
        if change == "during":
            path.write_bytes(b"another reviewed package")
        elif change == "deleted":
            path.unlink()
        return {"state": "pass", "passed": True}

    monkeypatch.setattr(readiness, "high_fidelity_human_review_status", review)
    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["state"] == "blocked"
    assert result["component_package_complete"] is False
    assert result["high_fidelity_complete"] is False
    assert result["high_fidelity_human_review_complete"] is False
    assert result["software_ready_for_physical_acceptance"] is False
    assert result["next_gate"] is None
    assert result["production_activation"] is False


def test_corrupt_final_review_keeps_package_complete_but_blocks_readiness(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact reviewed package")
    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(package, complete=True))

    def corrupt(_path: Path) -> dict:
        raise readiness.HighFidelityHumanReviewError("review no longer matches current component-state authority")

    monkeypatch.setattr(readiness, "high_fidelity_human_review_status", corrupt)
    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["state"] == "blocked"
    assert result["component_package_complete"] is True
    assert result["software_ready_for_physical_acceptance"] is False
    assert result["gates"][-1]["state"] == "invalid"
    assert result["next_gate"] is None


def test_corrupt_physical_handoff_blocks_without_rerun_command(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-package")
    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(package, complete=True))
    monkeypatch.setattr(readiness, "high_fidelity_human_review_status", lambda _package: _review_pass())
    monkeypatch.setattr(
        readiness,
        "physical_acceptance_status",
        lambda *args, **kwargs: {
            "state": "invalid",
            "gate": "physical-gate-a",
            "acceptance_dir": "C:/hf/physical",
            "message": "handoff receipt hash changed",
            "next_command": None,
            "production_activation": False,
        },
    )

    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["state"] == "blocked"
    assert result["gates"][-1]["id"] == "physical_gate_a"
    assert result["gates"][-1]["state"] == "invalid"
    assert result["next_gate"] is None
    assert result["production_ready"] is False
