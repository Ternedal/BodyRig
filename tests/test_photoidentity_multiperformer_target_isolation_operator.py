from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATERIALIZE = ROOT / "materialize-photoidentity-multiperformer-target-source.ps1"
RECORD = ROOT / "record-photoidentity-multiperformer-target-isolation.ps1"


def test_target_isolation_materializer_is_checkout_bound_and_non_authoritative() -> None:
    text = MATERIALIZE.read_text(encoding="utf-8").lower()
    assert "git -c $reporoot rev-parse head" in text
    assert "git -c $reporoot status --porcelain" in text
    assert "bodyrig.__file__" in text
    assert "bodyrig.photoidentity_multiperformer_target_isolation" in text
    assert "target_isolated_source_authority -ne $false" in text
    assert "target_isolation_human_review_required -ne $true" in text
    assert "reconstruction permitted: false" in text
    assert "record-photoidentity-multiperformer-target-isolation.ps1" in text


def test_target_isolation_recorder_requires_explicit_human_confirmation_and_stays_pre_reconstruction() -> None:
    text = RECORD.read_text(encoding="utf-8").lower()
    assert "[switch]$confirmtargetisolation" in text
    assert "[string[]]$sampleid" in text
    assert "qualitynote" in text
    assert "bodyrig.photoidentity_multiperformer_target_attestation" in text
    assert "target_isolated_source_authority -ne $true" in text
    assert "photoidentity_source_evidence_authority -ne $false" in text
    assert "reconstruction_permitted -ne $false" in text
    assert "production_activation -ne $false" in text


def test_target_isolation_operators_do_not_invoke_reconstruction_or_render() -> None:
    text = (MATERIALIZE.read_text(encoding="utf-8") + RECORD.read_text(encoding="utf-8")).lower()
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
