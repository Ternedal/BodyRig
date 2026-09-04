from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import bodyrig.high_fidelity_component_review as review
from bodyrig.high_fidelity_component_review import (
    CHECKLIST_FIELDS,
    HighFidelityComponentReviewError,
    read_review,
    review_status,
    write_review,
)
from bodyrig.high_fidelity_preview_jobs import VIEW_NAMES

JOB_ID = "hfpreview-0123456789abcdef0123456789abcdef"
REVISION = "1" * 40


def _preview() -> dict:
    return {
        "job_id": JOB_ID,
        "kind": "high-fidelity-preview",
        "person_id": "person-test",
        "body_revision": "body-r0001",
        "canonical_body_id": "bodyid-test",
        "bodyrig_revision": REVISION,
        "target_family": "neutral",
        "status": "succeeded",
        "candidate_package_sha256": "a" * 64,
        "review_vrm_sha256": "b" * 64,
        "anatomy_gate_sha256": "c" * 64,
        "component_discovery_sha256": "d" * 64,
        "comparison_authority_sha256": "e" * 64,
        "semantics": "visual-fidelity-not-identity-verification",
        "iris_identity_status": "review-pending",
        "eyelash_status": "missing",
        "comparison_only": True,
        "human_review_required": True,
        "production_activation": False,
        "views": [
            {"view": name, "sha256": f"{index + 1:x}" * 64}
            for index, name in enumerate(VIEW_NAMES)
        ],
    }


def _checklist() -> dict[str, bool]:
    return {field: True for field in CHECKLIST_FIELDS}


def _install_preview(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, state: dict) -> None:
    monkeypatch.setattr(review, "ui_jobs_dir", lambda: tmp_path)
    monkeypatch.setattr(review.preview_jobs, "get", lambda job_id: deepcopy(state))


def test_visual_review_binds_exact_preview_and_only_anatomy_is_promotion_eligible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _preview()
    _install_preview(monkeypatch, tmp_path, state)

    receipt = write_review(
        JOB_ID,
        bodyrig_revision=REVISION,
        checklist=_checklist(),
        quality_note="Anatomy proportions and hair silhouette match the six rendered views.",
    )
    verified = read_review(JOB_ID)

    assert verified == receipt
    assert receipt["view_sha256"] == {item["view"]: item["sha256"] for item in state["views"]}
    assert receipt["review_outcome"] == {
        "body_anatomy": "pass",
        "hair": "visual-pass-deformation-review-required",
        "eyes": "visual-pass-iris-authority-required",
    }
    assert receipt["promotion_eligibility"] == {
        "body_anatomy": True,
        "hair": False,
        "eyes": False,
    }
    assert receipt["production_activation"] is False
    status = review_status(JOB_ID)
    assert status["state"] == "pass"
    assert status["promotion_eligibility"]["body_anatomy"] is True
    assert status["promotion_eligibility"]["hair"] is False
    assert status["promotion_eligibility"]["eyes"] is False


def test_visual_review_is_create_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state = _preview()
    _install_preview(monkeypatch, tmp_path, state)
    kwargs = {
        "bodyrig_revision": REVISION,
        "checklist": _checklist(),
        "quality_note": "Reviewed once.",
    }

    write_review(JOB_ID, **kwargs)
    with pytest.raises(HighFidelityComponentReviewError, match="refusing to overwrite"):
        write_review(JOB_ID, **kwargs)


def test_visual_review_rejects_checkout_revision_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_preview(monkeypatch, tmp_path, _preview())

    with pytest.raises(HighFidelityComponentReviewError, match="checkout revision mismatch"):
        write_review(
            JOB_ID,
            bodyrig_revision="2" * 40,
            checklist=_checklist(),
            quality_note="Wrong checkout.",
        )


def test_existing_review_fails_closed_when_one_preview_image_hash_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _preview()
    _install_preview(monkeypatch, tmp_path, state)
    write_review(
        JOB_ID,
        bodyrig_revision=REVISION,
        checklist=_checklist(),
        quality_note="Exact six-view review.",
    )

    state["views"][-1]["sha256"] = "f" * 64
    with pytest.raises(HighFidelityComponentReviewError, match="exact preview image bytes"):
        read_review(JOB_ID)


def test_review_v1_refuses_non_pending_iris_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _preview()
    state["iris_identity_status"] = "complete"
    _install_preview(monkeypatch, tmp_path, state)

    with pytest.raises(HighFidelityComponentReviewError, match="expects iris identity"):
        write_review(
            JOB_ID,
            bodyrig_revision=REVISION,
            checklist=_checklist(),
            quality_note="Unexpected authority state.",
        )


def test_review_status_is_required_before_receipt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _install_preview(monkeypatch, tmp_path, _preview())

    status = review_status(JOB_ID)

    assert status["state"] == "required"
    assert status["passed"] is False
    assert status["promotion_eligibility"] == {
        "body_anatomy": True,
        "hair": False,
        "eyes": False,
    }
