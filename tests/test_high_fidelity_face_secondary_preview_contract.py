from __future__ import annotations

from pathlib import Path

from bodyrig.high_fidelity_face_secondary_preview_cli import main as preview_cli_main


REPO = Path(__file__).resolve().parents[1]


def test_preview_cli_exports_finalize_and_verify() -> None:
    assert callable(preview_cli_main)
    source = (REPO / "bodyrig" / "high_fidelity_face_secondary_preview_cli.py").read_text(encoding="utf-8")
    assert "finalize_preview" in source
    assert "read_preview" in source
    assert 'sub.add_parser("finalize")' in source
    assert 'sub.add_parser("verify")' in source


def test_windows_operator_is_atomic_and_uses_exact_renderer_path() -> None:
    source = (REPO / "run-high-fidelity-face-secondary-windows-preview.ps1").read_text(encoding="utf-8")
    assert "status --porcelain" in source
    assert "run-fidelity-windows-render-probe.ps1" in source
    assert '"finalize"' in source
    assert '"verify"' in source
    assert "Move-Item -LiteralPath $attempt -Destination $OutputDir" in source
    assert "Remove-Item -LiteralPath $OutputDir -Recurse -Force" in source


def test_reference_renderer_exposes_open_mouth_diagnostic_without_changing_v1_manifest() -> None:
    source = (REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigFidelitySnapshotCapture.cs").read_text(encoding="utf-8")
    assert 'new CameraPose("mouth-open"' in source
    assert 'new CameraPose("front-full"' in source
    assert 'new CameraPose("three-quarter-full"' in source
    assert 'new CameraPose("side-full"' in source
    assert 'new CameraPose("face-front"' in source
    assert "diagnosticPoses" in source
