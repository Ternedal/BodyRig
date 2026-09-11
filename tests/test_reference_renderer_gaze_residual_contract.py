from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_unsupported_gaze_target_clears_smoothed_residual_without_head_write() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    apply_gaze = source[
        source.index("private bool ApplyGaze") : source.index("private void RestorePostureOffsetsForFrame")
    ]

    unsupported_guard = apply_gaze.index('if (_state.gaze.target != "user")')
    zero_guard = apply_gaze.index("if (_state.gaze.strength <= 0.0f)")
    unsupported = apply_gaze[unsupported_guard:zero_guard]

    assert "_gazeStrength = 0.0f;" in unsupported
    assert "return false;" in unsupported
    assert "userGazeTarget" not in unsupported
    assert "_head.localRotation" not in unsupported


def test_gaze_residual_cleanup_runs_after_frame_smoothing() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")
    ]

    smoothing = late_update.index("_gazeStrength = Mathf.Lerp(_gazeStrength, targetGaze, blend);")
    realization = late_update.index("GazeRealized = ApplyGaze();")
    assert smoothing < realization
