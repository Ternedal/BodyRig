from __future__ import annotations

import hashlib
from pathlib import Path

import bodyrig.high_fidelity_release_readiness as readiness


JOB_ID = "hfpreview-" + "e" * 32


def _base(package: Path) -> dict:
    return {
        "format": "bodyrig-high-fidelity-continuation-status",
        "version": 1,
        "preview_job_id": JOB_ID,
        "state": "complete",
        "gates": [{"id": "preview", "label": "preview", "state": "pass", "passed": True, "reason": "", "evidence": {}}],
        "next_gate": None,
        "current_package_path": str(package),
        "current_package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "components": {"body_anatomy": "complete"},
        "high_fidelity_complete": True,
        "high_fidelity_human_review_required": True,
        "physical_windows_acceptance_required": True,
        "quest_acceptance_required": True,
        "final_release_required": True,
        "production_ready": False,
        "production_activation": False,
        "final_audit": None,
    }


def test_invalid_review_routes_to_preserving_recovery_gate(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-package")
    package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
    receipt_sha = "a" * 64
    invalid_path = tmp_path / "invalid-review.json"
    archive_path = tmp_path / f"invalid-review.invalid-{receipt_sha}.json"

    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(package))

    def invalid(_package: Path) -> dict:
        raise readiness.HighFidelityHumanReviewError("human review quality note is still a generated placeholder")

    monkeypatch.setattr(readiness, "high_fidelity_human_review_status", invalid)
    monkeypatch.setattr(
        readiness,
        "invalid_review_recovery_status",
        lambda _package: {
            "available": True,
            "reason": "human review quality note is still a generated placeholder",
            "package_sha256": package_sha,
            "review_path": str(invalid_path),
            "receipt_sha256": receipt_sha,
            "archive_path": str(archive_path),
        },
    )

    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["state"] == "human-review-recovery-required"
    assert result["component_package_complete"] is True
    assert result["high_fidelity_human_review_complete"] is False
    assert result["software_ready_for_physical_acceptance"] is False
    assert result["production_ready"] is False
    assert result["production_activation"] is False
    assert result["gates"][-1]["id"] == "high_fidelity_human_review"
    assert result["gates"][-1]["state"] == "invalid"
    assert result["gates"][-1]["evidence"]["receipt_sha256"] == receipt_sha
    assert result["next_gate"]["gate"] == "high_fidelity_human_review_recovery"
    assert "archive-invalid-high-fidelity-human-review.ps1" in result["next_gate"]["command"]
    assert f"-PackagePath '{package.resolve()}'" in result["next_gate"]["command"]


def test_invalid_review_without_safe_recovery_remains_blocked(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-package")
    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(package))

    def invalid(_package: Path) -> dict:
        raise readiness.HighFidelityHumanReviewError("review is invalid")

    monkeypatch.setattr(readiness, "high_fidelity_human_review_status", invalid)
    monkeypatch.setattr(
        readiness,
        "invalid_review_recovery_status",
        lambda _package: {"available": False, "reason": "no current receipt exists"},
    )

    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["state"] == "blocked"
    assert result["next_gate"] is None
    assert result["production_activation"] is False
