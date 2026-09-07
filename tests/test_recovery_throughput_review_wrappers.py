from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = (ROOT / "build-recovery-throughput-review-bundle.ps1").read_text(encoding="utf-8")
RECORD = (ROOT / "record-recovery-throughput-human-review.ps1").read_text(encoding="utf-8")


def test_bundle_wrapper_is_exact_revision_bound_and_checkout_clean() -> None:
    assert "[string]$BaselineBodyRigRevision" in BUNDLE
    assert "ValidatePattern('^[0-9a-fA-F]{40}$')" in BUNDLE
    assert "git -C $RepoRoot rev-parse HEAD" in BUNDLE
    assert "git -C $RepoRoot status --porcelain" in BUNDLE
    assert "Baseline and candidate BodyRig revisions are identical" in BUNDLE
    assert "--expected-baseline-bodyrig-revision $baselineBodyRigRevision" in BUNDLE
    assert "--expected-candidate-bodyrig-revision $head" in BUNDLE


def test_bundle_wrapper_has_no_historical_branch_or_baseline_authority() -> None:
    assert "0b8f61b6f369e0d63ed006d808e316798121f79f" not in BUNDLE
    assert "agent/person-studio-photoreal-20260902" not in BUNDLE
    assert "agent/recovery-throughput-v3-20260903" not in BUNDLE
    assert "update-windows.ps1" not in BUNDLE


def test_human_review_wrapper_requires_explicit_four_axis_judgement_and_note() -> None:
    for name in ("IdentityShape", "FaceIdentity", "SkinTextureAlignment", "GrossAnatomy"):
        assert f"[string]${name}" in RECORD
    assert '[ValidateSet("pass", "fail")]' in RECORD
    assert "[string]$Note" in RECORD
    assert "This records human evidence only; it cannot promote or activate anything." in RECORD
    assert "promotion/production remain false" in RECORD


def test_human_review_wrapper_does_not_mutate_bundle_or_git() -> None:
    for command in ("Remove-Item", "Set-Content", "Out-File", "Move-Item", "Copy-Item", "git switch", "git checkout"):
        assert command not in RECORD
    assert "bodyrig.recovery_throughput_human_review" in RECORD
