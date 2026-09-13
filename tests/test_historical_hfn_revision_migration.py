from __future__ import annotations

import hashlib
from pathlib import Path

import bodyrig.high_fidelity_continuation_status as status


JOB_ID = "hfpreview-" + "a" * 32
PERSON = "person-" + "1" * 32
BODY = "body-r0001"
LEGACY_REVISION = "b" * 40
CURRENT_REVISION = "c" * 40


def _legacy_complete(package: Path) -> dict[str, object]:
    package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
    return {
        "format": status.FORMAT,
        "version": status.VERSION,
        "preview_job_id": JOB_ID,
        "state": "complete",
        "gates": [status._gate(name, "pass") for name in status._legacy.GATE_ORDER],
        "next_gate": None,
        "current_package_path": str(package),
        "current_package_sha256": package_sha,
        "components": {"face_secondary": "complete"},
        "high_fidelity_complete": True,
        "high_fidelity_human_review_required": True,
        "physical_windows_acceptance_required": True,
        "quest_acceptance_required": True,
        "final_release_required": True,
        "production_ready": False,
        "production_activation": False,
        "final_audit": {"package_sha256": package_sha},
    }


def _preview() -> dict[str, str]:
    return {
        "person_id": PERSON,
        "body_revision": BODY,
        "bodyrig_revision": LEGACY_REVISION,
    }


def test_legacy_complete_package_enters_hfn_on_clean_current_integration_revision(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "legacy-face-promoted.mrbody"
    source.write_bytes(b"exact historical face promoted package")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    captured: dict[str, object] = {}

    monkeypatch.setattr(status._legacy, "inspect_continuation", lambda _job: _legacy_complete(source))
    monkeypatch.setattr(status._legacy.preview_manager, "get", lambda _job: _preview())
    monkeypatch.setattr(status, "_preview_root", lambda _job: tmp_path / "preview")
    monkeypatch.setattr(status, "person_library", lambda: tmp_path / "people")
    monkeypatch.setattr(status, "_integration_checkout_state", lambda: (CURRENT_REVISION, True, True))

    def inspect_hfn(**kwargs):
        captured.update(kwargs)
        return {
            "gates": [{
                "id": status.CANDIDATE_GATE,
                "state": "required",
                "passed": False,
                "reason": "no exact HFN detail candidate targets the promoted legacy package",
                "evidence": {},
            }],
            "actions": {
                status.CANDIDATE_GATE: {
                    "gate": status.CANDIDATE_GATE,
                    "command": ".\\prepare-hands-feet-nails-detail-candidate.ps1 ...",
                    "operator_input_required": True,
                    "reason": "select exact source HFN evidence",
                }
            },
            "package_path": source,
            "package_sha256": source_sha,
        }

    monkeypatch.setattr(status, "inspect_hfn_continuation", inspect_hfn)

    result = status.inspect_continuation(JOB_ID)

    assert captured["bodyrig_revision"] == CURRENT_REVISION
    assert captured["source_package_path"] == source.resolve()
    assert captured["source_package_sha256"] == source_sha
    assert result["source_bodyrig_revision"] == LEGACY_REVISION
    assert result["hfn_bodyrig_revision"] == CURRENT_REVISION
    assert result["state"] == "incomplete"
    assert result["next_gate"]["gate"] == status.CANDIDATE_GATE
    assert result["production_activation"] is False


def test_pre_hfn_checkout_only_routes_back_to_current_integration(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "legacy-face-promoted.mrbody"
    source.write_bytes(b"exact historical face promoted package")

    monkeypatch.setattr(status._legacy, "inspect_continuation", lambda _job: _legacy_complete(source))
    monkeypatch.setattr(status._legacy.preview_manager, "get", lambda _job: _preview())
    monkeypatch.setattr(status, "_preview_root", lambda _job: tmp_path / "preview")
    monkeypatch.setattr(status, "_integration_checkout_state", lambda: (LEGACY_REVISION, True, False))
    monkeypatch.setattr(
        status,
        "inspect_hfn_continuation",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("historical checkout must not issue HFN authority")),
    )

    result = status.inspect_continuation(JOB_ID)

    assert result["state"] == "incomplete"
    assert result["source_bodyrig_revision"] == LEGACY_REVISION
    assert result["hfn_bodyrig_revision"] is None
    assert result["next_gate"]["gate"] == status.CANDIDATE_GATE
    assert "update-windows.ps1 -NoBrowser -SkipPlan" in result["next_gate"]["command"]
    assert f"high-fidelity-physical-status.ps1 -PreviewJobId '{JOB_ID}'" in result["next_gate"]["command"]
    assert result["production_activation"] is False


def test_dirty_current_checkout_cannot_create_hfn_authority(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "legacy-face-promoted.mrbody"
    source.write_bytes(b"exact historical face promoted package")

    monkeypatch.setattr(status._legacy, "inspect_continuation", lambda _job: _legacy_complete(source))
    monkeypatch.setattr(status._legacy.preview_manager, "get", lambda _job: _preview())
    monkeypatch.setattr(status, "_preview_root", lambda _job: tmp_path / "preview")
    monkeypatch.setattr(status, "_integration_checkout_state", lambda: (CURRENT_REVISION, False, True))
    monkeypatch.setattr(
        status,
        "inspect_hfn_continuation",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("dirty checkout must not issue HFN authority")),
    )

    result = status.inspect_continuation(JOB_ID)

    assert result["state"] == "blocked"
    assert result["next_gate"]["command"] is None
    assert result["source_bodyrig_revision"] == LEGACY_REVISION
    assert result["hfn_bodyrig_revision"] is None
    assert "dirty" in result["next_gate"]["reason"].lower()
    assert result["production_activation"] is False
