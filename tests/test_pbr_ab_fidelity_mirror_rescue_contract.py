from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "rescue-pbr-ab-after-fidelity-mirror-bug.ps1").read_text(encoding="utf-8")


def test_repair_is_bound_to_exact_succeeded_job_and_clean_main() -> None:
    assert '"bodyrig-ui-job"' in SCRIPT
    assert '"body-build"' in SCRIPT
    assert '"succeeded"' in SCRIPT
    assert "Assert-CleanMain -Root $RepoRoot -ExpectedRevision $mainRevision" in SCRIPT
    assert '"status","--porcelain"' in SCRIPT
    assert '"refs/remotes/origin/main"' in SCRIPT
    assert "git checkout" not in SCRIPT.lower()
    assert "git switch" not in SCRIPT.lower()


def test_repair_revalidates_canonical_review_and_fidelity_bytes() -> None:
    assert "bodyrig.person_body_review" in SCRIPT
    assert "read_review" in SCRIPT
    assert "validate_fidelity_output" in SCRIPT
    assert "job.body_review_sha256" in SCRIPT
    assert "canonical persisted body review receipt" in SCRIPT
    assert "Get-FileHash -LiteralPath $canonicalReview -Algorithm SHA256" in SCRIPT
    assert 'Join-Path $fidelityDir "comparison-authority.json"' in SCRIPT
    assert 'Join-Path $fidelityDir "snapshots\\fidelity-render-set.json"' in SCRIPT


def test_repair_creates_only_an_exact_byte_mirror_and_never_overwrites_mismatch() -> None:
    assert 'Join-Path $fidelityDir "review.json"' in SCRIPT
    assert "Existing fidelity review mirror differs from canonical persisted review; refusing overwrite." in SCRIPT
    assert "[IO.File]::Copy($canonicalReview,$tempMirror,$false)" in SCRIPT
    assert "[IO.File]::Move($tempMirror,$mirrorPath)" in SCRIPT
    assert "$tempSha -ne $expectedReviewSha" in SCRIPT
    assert "$mirrorSha -ne $expectedReviewSha" in SCRIPT


def test_repair_receipt_cannot_claim_human_physical_or_production_authority() -> None:
    assert 'format = "bodyrig-fidelity-review-mirror-repair-authority"' in SCRIPT
    assert "comparison_only = $true" in SCRIPT
    assert "human_visual_authority_created = $false" in SCRIPT
    assert "physical_acceptance_authority = $false" in SCRIPT
    assert "promotion_authority = $false" in SCRIPT
    assert "production_activation = $false" in SCRIPT


def test_repair_delegates_to_exact_previously_green_launcher_rescue() -> None:
    assert '$CanonicalLauncherRescueRevision = "73d5af8c4bdadff00d5cb3685e2e7e8bbd945d04"' in SCRIPT
    assert '${CanonicalLauncherRescueRevision}:rescue-pbr-ab-after-splat-bug.ps1' in SCRIPT
    assert "OperatorPatchRevision = $CanonicalLauncherRescueRevision" in SCRIPT
    assert "& $tempRescue @params" in SCRIPT
