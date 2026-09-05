from __future__ import annotations

import hashlib
from pathlib import Path

import bodyrig.high_fidelity_release_readiness as readiness


JOB_ID = "hfpreview-" + "f" * 32


def _base(package: Path) -> dict:
    return {
        "format": "bodyrig-high-fidelity-continuation-status",
        "version": 1,
        "preview_job_id": JOB_ID,
        "state": "complete",
        "gates": [
            {
                "id": "preview",
                "label": "preview",
                "state": "pass",
                "passed": True,
                "reason": "",
                "evidence": {},
            }
        ],
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


def _must_not_read_source_review(*_args, **_kwargs):
    raise AssertionError("live source human-review sidecar must not be authoritative after finalized Gate A")


def test_finalized_gate_a_uses_frozen_review_without_reading_live_source_sidecar(
    monkeypatch,
    tmp_path: Path,
) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-package")
    acceptance = tmp_path / "physical-acceptance"
    acceptance.mkdir()

    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(package))
    monkeypatch.setattr(readiness, "physical_acceptance_dir", lambda _job: acceptance)
    monkeypatch.setattr(readiness, "high_fidelity_human_review_status", _must_not_read_source_review)
    monkeypatch.setattr(readiness, "invalid_review_recovery_status", _must_not_read_source_review)
    monkeypatch.setattr(
        readiness,
        "physical_acceptance_status",
        lambda *_args, **_kwargs: {
            "state": "ready",
            "gate": "windows-probe",
            "acceptance_dir": str(acceptance),
            "bodyrig_revision": "a" * 40,
            "message": "run Windows probe",
            "next_command": ".\\run-windows-renderer-probe.ps1",
            "production_activation": False,
        },
    )

    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["state"] == "physical-windows-acceptance-required"
    assert result["next_gate"]["gate"] == "physical_windows_acceptance"
    review_gate = next(gate for gate in result["gates"] if gate["id"] == "high_fidelity_human_review")
    assert review_gate["state"] == "pass"
    assert review_gate["evidence"]["frozen_by_gate_a"] is True
    assert review_gate["evidence"]["acceptance_dir"] == str(acceptance)
    assert result["high_fidelity_human_review_complete"] is True
    assert result["high_fidelity_human_review_required"] is False
    assert result["production_activation"] is False


def test_invalid_frozen_gate_a_review_blocks_without_source_review_recovery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-package")
    acceptance = tmp_path / "physical-acceptance"
    acceptance.mkdir()

    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(package))
    monkeypatch.setattr(readiness, "physical_acceptance_dir", lambda _job: acceptance)
    monkeypatch.setattr(readiness, "high_fidelity_human_review_status", _must_not_read_source_review)
    monkeypatch.setattr(readiness, "invalid_review_recovery_status", _must_not_read_source_review)
    monkeypatch.setattr(
        readiness,
        "physical_acceptance_status",
        lambda *_args, **_kwargs: {
            "state": "invalid",
            "gate": "physical-gate-a",
            "acceptance_dir": str(acceptance),
            "bodyrig_revision": "a" * 40,
            "message": "frozen final human-review hash changed",
            "next_command": None,
            "production_activation": False,
        },
    )

    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["state"] == "blocked"
    assert result["next_gate"] is None
    assert all(gate["id"] != "high_fidelity_human_review_recovery" for gate in result["gates"])
    review_gate = next(gate for gate in result["gates"] if gate["id"] == "high_fidelity_human_review")
    assert review_gate["state"] == "invalid"
    assert review_gate["evidence"]["frozen_by_gate_a"] is True
    assert "recovery is disabled after Gate A" in review_gate["reason"]
    physical_gate = result["gates"][-1]
    assert physical_gate["id"] == "physical_gate_a"
    assert physical_gate["state"] == "invalid"
    assert "frozen final human-review hash changed" in physical_gate["reason"]
    assert result["high_fidelity_human_review_complete"] is False
    assert result["high_fidelity_human_review_required"] is False
    assert result["software_ready_for_physical_acceptance"] is False
    assert result["production_ready"] is False
    assert result["production_activation"] is False


def test_gate_a_finalized_during_source_review_read_wins_before_new_review_command(
    monkeypatch,
    tmp_path: Path,
) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-package")
    acceptance = tmp_path / "physical-acceptance"

    monkeypatch.setattr(readiness, "inspect_continuation", lambda _job: _base(package))
    monkeypatch.setattr(readiness, "physical_acceptance_dir", lambda _job: acceptance)

    def review_required(_package: Path) -> dict:
        acceptance.mkdir()
        return {"state": "required", "passed": False, "reason": "source review missing"}

    monkeypatch.setattr(readiness, "high_fidelity_human_review_status", review_required)
    monkeypatch.setattr(
        readiness,
        "physical_acceptance_status",
        lambda *_args, **_kwargs: {
            "state": "ready",
            "gate": "windows-probe",
            "acceptance_dir": str(acceptance),
            "bodyrig_revision": "b" * 40,
            "message": "run Windows probe",
            "next_command": ".\\run-windows-renderer-probe.ps1",
            "production_activation": False,
        },
    )

    result = readiness.inspect_release_readiness(JOB_ID)

    assert result["state"] == "physical-windows-acceptance-required"
    assert result["next_gate"]["gate"] == "physical_windows_acceptance"
    assert "record-high-fidelity-human-review.ps1" not in str(result["next_gate"].get("command") or "")
    review_gate = next(gate for gate in result["gates"] if gate["id"] == "high_fidelity_human_review")
    assert review_gate["state"] == "pass"
    assert review_gate["evidence"]["frozen_by_gate_a"] is True
