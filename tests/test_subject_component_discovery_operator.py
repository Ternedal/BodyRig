from pathlib import Path


def test_subject_component_discovery_is_bound_to_exact_anatomy_candidate() -> None:
    source = (Path(__file__).resolve().parents[1] / "run-subject-component-discovery.ps1").read_text(encoding="utf-8")

    required = (
        'Subject anatomy physical gate was produced by a different BodyRig revision.',
        '$summary.candidate_gross_anatomy_pass -ne $true',
        '[string]$refit.derivedSmplxObjSha256 -ne $donorSha',
        '[string]$candidateAudit.donorObjSha256 -ne $donorSha',
        '[string]$hair.donorObjSha256 -ne $donorSha',
        '[string]$eyes.donorObjSha256 -ne $donorSha',
        '$summary.reconstruction_rerun -ne $false',
        '$summary.production_activation -ne $false',
        'high_fidelity_ready = $false',
        'production_activation = $false',
    )
    for marker in required:
        assert marker in source


def test_subject_component_discovery_keeps_incomplete_eye_truth_explicit() -> None:
    source = (Path(__file__).resolve().parents[1] / "run-subject-component-discovery.ps1").read_text(encoding="utf-8")

    assert '$eyes.sourceDerivedIrisAppearance -ne $false' in source
    assert 'source_derived_iris_appearance = $false' in source
    assert 'Iris:           MISSING' in source
    assert 'Human review:   REQUIRED' in source
