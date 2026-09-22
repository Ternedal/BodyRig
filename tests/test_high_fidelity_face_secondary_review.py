from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig import high_fidelity_face_secondary_review as review
from bodyrig.high_fidelity_face_secondary_review import HighFidelityFaceSecondaryReviewError


def _authority(*, source_dental: bool = False) -> dict:
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
        "sourceDerivedDentalIdentity": source_dental,
        "genericSecondaryAnatomy": not source_dental,
        "dentalReconstructionResultSha256": "5" * 64 if source_dental else None,
        "dentalVrmSha256": "6" * 64 if source_dental else None,
        "fineIdentityAttestationSha256": "7" * 64 if source_dental else None,
        "dentalTextureSha256": "8" * 64 if source_dental else None,
        "dentalAdapter": "fixture-dental" if source_dental else None,
        "dentalAdapterRevision": "fixture-v1" if source_dental else None,
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
    assert result["sourceDentalIdentityReviewAuthority"] == {
        "reviewedAgainstAttestedSource": False,
        "identityMatchAccepted": False,
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



def test_source_dental_review_requires_explicit_identity_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(review, "_current_authority", lambda *_args: _authority(source_dental=True))
    with pytest.raises(
        HighFidelityFaceSecondaryReviewError,
        match="requires explicit human confirmation",
    ):
        review.write_review(
            tmp_path / "prep",
            tmp_path / "runtime",
            tmp_path / "render",
            tmp_path / "review",
            bodyrig_revision="a" * 40,
            checklist=_checklist(),
            quality_note="Dental source candidate reviewed.",
        )


def test_source_dental_review_binds_identity_confirmation_and_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(review, "_current_authority", lambda *_args: _authority(source_dental=True))
    output = tmp_path / "review-source-dental"
    value = review.write_review(
        tmp_path / "prep",
        tmp_path / "runtime",
        tmp_path / "render",
        output,
        bodyrig_revision="a" * 40,
        checklist=_checklist(),
        quality_note="Compared upper/lower dental identity and mouth interior to exact attested source evidence.",
        source_dental_identity_confirmed=True,
    )
    assert value["sourceDerivedDentalIdentity"] is True
    assert value["genericSecondaryAnatomy"] is False
    assert value["dentalReconstructionResultSha256"] == "5" * 64
    assert value["sourceDentalIdentityReviewAuthority"] == {
        "reviewedAgainstAttestedSource": True,
        "identityMatchAccepted": True,
    }
    verified = review.read_review(
        tmp_path / "prep",
        tmp_path / "runtime",
        tmp_path / "render",
        output,
    )
    assert verified["fineIdentityAttestationSha256"] == "7" * 64
    assert verified["productionActivation"] is False


def test_historical_review_rejects_source_identity_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(review, "_current_authority", lambda *_args: _authority())
    with pytest.raises(
        HighFidelityFaceSecondaryReviewError,
        match="cannot be applied to historical generic",
    ):
        review.write_review(
            tmp_path / "prep",
            tmp_path / "runtime",
            tmp_path / "render",
            tmp_path / "review-historical",
            bodyrig_revision="a" * 40,
            checklist=_checklist(),
            quality_note="Historical generic review.",
            source_dental_identity_confirmed=True,
        )
