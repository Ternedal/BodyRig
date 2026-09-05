from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.person_release_status as release_status
from bodyrig.person_release_status import PersonReleaseStatusError

PERSON_ID = "person-" + "1" * 32
BODY_REVISION = "body-r0001"
BODY_ID = "bodyid-" + "2" * 24
REGISTERED_SHA = "3" * 64
PROMOTED_SHA = "4" * 64
BODYRIG_REVISION = "5" * 40
PREVIEW_ID = "hfpreview-" + "6" * 32
BODY_JOB_ID = "job-" + "7" * 32

COMPONENTS = {
    "body_anatomy": "complete",
    "skin_appearance": "complete",
    "hair": "complete",
    "eyes": "complete",
    "face_secondary": "complete",
}
FACE_COMPONENTS = {
    "eyebrow_appearance": "complete",
    "lip_boundary": "complete",
    "mouth_interior": "complete",
    "teeth": "complete",
    "eyelashes": "complete",
}


def _source_job() -> dict:
    return {
        "format": "bodyrig-ui-job",
        "version": 1,
        "kind": "body-build",
        "job_id": BODY_JOB_ID,
        "person_id": PERSON_ID,
        "body_revision": BODY_REVISION,
        "canonical_body_id": BODY_ID,
        "status": "succeeded",
        "acceptance_dir": "/deliberately/not/used/by/high-fidelity-routing",
        "created_utc": "2026-09-05T12:00:00Z",
    }


def _preview() -> dict:
    return {
        "job_id": PREVIEW_ID,
        "person_id": PERSON_ID,
        "body_job_id": BODY_JOB_ID,
        "body_revision": BODY_REVISION,
        "canonical_body_id": BODY_ID,
        "bodyrig_revision": BODYRIG_REVISION,
        "status": "succeeded",
    }


def _final_audit() -> dict:
    return {
        "face_secondary_components": dict(FACE_COMPONENTS),
        "face_secondary_ready": True,
        "face_secondary_blockers": [],
        "semantic_vertex_map_authority": "licensed-smplx-verified",
    }


def _production_readiness() -> dict:
    return {
        "state": "production-ready",
        "production_ready": True,
        "production_activation": True,
        "component_package_complete": True,
        "high_fidelity_human_review_complete": True,
        "current_package_sha256": PROMOTED_SHA,
        "components": dict(COMPONENTS),
        "final_audit": _final_audit(),
        "gates": [
            {
                "id": "physical_gate_a",
                "state": "pass",
                "evidence": {"bodyrig_revision": BODYRIG_REVISION},
            },
            {"id": "physical_windows_acceptance", "state": "pass"},
            {"id": "physical_quest_acceptance", "state": "pass"},
            {"id": "final_release", "state": "pass"},
            {"id": "high_fidelity_human_review", "state": "pass"},
        ],
        "next_gate": None,
    }


def _windows_readiness() -> dict:
    return {
        "state": "physical-windows-acceptance-required",
        "production_ready": False,
        "production_activation": False,
        "component_package_complete": True,
        "high_fidelity_human_review_complete": True,
        "current_package_sha256": PROMOTED_SHA,
        "components": dict(COMPONENTS),
        "final_audit": _final_audit(),
        "physical_acceptance_dir": "/fake/physical",
        "gates": [
            {
                "id": "physical_gate_a",
                "state": "pass",
                "evidence": {"bodyrig_revision": BODYRIG_REVISION},
            },
            {"id": "physical_windows_acceptance", "state": "required"},
            {"id": "high_fidelity_human_review", "state": "pass"},
        ],
        "next_gate": {
            "gate": "physical_windows_acceptance",
            "command": ".\\run-windows-renderer-probe.ps1 -AcceptanceDir '/fake/physical'",
            "reason": "Windows probe required",
            "operator_input_required": True,
        },
    }


def _route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    readiness: dict,
    operator_authority: dict | None = None,
) -> dict:
    monkeypatch.setattr(
        release_status.high_fidelity_preview_manager,
        "latest_for_revision",
        lambda person_id, body_revision: _preview(),
    )
    monkeypatch.setattr(release_status, "inspect_release_readiness", lambda job_id: readiness)
    monkeypatch.setattr(
        release_status,
        "_legacy_inspect_candidate_release_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy release status must not run")),
    )
    return release_status.inspect_candidate_release_status(
        [_source_job()],
        person_id=PERSON_ID,
        body_revision=BODY_REVISION,
        body_id=BODY_ID,
        package_sha256=REGISTERED_SHA,
        operator_authority=operator_authority,
    )


def test_high_fidelity_production_route_uses_promoted_release_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _route(monkeypatch, readiness=_production_readiness())

    assert value["state"] == "complete"
    assert value["gate"] == "release"
    assert value["production_ready"] is True
    assert value["production_activation"] is True
    assert value["package_sha256"] == PROMOTED_SHA
    assert value["registered_package_sha256"] == REGISTERED_SHA
    assert value["high_fidelity_preview_job_id"] == PREVIEW_ID
    assert value["bodyrig_revision"] == BODYRIG_REVISION
    assert value["next_command"] is None
    assert value["stages"] == {"gate_a": "pass", "windows": "pass", "quest": "pass", "release": "pass"}
    assert value["fidelity"]["high_fidelity_ready"] is True
    assert value["fidelity"]["human_review"]["passed"] is True


def test_high_fidelity_prefinal_route_does_not_fall_back_to_generic_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_root = tmp_path / "operator"
    operator_root.mkdir()

    def bind(result: dict, root: Path) -> dict:
        assert root == operator_root.resolve()
        value = dict(result)
        next_gate = dict(value["next_gate"])
        next_gate["command"] = (
            f'& "{operator_root.resolve() / "run-reference-windows-renderer-probe.ps1"}" '
            "-AcceptanceDir '/fake/physical'"
        )
        value["next_gate"] = next_gate
        value["operator_checkout"] = {
            "authorized": True,
            "revision": BODYRIG_REVISION,
            "root": str(operator_root.resolve()),
            "clean": True,
        }
        return value

    monkeypatch.setattr(release_status, "bind_high_fidelity_operator_checkout", bind)
    value = _route(
        monkeypatch,
        readiness=_windows_readiness(),
        operator_authority={
            "ok": True,
            "root": str(operator_root),
            "revision": BODYRIG_REVISION,
        },
    )

    assert value["production_ready"] is False
    assert value["production_activation"] is False
    assert value["package_sha256"] == PROMOTED_SHA
    assert value["state"] == "ready"
    assert value["gate"] == "windows-probe"
    assert value["stages"]["gate_a"] == "pass"
    assert value["stages"]["windows"] == "machine-probe-required"
    assert value["operator_checkout"]["ready"] is True
    assert "run-reference-windows-renderer-probe.ps1" in value["next_command"]
    assert "run-windows-renderer-probe.ps1 -AcceptanceDir" not in value["next_command"]


def test_high_fidelity_route_withholds_raw_command_when_checkout_is_not_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _route(
        monkeypatch,
        readiness=_windows_readiness(),
        operator_authority={"ok": False, "reason": "checkout is dirty", "revision": BODYRIG_REVISION},
    )

    assert value["production_ready"] is False
    assert value["next_command"] is None
    assert value["operator_checkout"]["required"] is True
    assert value["operator_checkout"]["ready"] is False
    assert "dirty" in value["operator_checkout"]["reason"]


def test_high_fidelity_route_rejects_missing_source_body_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        release_status.high_fidelity_preview_manager,
        "latest_for_revision",
        lambda person_id, body_revision: _preview(),
    )
    monkeypatch.setattr(
        release_status,
        "inspect_release_readiness",
        lambda job_id: (_ for _ in ()).throw(AssertionError("readiness must not run before source binding")),
    )

    with pytest.raises(PersonReleaseStatusError, match="source body-build job is unavailable"):
        release_status.inspect_candidate_release_status(
            [],
            person_id=PERSON_ID,
            body_revision=BODY_REVISION,
            body_id=BODY_ID,
            package_sha256=REGISTERED_SHA,
        )


def test_no_high_fidelity_preview_preserves_legacy_release_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = {"state": "legacy", "production_ready": False}
    calls: list[dict] = []

    def no_preview(person_id: str, body_revision: str) -> dict:
        raise release_status.HighFidelityPreviewError("no high-fidelity preview exists for this body revision")

    def legacy(jobs, **kwargs):
        calls.append({"jobs": list(jobs), **kwargs})
        return sentinel

    monkeypatch.setattr(release_status.high_fidelity_preview_manager, "latest_for_revision", no_preview)
    monkeypatch.setattr(release_status, "_legacy_inspect_candidate_release_status", legacy)

    value = release_status.inspect_candidate_release_status(
        [_source_job()],
        person_id=PERSON_ID,
        body_revision=BODY_REVISION,
        body_id=BODY_ID,
        package_sha256=REGISTERED_SHA,
        operator_authority={"ok": False},
    )

    assert value is sentinel
    assert len(calls) == 1
    assert calls[0]["person_id"] == PERSON_ID
    assert calls[0]["body_revision"] == BODY_REVISION
    assert calls[0]["body_id"] == BODY_ID
    assert calls[0]["package_sha256"] == REGISTERED_SHA
