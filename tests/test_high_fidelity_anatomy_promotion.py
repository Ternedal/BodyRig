from __future__ import annotations

import pytest

from bodyrig.bridges.avatar_fidelity_components import current_pipeline_receipt, with_component_status
from bodyrig.bridges.face_secondary_fidelity import current_face_secondary_receipt
from bodyrig.bridges.sith_pbr_material import _read_glb, _write_glb
from bodyrig.high_fidelity_anatomy_promotion import (
    HighFidelityAnatomyPromotionError,
    _promoted_avatar,
)


def _avatar(top=None) -> bytes:
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": 0}],
        "extras": {
            "bodyrig": {
                "fidelityComponents": top or current_pipeline_receipt(),
                "faceSecondaryFidelity": current_face_secondary_receipt(),
            }
        },
    }
    return _write_glb(document, b"")


def _review() -> dict:
    return {
        "preview_job_id": "hfpreview-0123456789abcdef0123456789abcdef",
        "bodyrig_revision": "1" * 40,
        "target_family": "female",
        "anatomy_gate_sha256": "2" * 64,
        "promotion_eligibility": {
            "body_anatomy": True,
            "hair": False,
            "eyes": False,
        },
    }


def test_promoted_avatar_changes_only_body_anatomy_and_stays_non_activating() -> None:
    source = current_pipeline_receipt()
    promoted, before, after = _promoted_avatar(
        _avatar(source),
        review=_review(),
        component_review_sha256="3" * 64,
        source_package_sha256="4" * 64,
    )

    document, _ = _read_glb(promoted)
    bodyrig = document["extras"]["bodyrig"]
    assert before["components"]["body_anatomy"] == "not-evaluated"
    assert after["components"]["body_anatomy"] == "complete"
    for component in ("skin_appearance", "hair", "eyes", "face_secondary"):
        assert after["components"][component] == before["components"][component]
    assert bodyrig["fidelityComponents"] == after
    assert bodyrig["bodyAnatomyPromotion"] == {
        "format": "bodyrig-body-anatomy-promotion",
        "version": 1,
        "policyRevision": "bodyrig-high-fidelity-anatomy-promotion-v1",
        "previewJobId": "hfpreview-0123456789abcdef0123456789abcdef",
        "componentReviewSha256": "3" * 64,
        "sourcePackageSha256": "4" * 64,
        "anatomyGateSha256": "2" * 64,
        "bodyrigRevision": "1" * 40,
        "targetFamily": "female",
        "component": "body_anatomy",
        "productionActivation": False,
    }
    assert after["highFidelityReady"] is False
    assert after["productionReady"] is False


def test_promoted_avatar_rejects_review_that_attempts_hair_or_eye_promotion() -> None:
    review = _review()
    review["promotion_eligibility"] = {
        "body_anatomy": True,
        "hair": True,
        "eyes": False,
    }
    with pytest.raises(HighFidelityAnatomyPromotionError, match="anatomy-only"):
        _promoted_avatar(
            _avatar(),
            review=review,
            component_review_sha256="3" * 64,
            source_package_sha256="4" * 64,
        )


def test_promoted_avatar_rejects_already_complete_anatomy() -> None:
    complete = with_component_status(
        current_pipeline_receipt(),
        component="body_anatomy",
        status="complete",
    )
    with pytest.raises(HighFidelityAnatomyPromotionError, match="already complete"):
        _promoted_avatar(
            _avatar(complete),
            review=_review(),
            component_review_sha256="3" * 64,
            source_package_sha256="4" * 64,
        )
