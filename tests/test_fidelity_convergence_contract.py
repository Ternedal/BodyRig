from __future__ import annotations

import hashlib
from pathlib import Path

from bodyrig.bridges.opencv_fidelity_evaluator import combined_reference_sha


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_measurement_reference_authority_binds_stash_and_private_body_reference() -> None:
    stash = "a" * 64
    body = "b" * 64
    expected = hashlib.sha256(f"{stash}:{body}".encode("ascii")).hexdigest()
    assert combined_reference_sha(stash, body) == expected
    assert combined_reference_sha(stash, None) == stash


def test_evaluator_requires_explicit_photorealism_human_plausibility_and_definition() -> None:
    source = text("bodyrig/bridges/opencv_fidelity_evaluator.py")
    assert 'REVISION = "4"' in source
    assert '"photorealism"' in source
    assert '"human_plausibility"' in source
    assert "photo_statistics_similarity" in source
    assert "facial_definition_similarity" in source
    assert "bilateral_face_plausibility" in source
    assert "head_shoulder_plausibility" in source
    assert "skin_liveliness_similarity" in source
    assert "broad-render-plausibility-and-definition-not-age-or-identity-classification" in source
    assert "combined_reference_sha" in source
    assert "human_visual_authority_required" in source


def test_convergence_requires_human_plausibility_before_human_review() -> None:
    source = text("bodyrig/fidelity_convergence.py")
    assert '"human_plausibility"' in source
    assert "human_plausibility: float = 0.82" in source
    assert 'strategy = "plausibility-search"' in source
    assert "implausible or uncanny" in source


def test_physical_loop_freezes_source_body_reference_and_never_promotes_automatically() -> None:
    source = text("run-profiled-fidelity-convergence.ps1")
    assert 'private-body-reference-rgba.png' in source
    assert 'Frozen body reference changed during convergence.' in source
    assert '--body-reference-rgba", $frozenBodyReference' in source
    assert 'scores.photorealism' in source
    assert 'best_scores.photorealism' in source
    assert 'best_comparison_render_dir' in source
    assert 'appearance-search' in source
    assert 'production_activation = $false' in source
    assert 'human_visual_authority_required = $true' in source
    assert 'complete-reference-renderer-acceptance' not in source
    assert 'complete-acceptance.ps1' not in source
    assert 'Quest' in source


def test_comparison_renderer_is_separate_from_acceptance_evidence() -> None:
    source = text("run-fidelity-windows-render-probe.ps1")
    assert "fidelity-render-set.json" in source
    assert "visual-fidelity-not-identity-verification" in source
    assert "windows-evidence" not in source
    assert "human" in source.lower()
