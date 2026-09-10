from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

import bodyrig.high_fidelity_preview_api as api
from bodyrig.photoidentity_registry import PhotoIdentityRegistryError


def test_preview_api_requires_photoidentity_authority_before_manager_start(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def reject(person_id: str, body_job_id: str):
        calls.append(f"gate:{person_id}:{body_job_id}")
        raise PhotoIdentityRegistryError("insufficient source evidence")

    def forbidden_start(*args, **kwargs):
        calls.append("manager")
        raise AssertionError("manager.start must not run before source sufficiency")

    monkeypatch.setattr(api, "require_body_job_photoidentity_evidence", reject)
    monkeypatch.setattr(api.manager, "start", forbidden_start)
    request = api.HighFidelityPreviewStartRequest(
        body_job_id="job-" + "1" * 32,
        target_family="female",
    )

    with pytest.raises(HTTPException) as exc:
        api.start_high_fidelity_preview("person-fixture", request)

    assert exc.value.status_code == 409
    assert "insufficient source evidence" in str(exc.value.detail)
    assert calls == [f"gate:person-fixture:job-{'1' * 32}"]


def test_preview_api_calls_manager_only_after_sufficient_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def allow(person_id: str, body_job_id: str):
        calls.append("gate")
        return {"source_evidence_sufficient": True, "human_review_render_permitted": True}

    def start(person_id: str, *, body_job_id: str, target_family: str):
        calls.append("manager")
        return {"job_id": "hfpreview-" + "2" * 32, "status": "queued"}

    monkeypatch.setattr(api, "require_body_job_photoidentity_evidence", allow)
    monkeypatch.setattr(api.manager, "start", start)
    request = api.HighFidelityPreviewStartRequest(
        body_job_id="job-" + "2" * 32,
        target_family="female",
    )

    result = api.start_high_fidelity_preview("person-fixture", request)
    assert result["status"] == "queued"
    assert calls == ["gate", "manager"]


def test_preview_route_source_keeps_gate_before_manager_start() -> None:
    source = inspect.getsource(api.start_high_fidelity_preview)
    assert source.index("require_body_job_photoidentity_evidence") < source.index("manager.start")
