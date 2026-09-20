from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "resume-photoreal-v2-after-source.ps1").read_text(encoding="utf-8")


def test_resume_does_not_stop_at_biometric_calibration_block() -> None:
    calibration = SCRIPT.index('if ($calibrationExit -eq 2)')
    frame_analysis = SCRIPT.index('14/16 MEASURE ALL PLANNED FRAMES', calibration)
    block = SCRIPT[calibration:frame_analysis]

    assert 'BLOCKED FOR BIOMETRIC MATCHING' in block
    assert 'Source-bound identity: CONTINUING' in block
    assert 'single-performer Stash sources are independently authorized by source binding' in block
    assert 'exit $finalExitCode' not in block
    assert 'Write-Status -Status "identity-calibration-blocked"' not in block


def test_resume_still_applies_core_source_identity_authority() -> None:
    calibration = SCRIPT.index('13/16 DERIVE IDENTITY THRESHOLD')
    frame_analysis = SCRIPT.index('14/16 MEASURE ALL PLANNED FRAMES')
    identity_authority = SCRIPT.index('15/16 APPLY CORE IDENTITY AUTHORITY')
    frame_index = SCRIPT.index('16/16 LEAKAGE + HELD-OUT COVERAGE GATE')

    assert calibration < frame_analysis < identity_authority < frame_index
    assert 'bodyrig.photoreal_frame_identity_authority_cli' in SCRIPT[identity_authority:frame_index]
