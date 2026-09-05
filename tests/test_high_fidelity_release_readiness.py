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


def test_human_review_pass_only_grants_software_readiness_for_physical_acceptance(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-package")
    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(package, complete=True))
    monkeypatch.setattr(
        readiness,
        "high_fidelity_human_review_status",
        lambda _package: {
            "state": "pass",
            "passed": True,
            "reviewed_utc": "2026-09-04T21:00:00Z",
            "policy_revision": "bodyrig-high-fidelity-human-review-v1",
        },
    )

    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["state"] == "software-ready-for-physical-acceptance"
    assert result["component_package_complete"] is True
    assert result["high_fidelity_human_review_complete"] is True
    assert result["high_fidelity_human_review_required"] is False
    assert result["software_ready_for_physical_acceptance"] is True
    assert result["gates"][-1]["state"] == "pass"
    assert result["next_gate"]["gate"] == "physical_windows_acceptance"
    assert result["physical_windows_acceptance_required"] is True
    assert result["quest_acceptance_required"] is True
    assert result["final_release_required"] is True
    assert result["production_ready"] is False
    assert result["production_activation"] is False
    assert result["gates"][-1]["evidence"]["package_sha256"] == hashlib.sha256(package.read_bytes()).hexdigest()


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
