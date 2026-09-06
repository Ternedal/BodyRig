from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v3_operator_is_explicit_comparison_only_bake_aligned_path() -> None:
    source = (ROOT / "refit-subject-anatomy-v3.ps1").read_text(encoding="utf-8")

    assert "sith_subject_anatomy_refit_v3.py" in source
    assert '"--sith-repo", $InstallRoot' in source
    assert "explicit-family-smplx-betas-icp-bake-surface-normal-aware-to-retained-sith-source-v3" in source
    assert "sith-closest-source-triangle-face-normal-v1" in source
    assert "deterministic-smplx-face-centroids-v1" in source
    assert "comparison-only" in source
    assert "SiTH rerun:     FALSE" in source
    assert "productionReady -ne $false" in source
    assert "exit 2" in source
