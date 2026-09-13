from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "prepare-hands-feet-nails-detail-candidate.ps1"
CLI = ROOT / "bodyrig" / "hands_feet_nails_detail_candidate_cli.py"


def test_wrapper_binds_candidate_to_exact_clean_checkout_and_existing_m2_next_gate() -> None:
    text = WRAPPER.read_text(encoding="utf-8")

    assert 'git -C $repoRoot status --porcelain' in text
    assert "requires a clean BodyRig checkout" in text
    assert 'git -C $repoRoot rev-parse HEAD' in text
    assert '--bodyrig-revision $revision' in text
    assert '--landmark-bodyrig-revision $landmarkRevision' in text
    assert 'bodyrig.hands_feet_nails_detail_candidate_cli' in text
    assert 'Python imported BodyRig outside the current checkout' in text
    assert 'prepare-hands-feet-nails-render-review.ps1' in text
    assert 'production_activation = $false' in text
    assert 'human_review_required = $true' in text
    assert 'comparison_only = $true' in text


def test_wrapper_does_not_accept_operator_supplied_candidate_revision() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    parameter_section = text.split(")\n\n$ErrorActionPreference", 1)[0]

    assert "CandidateBodyRigRevision" not in parameter_section
    assert "BodyRigRevision" not in parameter_section.replace("LandmarkBodyRigRevision", "")
    assert '$revision = (@(& git -C $repoRoot rev-parse HEAD' in text


def test_cli_keeps_candidate_comparison_only_and_non_activating() -> None:
    text = CLI.read_text(encoding="utf-8")

    assert '"comparison_only": True' in text
    assert '"human_review_required": True' in text
    assert '"production_activation": False' in text
    assert '"geometry_mutation_performed": False' in text
    assert 'write_detail_candidate(' in text
    assert 'person_library()' in text
