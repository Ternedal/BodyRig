from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_missing_gaze_releases_smoothing_residual_immediately() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")
    ]

    guard = "if (_state.gaze == null)"
    assert guard in late_update
    release_start = late_update.index(guard)
    smooth = late_update.index("_gazeStrength = Mathf.Lerp(_gazeStrength, targetGaze, blend);")
    assert release_start < smooth
    release = late_update[release_start:smooth]
    assert "_gazeStrength = 0.0f;" in release


def test_active_gaze_still_uses_smoothed_strength() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")
    ]
    assert "_gazeStrength = Mathf.Lerp(_gazeStrength, targetGaze, blend);" in late_update

    apply_gaze = source[
        source.index("private bool ApplyGaze") : source.index("private void RestorePostureOffsetsForFrame")
    ]
    assert 'if (_state.gaze.target != "user")' in apply_gaze
    assert "if (_state.gaze.strength <= 0.0f)" in apply_gaze
