from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "prepare-hands-feet-nails-landmark-evidence.ps1"
CLI = ROOT / "bodyrig" / "hands_feet_nails_landmark_evidence_cli.py"


def test_wrapper_uses_clean_checkout_head_as_evidence_revision() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    assert "git -C $repoRoot status --porcelain" in source
    assert "requires a clean BodyRig checkout" in source
    assert "git -C $repoRoot rev-parse HEAD" in source
    assert "--bodyrig-revision $revision" in source
    assert "--bodyrig-revision $BodyRigRevision" not in source
    assert "Python imported BodyRig outside the current checkout" in source


def test_wrapper_routes_exact_person_body_capture_scope_to_cli() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    assert "--person-id $PersonId" in source
    assert "--body-revision $BodyRevision" in source
    assert "--capture-id $CaptureId" in source
    assert "--distribution $Distribution" in source
    assert "--openpose $OpenPose" in source
    assert "--ffmpeg-exe $FfmpegExe" in source
    assert "--wsl-exe $WslExe" in source


def test_cli_uses_person_library_and_keeps_authority_false() -> None:
    source = CLI.read_text(encoding="utf-8")
    assert "person_library()" in source
    assert '"package_application_authority": False' in source
    assert '"production_activation": False' in source
