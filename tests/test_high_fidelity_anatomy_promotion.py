from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.high_fidelity_anatomy_promotion as promotion

from bodyrig.fine_identity_application import build_requirement
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


def _fine_requirement() -> dict:
    return build_requirement(
        bodyrig_revision="1" * 40,
        fine_identity_authority_sha256="5" * 64,
        fine_identity_attestation_sha256="6" * 64,
    )


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
        fine_identity_requirement=_fine_requirement(),
    )

    document, _ = _read_glb(promoted)
    bodyrig = document["extras"]["bodyrig"]
    assert before["components"]["body_anatomy"] == "not-evaluated"
    assert after["components"]["body_anatomy"] == "complete"
    for component in ("skin_appearance", "hair", "eyes", "face_secondary"):
        assert after["components"][component] == before["components"][component]
    assert bodyrig["fidelityComponents"] == after
    assert bodyrig["fineIdentityRequirement"] == _fine_requirement()
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
        fine_identity_requirement=_fine_requirement(),
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
        fine_identity_requirement=_fine_requirement(),
        )


def test_anatomy_promotion_persisted_v1_discriminator_is_bool_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = {
        "preview_job_id": "hfpreview-" + "1" * 32,
        "canonical_body_id": "bodyid-test",
        "bodyrig_revision": "2" * 40,
        "target_family": "female",
        "anatomy_gate_sha256": "3" * 64,
    }
    source = tmp_path / "source.mrbody"
    destination = tmp_path / "promoted.mrbody"
    review_receipt = tmp_path / "component-review.json"
    receipt_path = tmp_path / "promotion.json"
    source.write_bytes(b"source-package")
    destination.write_bytes(b"promoted-package")
    review_receipt.write_bytes(b"component-review")

    monkeypatch.setattr(promotion, "read_review", lambda job_id: dict(review))
    monkeypatch.setattr(promotion, "_candidate_package", lambda value: source)
    monkeypatch.setattr(
        promotion,
        "_promotion_paths",
        lambda value: (destination, receipt_path),
    )
    monkeypatch.setattr(
        promotion,
        "_review_receipt_path",
        lambda value: review_receipt,
    )

    base = {field: None for field in promotion.TOP_FIELDS}
    base.update(
        {
            "format": promotion.FORMAT,
            "policy_revision": promotion.POLICY_REVISION,
        }
    )

    for invalid in (True, False, "1", None, {}, [], 2):
        value = dict(base)
        value["version"] = invalid
        receipt_path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(
            promotion.HighFidelityAnatomyPromotionError,
            match="format/version/policy",
        ):
            promotion.read_promotion(review["preview_job_id"])

    numeric = dict(base)
    numeric["version"] = 1.0
    receipt_path.write_text(json.dumps(numeric), encoding="utf-8")
    with pytest.raises(
        promotion.HighFidelityAnatomyPromotionError,
        match="no longer matches exact authority: preview_job_id",
    ):
        promotion.read_promotion(review["preview_job_id"])
