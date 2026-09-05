from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bodyrig import high_fidelity_face_secondary_promotion as promotion
from bodyrig.bridges.avatar_fidelity_components import current_pipeline_receipt, with_component_status
from bodyrig.bridges.face_secondary_fidelity import current_face_secondary_receipt
from bodyrig.high_fidelity_face_secondary_promotion import HighFidelityFaceSecondaryPromotionError


def _before_components() -> dict:
    top = current_pipeline_receipt()
    for component in ("body_anatomy", "skin_appearance", "hair", "eyes"):
        top = with_component_status(top, component=component, status="complete")
    return top


def test_nested_completion_drives_top_level_face_secondary() -> None:
    nested = promotion._completed_face_receipt(current_face_secondary_receipt())
    assert nested["components"] == {component: "complete" for component in promotion.REQUIRED_SUBCOMPONENTS}
    assert nested["faceSecondaryReady"] is True
    assert nested["semanticVertexMapAuthority"] == "licensed-smplx-verified"
    before = _before_components()
    from bodyrig.bridges.avatar_fidelity_components import with_face_secondary_receipt
    after = with_face_secondary_receipt(before, face_secondary_receipt=nested)
    assert after["components"]["face_secondary"] == "complete"
    assert after["highFidelityReady"] is True
    assert after["productionReady"] is False


def test_atomic_final_directory_rolls_back_after_post_move_revalidation_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.mrbody"
    source.write_bytes(b"source-package")
    human = tmp_path / "human"
    human.mkdir()
    review_path = human / "review.json"
    review_path.write_bytes(b"human-review")
    final = tmp_path / "promotion"

    before = _before_components()
    before["components"]["face_secondary"] = "partial"
    before["blockers"] = ["face_secondary"]
    before["highFidelityReady"] = False
    after = {**before, "components": {**before["components"], "face_secondary": "complete"}, "blockers": [], "highFidelityReady": True}
    review = {
        "canonicalBodyId": "body-test",
        "sourceRuntimeReceiptSha256": "1" * 64,
        "sourceReviewVrmSha256": "2" * 64,
        "previewAuthoritySha256": "3" * 64,
        "reviewPath": str(review_path),
    }
    runtime = {"canonicalBodyId": "body-test"}

    monkeypatch.setattr(promotion, "_authority", lambda *_args: (review, runtime, b"review-vrm", promotion._sha256_file(source)))
    monkeypatch.setattr(promotion, "_package_avatar", lambda _path: (b"source-avatar", "body-test"))
    monkeypatch.setattr(promotion, "_build_promoted_avatar", lambda **_kwargs: (b"promoted-avatar", before, after))
    monkeypatch.setattr(promotion, "_rewrite_package", lambda _src, dst, *, avatar_vrm: dst.write_bytes(b"package" + avatar_vrm))
    monkeypatch.setattr(promotion, "validate_package", lambda _path: SimpleNamespace(manifest={"id": "body-test"}))
    monkeypatch.setattr(promotion, "audit_high_fidelity_package", lambda _path: {
        "face_secondary_components": {component: "complete" for component in promotion.REQUIRED_SUBCOMPONENTS},
        "face_secondary_ready": True,
        "components": dict(after["components"]),
        "production_ready": False,
        "high_fidelity_ready": True,
    })
    monkeypatch.setattr(promotion, "read_promotion", lambda **_kwargs: (_ for _ in ()).throw(HighFidelityFaceSecondaryPromotionError("forced post-move failure")))

    with pytest.raises(HighFidelityFaceSecondaryPromotionError, match="forced post-move failure"):
        promotion.write_promotion(
            preparation_dir=tmp_path / "prep",
            runtime_dir=tmp_path / "runtime",
            render_dir=tmp_path / "render",
            human_review_dir=human,
            source_package_path=source,
            output_dir=final,
            promotion_bodyrig_revision="a" * 40,
        )
    assert not final.exists()


def test_preexisting_output_is_never_removed(tmp_path: Path) -> None:
    source = tmp_path / "source.mrbody"
    source.write_bytes(b"source")
    final = tmp_path / "promotion"
    final.mkdir()
    marker = final / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(HighFidelityFaceSecondaryPromotionError, match="create-only"):
        promotion.write_promotion(
            preparation_dir=tmp_path / "prep",
            runtime_dir=tmp_path / "runtime",
            render_dir=tmp_path / "render",
            human_review_dir=tmp_path / "human",
            source_package_path=source,
            output_dir=final,
            promotion_bodyrig_revision="a" * 40,
        )
    assert marker.read_text(encoding="utf-8") == "keep"
