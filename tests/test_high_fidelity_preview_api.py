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


def test_main_app_exposes_preview_and_review_authority_routes() -> None:
    paths = app.openapi()["paths"]

    preview = paths["/api/v1/people/{person_id}/body/high-fidelity-preview"]
    assert "post" in preview
    assert "get" in preview
    assert "get" in paths["/api/v1/high-fidelity-preview-jobs/{job_id}"]
    assert "get" in paths["/api/v1/high-fidelity-preview-jobs/{job_id}/image/{view}"]
    assert "get" in paths["/api/v1/high-fidelity-preview-jobs/{job_id}/component-review"]
    assert "get" in paths["/api/v1/high-fidelity-preview-jobs/{job_id}/anatomy-promotion"]
    assert "get" in paths["/api/v1/high-fidelity-preview-jobs/{job_id}/hair-deformation-review"]


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
