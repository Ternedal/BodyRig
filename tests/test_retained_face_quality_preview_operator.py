from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-retained-face-quality-preview.ps1"


def test_operator_reuses_retained_reconstruction_and_produces_visible_face_views() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'branch --show-current' in source
    assert '"main"' in source
    assert "status --porcelain" in source
    assert "build-retained-hair-eye-review-runtime.ps1" in source
    assert "run-retained-hair-eye-preview.ps1" not in source
    assert "run-face-secondary-hair-eye-windows-preview.ps1" in source
    assert "Intermediate render: SKIPPED" in source
    assert "Renderer build:    FORCED CURRENT HEAD" in source
    assert "sith_reconstruct" not in source
    assert "clone-body-from-stash" not in source

    for view in (
        "front-full.png",
        "three-quarter-full.png",
        "face-front.png",
        "face-zoom.png",
        "eyes-closeup.png",
        "mouth-open.png",
    ):
        assert view in source

    assert "reconstruction_rerun = $false" in source
    assert "rounded_face_secondary_geometry = $true" in source
    assert "production_activation = $false" in source
    assert "deterministic-rounded-oval-cavity-v2" in source
    assert "deterministic-individual-rounded-dental-row-v2" in source
    assert "deterministic-smplx-head-anchored-tapered-ribbon-v2" in source


def test_operator_opens_snapshot_folder_only_when_requested() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "[switch]$OpenPreview" in source
    assert "if ($OpenPreview)" in source
    assert "Start-Process explorer.exe" in source


def test_operator_rejects_skip_build_for_visible_quality_evidence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "[switch]$SkipBuild" in source
    assert 'if ($SkipBuild)' in source
    assert "does not allow -SkipBuild" in source
    assert "$faceArgs.SkipBuild" not in source
    assert "$hairEyeArgs.SkipBuild" not in source
    assert "current_head_renderer_rebuilt = $true" in source
    assert "intermediate_hair_eye_render_skipped = $true" in source
