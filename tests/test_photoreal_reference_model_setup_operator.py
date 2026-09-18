from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "setup-photoreal-reference-models.ps1").read_text(encoding="utf-8")


def test_model_setup_requires_explicit_research_license_acceptance() -> None:
    assert "[switch]$AcceptInsightFaceResearchLicense" in SCRIPT
    assert "if (-not $AcceptInsightFaceResearchLicense)" in SCRIPT
    assert "research/non-commercial assets" in SCRIPT


def test_model_setup_verifies_official_buffalo_archive_sha() -> None:
    assert "80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f" in SCRIPT
    assert "InsightFace buffalo_l archive SHA-256 mismatch" in SCRIPT
    assert 'Get-ChildItem -LiteralPath $extract -Filter "w600k_r50.onnx"' in SCRIPT
    assert 'Get-ChildItem -LiteralPath $extract -Filter "det_10g.onnx"' in SCRIPT


def test_model_setup_is_atomic_and_does_not_write_into_final_root_until_complete() -> None:
    assert '$stageRoot = Join-Path $tempRoot "model-root"' in SCRIPT
    assert 'Move-Item -LiteralPath $stageRoot -Destination $ModelRoot' in SCRIPT
    assert "Staged model root is incomplete" in SCRIPT
    assert SCRIPT.index("Staged model root is incomplete") < SCRIPT.index("Move-Item -LiteralPath $stageRoot")


def test_model_setup_replaces_existing_root_only_after_staging_when_forced() -> None:
    final_remove = SCRIPT.rindex("Remove-Item -LiteralPath $ModelRoot -Recurse -Force")
    final_move = SCRIPT.index("Move-Item -LiteralPath $stageRoot -Destination $ModelRoot")
    assert final_remove < final_move
    assert SCRIPT.index("Staged model root is incomplete") < final_remove


def test_model_setup_keeps_runtime_authority_false() -> None:
    assert "production_activation = $false" in SCRIPT
    assert "Production:       FALSE" in SCRIPT
