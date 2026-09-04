from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig import high_fidelity_face_secondary_review as review
from bodyrig.high_fidelity_face_secondary_review import HighFidelityFaceSecondaryReviewError


def _authority() -> dict:
    return {
        "bodyrigRevision": "a" * 40,
        "canonicalBodyId": "body-test",
        "sourcePackageSha256": "b" * 64,
        "sourceRuntimeReceiptSha256": "c" * 64,
        "sourceReviewVrmSha256": "d" * 64,
        "comparisonPackageSha256": "e" * 64,
        "previewAuthoritySha256": "f" * 64,
        "comparisonAuthoritySha256": "1" * 64,
        "renderManifestSha256": "2" * 64,
        "canonicalViewSha256": {name: "3" * 64 for name in ("front-full", "three-quarter-full", "side-full", "face-front")},
        "diagnosticViewSha256": {name: "4" * 64 for name in ("face-zoom", "eyes-closeup", "mouth-open")},
        "semanticAnchorAuthority": "licensed-smplx-joint-topology-v1",
        "genericSecondaryAnatomy": True,
    }


def _checklist() -> dict[str, bool]:
    return {field: True for field in review.CHECKLIST_FIELDS}


def test_write_and_read_review_require_explicit_teeth_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review, "_current_authority", lambda *_args: _authority())
    output = tmp_path / "review"
    result = review.write_review(
        tmp_path / "prep",
        tmp_path / "runtime",
        tmp_path / "render",
        output,
        bodyrig_revision="a" * 40,
        checklist=_checklist(),
        quality_note="Teeth, mouth, lashes, brows and lip boundary reviewed at the exact bound views.",
    )
    assert result["componentReviewOutcome"] == {component: "pass" for component in review.COMPONENTS}
    assert result["teethReviewAuthority"] == {
        "upperVisibleAndPlausible": True,
        "lowerVisibleAndJawBound": True,
        "openPoseClippingAcceptable": True,
    }
    assert result["faceSecondaryPromotionEligible"] is True
    assert result["faceSecondaryComponentAuthority"] is False
    assert result["packageMutationPerformed"] is False
    assert result["productionActivation"] is False
    verified = review.read_review(tmp_path / "prep", tmp_path / "runtime", tmp_path / "render", output)
    assert verified["previewAuthoritySha256"] == "f" * 64


def test_review_rejects_any_unchecked_item(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review, "_current_authority", lambda *_args: _authority())
    checklist = _checklist()
    checklist["lower_teeth_visible_and_jaw_bound"] = False
    with pytest.raises(HighFidelityFaceSecondaryReviewError, match="lower_teeth_visible_and_jaw_bound"):
        review.write_review(
            tmp_path / "prep",
            tmp_path / "runtime",
            tmp_path / "render",
            tmp_path / "review",
            bodyrig_revision="a" * 40,
            checklist=checklist,
            quality_note="not enough",
        )


def test_review_is_invalidated_when_preview_authority_moves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    current = _authority()
    monkeypatch.setattr(review, "_current_authority", lambda *_args: dict(current))
    output = tmp_path / "review"
    review.write_review(
        tmp_path / "prep",
        tmp_path / "runtime",
        tmp_path / "render",
        output,
        bodyrig_revision="a" * 40,
        checklist=_checklist(),
        quality_note="Exact review evidence accepted.",
    )
    current["previewAuthoritySha256"] = "9" * 64
    with pytest.raises(HighFidelityFaceSecondaryReviewError, match="stale: previewAuthoritySha256"):
        review.read_review(tmp_path / "prep", tmp_path / "runtime", tmp_path / "render", output)


def test_review_receipt_is_create_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review, "_current_authority", lambda *_args: _authority())
    output = tmp_path / "review"
    kwargs = dict(
        bodyrig_revision="a" * 40,
        checklist=_checklist(),
        quality_note="Exact review evidence accepted.",
    )
    review.write_review(tmp_path / "prep", tmp_path / "runtime", tmp_path / "render", output, **kwargs)
    with pytest.raises(HighFidelityFaceSecondaryReviewError, match="create-only"):
        review.write_review(tmp_path / "prep", tmp_path / "runtime", tmp_path / "render", output, **kwargs)
