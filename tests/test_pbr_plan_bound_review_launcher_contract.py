from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "run-pbr-ab-from-body-job-plan-bound.ps1").read_text(encoding="utf-8")


def test_launcher_delegates_machine_run_to_existing_plan_bound_runner() -> None:
    assert 'run-pbr-ab-from-body-job.ps1' in SCRIPT
    assert 'record-pbr-ab-human-review-from-plan.ps1' in SCRIPT
    runner = SCRIPT.index('& $runner @runnerParams')
    plan_receipt = SCRIPT.index('body-job-plan-authority.json')
    rewrite = SCRIPT.index('Write-AtomicUtf8Text -Path $reviewNextPath')
    assert runner < plan_receipt < rewrite


def test_launcher_requires_exact_plan_authority_chain_before_review_routing() -> None:
    assert 'bodyrig-pbr-ab-body-job-plan-authority' in SCRIPT
    assert 'run_authority_sha256' in SCRIPT
    assert 'source_authority_sha256' in SCRIPT
    assert 'PBR plan authority no longer binds the exact run/source authority bytes.' in SCRIPT
    assert '$planAuthority.comparison_only -ne $true' in SCRIPT
    assert '$planAuthority.human_visual_authority_required -ne $true' in SCRIPT
    assert '$planAuthority.physical_acceptance_authority -ne $false' in SCRIPT
    assert '$planAuthority.promotion_authority -ne $false' in SCRIPT
    assert '$planAuthority.production_activation -ne $false' in SCRIPT


def test_review_next_routes_only_to_plan_bound_human_recorder() -> None:
    assert '$reviewNextPath = Join-Path $OutputDir "REVIEW-NEXT.txt"' in SCRIPT
    assert '.\\record-pbr-ab-human-review-from-plan.ps1' in SCRIPT
    assert "-Decision '<left|right|tie|reject-both>'" in SCRIPT
    assert "-QualityNote '<actual visual assessment>'" in SCRIPT
    assert '-ConfirmVisualReview' in SCRIPT
    assert 'record-fidelity-ab-review.ps1' not in SCRIPT
    assert 'The recorder rejects placeholder values.' in SCRIPT


def test_review_routing_is_atomic_and_non_activating() -> None:
    assert 'Move-Item -LiteralPath $temp -Destination $Path -Force' in SCRIPT
    assert 'Human review already exists; refusing to rewrite review routing' in SCRIPT
    assert 'Plan-bound human-review authority already exists; refusing to rewrite review routing' in SCRIPT
    assert 'READY FOR EXPLICIT HUMAN REVIEW' in SCRIPT
    assert 'no physical acceptance, promotion or production activation' in SCRIPT
