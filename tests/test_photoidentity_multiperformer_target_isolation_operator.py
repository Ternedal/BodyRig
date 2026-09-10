from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "materialize-photoidentity-multiperformer-target-source.ps1"


def test_target_isolation_operator_is_checkout_bound_source_only() -> None:
    text = SCRIPT.read_text(encoding="utf-8").lower()
    assert "git -c $reporoot rev-parse head" in text
    assert "git -c $reporoot status --porcelain" in text
    assert "bodyrig.__file__" in text
    assert "bodyrig.photoidentity_multiperformer_target_isolation" in text
    assert "target_isolated_source_authority" in text
    assert "photoidentity_source_evidence_authority" in text
    assert "reconstruction_permitted" in text
    assert "production_activation" in text
    assert "bbox_interpolation_used" in text
    assert "source_pixels_resized" in text
    assert "generative_pixels_used" in text


def test_target_isolation_operator_does_not_invoke_reconstruction_or_render() -> None:
    text = SCRIPT.read_text(encoding="utf-8").lower()
    forbidden = (
        "run-reference-windows-renderer-probe",
        "run-fidelity-windows-render-probe",
        "unity.exe",
        "unity -batchmode",
        "clone-body",
        "run-subject-anatomy",
        "refit-subject-anatomy",
        "sith_subject",
        "recover-body",
    )
    for token in forbidden:
        assert token not in text
