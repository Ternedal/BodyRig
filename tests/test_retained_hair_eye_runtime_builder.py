from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build-retained-hair-eye-review-runtime.ps1"


def test_builder_reuses_retained_reconstruction_without_rendering() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "extract-retained-hair.ps1" in source
    assert "extract-eye-components.ps1" in source
    assert "extract-eye-appearance.ps1" in source
    assert "build-source-hair-eye-review-runtime.ps1" in source

    assert "run-source-hair-eye-windows-preview.ps1" not in source
    assert "run-fidelity-windows-render-probe.ps1" not in source
    assert "BodyRigReferenceProbe.exe" not in source
    assert "sith_reconstruct" not in source
    assert "clone-body-from-stash" not in source

    assert "Intermediate render: SKIPPED" in source
    assert "SiTH rerun:        FALSE" in source
    assert "reconstruction_rerun = $false" in source
    assert "intermediate_render_skipped = $true" in source
    assert "production_activation = $false" in source


def test_builder_binds_runtime_to_exact_current_revision_and_source_bytes() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "git -C $repoRoot rev-parse HEAD" in source
    assert "git -C $repoRoot status --porcelain" in source
    assert "[string]$receipt.bodyrigRevision -ne $head" in source
    assert "[string]$receipt.packageSha256 -ne $packageSha" in source
    assert "[string]$receipt.reviewVrmSha256 -ne (Sha256 $vrmPath)" in source
    assert "(Sha256 $reconstructionPath) -ne $reconstructionSha" in source
    assert "(Sha256 $authorityPath) -ne $authoritySha" in source
    assert "(Sha256 $donorObj) -ne $donorSha" in source
