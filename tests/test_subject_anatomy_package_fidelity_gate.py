from pathlib import Path


def test_subject_anatomy_candidate_requires_high_fidelity_package_audit() -> None:
    source = (Path(__file__).resolve().parents[1] / "build-subject-anatomy-candidate.ps1").read_text(encoding="utf-8")

    required = (
        "bodyrig.high_fidelity_package_audit",
        'high_fidelity_ready -ne $false',
        'face_secondary_ready -ne $false',
        'semantic_vertex_map_authority -ne "unavailable"',
        'face_secondary_blockers = @($fidelity.face_secondary_blockers)',
        'High fidelity:  FALSE',
        'Face secondary: BLOCKED',
        'production_activation = $false',
    )
    for marker in required:
        assert marker in source
