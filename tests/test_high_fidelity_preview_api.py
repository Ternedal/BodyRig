from __future__ import annotations

import pytest
from pydantic import ValidationError

from bodyrig.app import app
from bodyrig.high_fidelity_preview_api import (
    HighFidelityPreviewStartRequest,
    latest_high_fidelity_preview,
    manager,
)


def test_start_request_requires_exact_body_job_id_and_explicit_target_family() -> None:
    request = HighFidelityPreviewStartRequest(
        body_job_id="job-0123456789abcdef0123456789abcdef",
        target_family="neutral",
    )
    assert request.body_job_id.startswith("job-")
    assert request.target_family == "neutral"

    with pytest.raises(ValidationError):
        HighFidelityPreviewStartRequest(body_job_id="not-a-job", target_family="neutral")
    with pytest.raises(ValidationError):
        HighFidelityPreviewStartRequest(
            body_job_id="job-0123456789abcdef0123456789abcdef",
            target_family="auto",
        )


def test_main_app_exposes_preview_start_status_and_image_routes() -> None:
    routes = {
        (route.path, frozenset(route.methods or set()))
        for route in app.routes
        if hasattr(route, "path") and hasattr(route, "methods")
    }

    assert (
        "/api/v1/people/{person_id}/body/high-fidelity-preview",
        frozenset({"POST"}),
    ) in routes
    assert (
        "/api/v1/people/{person_id}/body/high-fidelity-preview",
        frozenset({"GET"}),
    ) in routes
    assert (
        "/api/v1/high-fidelity-preview-jobs/{job_id}",
        frozenset({"GET"}),
    ) in routes
    assert (
        "/api/v1/high-fidelity-preview-jobs/{job_id}/image/{view}",
        frozenset({"GET"}),
    ) in routes


def test_latest_success_adds_only_hash_bound_image_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        manager,
        "latest_for_revision",
        lambda person_id, revision: {
            "job_id": "hfpreview-0123456789abcdef0123456789abcdef",
            "person_id": person_id,
            "body_revision": revision,
            "status": "succeeded",
            "comparison_only": True,
            "production_activation": False,
            "views": [
                {"view": "eyes-closeup", "sha256": "a" * 64},
            ],
        },
    )

    value = latest_high_fidelity_preview("person-test", revision="body-r0001")

    assert value["comparison_only"] is True
    assert value["production_activation"] is False
    assert value["views"] == [
        {
            "view": "eyes-closeup",
            "sha256": "a" * 64,
            "url": "/api/v1/high-fidelity-preview-jobs/hfpreview-0123456789abcdef0123456789abcdef/image/eyes-closeup",
        }
    ]
