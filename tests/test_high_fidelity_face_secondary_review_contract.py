from __future__ import annotations

from pathlib import Path

from bodyrig.high_fidelity_face_secondary_review import CHECKLIST_FIELDS
from bodyrig.high_fidelity_face_secondary_review_cli import main as review_cli_main


REPO = Path(__file__).resolve().parents[1]


def test_review_cli_and_operator_require_all_face_secondary_checks() -> None:
    assert callable(review_cli_main)
    cli = (REPO / "bodyrig" / "high_fidelity_face_secondary_review_cli.py").read_text(encoding="utf-8")
    wrapper = (REPO / "record-high-fidelity-face-secondary-review.ps1").read_text(encoding="utf-8")
    for field in CHECKLIST_FIELDS:
        assert "--" + field.replace("_", "-") in cli
    for token in (
        "UpperTeethVisibleAndPlausible",
        "LowerTeethVisibleAndJawBound",
        "TeethNoObviousClippingAtOpenPose",
        "MouthOpenPoseReviewed",
        "EyelashesNoObviousEyeSurfaceClipping",
    ):
        assert token in wrapper
    assert "status --porcelain" in wrapper
    assert '"verify"' in wrapper


def test_review_layer_never_claims_package_or_production_authority() -> None:
    source = (REPO / "bodyrig" / "high_fidelity_face_secondary_review.py").read_text(encoding="utf-8")
    assert '"faceSecondaryPromotionEligible": True' in source
    assert '"faceSecondaryComponentAuthority": False' in source
    assert '"packageMutationPerformed": False' in source
    assert '"productionActivation": False' in source
