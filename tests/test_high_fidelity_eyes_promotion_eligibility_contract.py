from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_operator_records_eligibility_without_promoting_or_mutating_package() -> None:
    text = (ROOT / "record-high-fidelity-eyes-promotion-eligibility.ps1").read_text(encoding="utf-8")
    assert "Windows-only" in text
    assert "PowerShell 7+" in text
    assert "status --porcelain" in text
    assert "bodyrig.high_fidelity_eyes_promotion_eligibility_cli record" in text
    assert "--preview-job-id $PreviewJobId" in text
    assert "--bodyrig-revision $head" in text
    assert "$result.eyes_promotion_eligible -ne $true" in text
    assert "$result.eye_component_authority -ne $false" in text
    assert "$result.package_mutation_performed -ne $false" in text
    assert "$result.eyes_promoted -ne $false" in text
    assert "$result.production_activation -ne $false" in text
    assert 'eyelash_status -ne "missing"' in text
    assert "Eyelashes:           MISSING (face_secondary blocker)" in text
    assert "eligibility alone never mutates the source package" in text


def test_checkout_race_cleanup_removes_only_new_eligibility_receipt() -> None:
    text = (ROOT / "record-high-fidelity-eyes-promotion-eligibility.ps1").read_text(encoding="utf-8")
    assert "Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head" in text
    assert "Remove-Item -LiteralPath $receiptPath -Force" in text
    assert "removed only the newly created eligibility receipt" in text
    assert "Remove-Item -LiteralPath $baseRoot" not in text
    assert "Remove-Item -LiteralPath $irisRoot" not in text
    assert "Remove-Item -LiteralPath $sourceRoot" not in text
    assert "Remove-Item -LiteralPath $reviewedRoot" not in text


def test_eligibility_module_requires_same_package_and_same_reviewed_vrm() -> None:
    text = (ROOT / "bodyrig" / "high_fidelity_eyes_promotion_eligibility.py").read_text(encoding="utf-8")
    assert "base eye runtime package differs from component visual-review candidate package" in text
    assert "iris review is not bound to the exact VRM bytes that received component visual review" in text
    assert '"eyesPromotionEligible": True' in text
    assert '"eyeComponentAuthority": False' in text
    assert '"packageMutationPerformed": False' in text
    assert '"eyesPromoted": False' in text
    assert '"eyelashStatus": "missing"' in text
    assert '"faceSecondaryUnaffected": True' in text
    assert '"productionActivation": False' in text
