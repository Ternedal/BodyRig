from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "enrich-photoidentity-multiperformer-target-crops.ps1"


def test_target_crop_enrichment_operator_is_revision_and_pinned_runtime_bound() -> None:
    text = SCRIPT.read_text(encoding="utf-8").lower()
    assert "git -c $reporoot rev-parse head" in text
    assert "git -c $reporoot status --porcelain" in text
    assert "bodyrig.__file__" in text
    assert "bodyrig-sith-fitter-config.json" in text
    assert "bodyrig.sith_preflight" in text
    assert "bodyrig.photoidentity_schp_preflight" in text
    assert "bodyrig.photoidentity_target_crop_enrich" in text
    assert "machine_observability_only -ne $true" in text
    assert "source_detail_quality_authority -ne $false" in text
    assert "photoidentity_source_evidence_authority -ne $false" in text
    assert "reconstruction_permitted -ne $false" in text
    assert "production_activation -ne $false" in text


def test_target_crop_enrichment_operator_does_not_render_or_reconstruct() -> None:
    text = SCRIPT.read_text(encoding="utf-8").lower()
    forbidden = (
        "unity.exe",
        "run-reference-windows-renderer-probe",
        "run-fidelity-windows-render-probe",
        "clone-body",
        "refit-subject-anatomy",
        "run-subject-anatomy",
        "recover-body",
    )
    for token in forbidden:
        assert token not in text
