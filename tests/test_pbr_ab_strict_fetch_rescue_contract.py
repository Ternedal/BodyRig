from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "rescue-pbr-ab-after-strict-fetch-binding-bug.ps1").read_text(encoding="utf-8")


def test_rescue_is_scoped_to_exact_known_baseline_and_reviewed_blobs() -> None:
    assert '"6e10351e4eba929062960ac46ec1582a467db259"' in SCRIPT
    assert '"73d5af8c4bdadff00d5cb3685e2e7e8bbd945d04"' in SCRIPT
    assert '"daa5361880a32c341a87342a58c6f8fc575882c7"' in SCRIPT
    assert '"0c4d6cc1cdd07081ae88e3b08ea07d8550c9b83f"' in SCRIPT
    assert '"1535e07b88ad7fdafb9b26f03abb1ae0bfcd550b"' in SCRIPT
    assert "This rescue is scoped only to baseline" in SCRIPT


def test_rescue_repairs_both_strict_fetch_bindings_only_in_temp_overlay() -> None:
    assert 'Invoke-Git -Arguments (@("-C",$repoRoot,"fetch","--no-tags","origin") + $fetchSpecs) -Step "Fetch baseline/candidate refs"' in SCRIPT
    assert 'Invoke-Git -Arguments (@("-C",$repoRoot,"fetch","--no-tags","origin") + $fetchSpecs) -Step "Recheck remote refs after A/B"' in SCRIPT
    assert 'Replace-ExactOnce -Text $strictText' in SCRIPT
    assert 'BODYRIG_RESCUE_STRICT_RUNNER' in SCRIPT
    assert 'BODYRIG_RESCUE_INTERNAL' in SCRIPT
    assert 'bodyrig-pbr-strict-fetch-rescue-' in SCRIPT
    assert 'repo_checkout_mutated = $false' in SCRIPT
    assert "git checkout" not in SCRIPT.lower()
    assert "git switch" not in SCRIPT.lower()
    assert "update-index" not in SCRIPT.lower()


def test_rescue_requires_prior_exact_fidelity_mirror_repair() -> None:
    assert 'review-mirror-repair-authority.json' in SCRIPT
    assert 'bodyrig-fidelity-review-mirror-repair-authority' in SCRIPT
    assert 'succeeded-ui-job-persisted-review-not-mirrored-to-fidelity-output' in SCRIPT
    assert '$mirrorSha -ne $expectedReviewSha' in SCRIPT
    assert 'human_visual_authority_created -ne $false' in SCRIPT


def test_rescue_preserves_canonical_plan_bound_launcher_and_terminal_authority() -> None:
    assert 'rescue-pbr-ab-after-splat-bug.ps1' in SCRIPT
    assert 'body-job-source-authority.json' in SCRIPT
    assert 'body-job-plan-authority.json' in SCRIPT
    assert 'launcher-rescue-authority.json' in SCRIPT
    assert 'strict-fetch-rescue-authority.json' in SCRIPT
    assert 'review.html' in SCRIPT
    assert 'REVIEW-NEXT.txt' in SCRIPT
    assert 'comparison_only = $true' in SCRIPT
    assert 'human_visual_authority_required = $true' in SCRIPT
    assert 'physical_acceptance_authority = $false' in SCRIPT
    assert 'promotion_authority = $false' in SCRIPT
    assert 'production_activation = $false' in SCRIPT
