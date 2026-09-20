from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "resume-photoreal-v2-after-calibration.ps1").read_text(encoding="utf-8")


def test_stage14_resume_reuses_stage13_without_rehash_or_recalibration() -> None:
    assert "Stage-13 dataset plan" in SCRIPT
    assert "Stage-13 source receipt" in SCRIPT
    assert "Stage-13 scan plan" in SCRIPT
    assert "Stage-13 model set" in SCRIPT
    assert "Stage-13 identity bank" in SCRIPT
    assert "Stage-13 identity calibration" in SCRIPT

    assert "source_rehash_skipped_explicitly = $true" in SCRIPT
    assert "identity_bank_rebuild = $false" in SCRIPT
    assert "identity_calibration_rebuild = $false" in SCRIPT

    assert "photoreal-stash-inventory.ps1" not in SCRIPT
    assert "photoreal_identity_extractor_cli" not in SCRIPT
    assert "photoreal_identity_negative_inventory_cli" not in SCRIPT
    assert "photoreal_identity_calibration_extractor_cli" not in SCRIPT
    assert "photoreal_identity_calibration_cli" not in SCRIPT


def test_stage14_resume_runs_only_remaining_p0_authority_chain() -> None:
    frame_analysis = SCRIPT.index("14/16 MEASURE ALL PLANNED FRAMES")
    identity_authority = SCRIPT.index("15/16 APPLY CORE SOURCE/IDENTITY AUTHORITY")
    frame_index = SCRIPT.index("16/16 LEAKAGE + HELD-OUT COVERAGE GATE")

    assert frame_analysis < identity_authority < frame_index
    assert "bodyrig.photoreal_frame_analyzer_cli" in SCRIPT[frame_analysis:identity_authority]
    assert "bodyrig.photoreal_frame_identity_authority_cli" in SCRIPT[identity_authority:frame_index]
    assert "bodyrig.photoreal_frame_index_cli" in SCRIPT[frame_index:]


def test_stage14_resume_preserves_source_bound_identity_semantics() -> None:
    assert "source_bound_identity_continues_independently = $true" in SCRIPT
    assert "stash-single-performer-target-binding-v1" in SCRIPT
    assert "calibrated-identity-bank-v1" in SCRIPT
    assert "Source-bound verified:" in SCRIPT
    assert "Calibrated verified:" in SCRIPT
    assert "Unresolved:" in SCRIPT


def test_stage14_resume_stays_below_photoreal_and_production_authority() -> None:
    assert "human_visual_acceptance_required = $true" in SCRIPT
    assert "photoreal_acceptance_authority = $false" in SCRIPT
    assert "production_activation = $false" in SCRIPT
    assert "Photoreal accept:      FALSE" in SCRIPT
    assert "Production:            FALSE" in SCRIPT


def test_stage14_resume_requires_canonical_clean_main() -> None:
    assert "branch --show-current" in SCRIPT
    assert 'Trim() -ne "main"' in SCRIPT
    assert "status --porcelain" in SCRIPT
    assert "requires an exact clean BodyRig checkout" in SCRIPT
