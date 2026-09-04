from __future__ import annotations

import hashlib
import json

import pytest

from bodyrig.bridges.avatar_fidelity_components import current_pipeline_receipt, with_component_status
from bodyrig.bridges.sith_pbr_material import _read_glb, _write_glb
from bodyrig.high_fidelity_hair_promotion import (
    HighFidelityHairPromotionError,
    _assert_no_eye_runtime,
    _canonical_json_sha256,
    _promoted_hair_avatar,
)


def _hair_avatar(*, with_eyes: bool = False) -> bytes:
    bodyrig = {
        "fidelityComponents": current_pipeline_receipt(),
        "hairReviewRuntime": {
            "comparisonOnly": True,
            "humanReviewRequired": True,
            "productionActivation": False,
        },
    }
    nodes = [{"name": "BodyRigSourceHairReview"}]
    materials = [{"name": "BodyRigHair"}]
    if with_eyes:
        bodyrig["eyeReviewRuntime"] = {"irisAppearanceStatus": "review-pending"}
        nodes.append({"name": "BodyRigSourceEyeReview"})
        materials.append({"name": "BodyRigCorneaReview"})
    return _write_glb(
        {
            "asset": {"version": "2.0"},
            "buffers": [{"byteLength": 0}],
            "nodes": nodes,
            "materials": materials,
            "extras": {"bodyrig": bodyrig},
        },
        b"",
    )


def _anatomy_avatar() -> bytes:
    components = with_component_status(
        current_pipeline_receipt(),
        component="body_anatomy",
        status="complete",
    )
    return _write_glb(
        {
            "asset": {"version": "2.0"},
            "buffers": [{"byteLength": 0}],
            "extras": {
                "bodyrig": {
                    "fidelityComponents": components,
                    "bodyAnatomyPromotion": {
                        "format": "bodyrig-body-anatomy-promotion",
                        "version": 1,
                        "component": "body_anatomy",
                        "productionActivation": False,
                    },
                }
            },
        },
        b"",
    )


def _promotion_kwargs() -> dict:
    return {
        "preview_job_id": "hfpreview-0123456789abcdef0123456789abcdef",
        "source_bodyrig_revision": "1" * 40,
        "promotion_bodyrig_revision": "2" * 40,
        "target_family": "female",
        "source_candidate_package_sha256": "3" * 64,
        "anatomy_promoted_package_sha256": "4" * 64,
        "anatomy_promotion_receipt_sha256": "5" * 64,
        "hair_deformation_review_sha256": "6" * 64,
        "combined_bridge_result_sha256": "7" * 64,
        "rebuilt_hair_bridge_canonical_sha256": "8" * 64,
        "rebuilt_hair_runtime_receipt_sha256": "9" * 64,
        "rebuilt_hair_review_vrm_sha256": "a" * 64,
    }


def test_hair_promotion_preserves_anatomy_and_changes_only_hair() -> None:
    promoted, before, after = _promoted_hair_avatar(
        _hair_avatar(),
        _anatomy_avatar(),
        **_promotion_kwargs(),
    )
    document, _ = _read_glb(promoted)
    bodyrig = document["extras"]["bodyrig"]

    assert before["components"]["body_anatomy"] == "complete"
    assert before["components"]["hair"] != "complete"
    assert after["components"]["body_anatomy"] == "complete"
    assert after["components"]["hair"] == "complete"
    for component in ("skin_appearance", "eyes", "face_secondary"):
        assert after["components"][component] == before["components"][component]
    assert bodyrig["fidelityComponents"] == after
    assert bodyrig["bodyAnatomyPromotion"]["component"] == "body_anatomy"
    assert bodyrig["hairPromotion"]["component"] == "hair"
    assert bodyrig["hairPromotion"]["eyesImported"] is False
    assert bodyrig["hairPromotion"]["productionActivation"] is False
    assert bodyrig["hairPromotion"]["sourceBodyRigRevision"] == "1" * 40
    assert bodyrig["hairPromotion"]["promotionBodyRigRevision"] == "2" * 40
    assert "eyeReviewRuntime" not in bodyrig
    assert after["productionReady"] is False


def test_hair_promotion_rejects_combined_hair_eye_runtime() -> None:
    with pytest.raises(HighFidelityHairPromotionError, match="eye runtime"):
        _promoted_hair_avatar(
            _hair_avatar(with_eyes=True),
            _anatomy_avatar(),
            **_promotion_kwargs(),
        )


def test_eye_runtime_guard_rejects_eye_node_and_cornea_material() -> None:
    document, _ = _read_glb(_hair_avatar())
    document["nodes"].append({"name": "BodyRigSourceEyeReview"})
    with pytest.raises(HighFidelityHairPromotionError, match="eye geometry"):
        _assert_no_eye_runtime(document)

    document, _ = _read_glb(_hair_avatar())
    document["materials"].append({"name": "BodyRigCorneaReview"})
    with pytest.raises(HighFidelityHairPromotionError, match="eye/cornea material"):
        _assert_no_eye_runtime(document)


def test_canonical_bridge_hash_matches_combined_bridge_algorithm() -> None:
    bridge = {
        "z": 1,
        "a": "hair",
        "comparisonOnly": True,
        "productionActivation": False,
    }
    expected = hashlib.sha256(
        json.dumps(bridge, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    assert _canonical_json_sha256(bridge) == expected
