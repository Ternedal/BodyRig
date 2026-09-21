from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "complete-photoreal-v2-p3-quest2-human-review.ps1"


def test_guided_human_review_operator_requires_clean_checkout() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires an exact clean BodyRig checkout" in source
    assert "git -C $repoRoot status --porcelain" in source
    assert "git -C $repoRoot rev-parse HEAD" in source


def test_guided_human_review_operator_requires_all_eight_explicit_decisions() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for parameter in (
        "IdentityLikeness",
        "FaceDetail",
        "Eyes",
        "HairSilhouetteAndAppearance",
        "SkinMaterialResponse",
        "HandsAndExtremities",
        "MotionIdentityPreservation",
        "TemporalStability",
    ):
        assert "[Parameter(Mandatory = $true)][ValidateSet(\"pass\", \"fail\")][string]$" + parameter in source

    for criterion in (
        "identity_likeness",
        "face_detail",
        "eyes",
        "hair_silhouette_and_appearance",
        "skin_material_response",
        "hands_and_extremities",
        "motion_identity_preservation",
        "temporal_stability",
    ):
        assert f'"--decision", "{criterion}=$' in source


def test_guided_human_review_operator_requires_explicit_confirmation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "[Parameter(Mandatory = $true)][switch]$ConfirmPhysicalDeviceReviewComplete" in source
    assert '"--confirm-physical-device-review-complete"' in source


def test_guided_human_review_operator_uses_machine_prefill_and_never_records_authority_itself() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "p3-physical-runtime-evidence.machine-prefill.json" in source
    assert "bodyrig.photoreal_p3_guided_human_review" in source
    assert "Final authority:              NOT YET RECORDED" in source
    assert "Production activation:        FALSE" in source
    assert "record-photoreal-v2-p3-quest2-physical-runtime-review.ps1" in source


def test_guided_human_review_operator_has_no_default_pass_decisions() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '= "pass"' not in source
    assert "= 'pass'" not in source
