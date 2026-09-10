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
    assert '"--expected-baseline-bodyrig-revision", $baselineBodyRigRevision' in BUNDLE
    assert '"--expected-candidate-bodyrig-revision", $head' in BUNDLE


def test_bundle_wrapper_executes_review_module_from_exact_candidate_checkout() -> None:
    assert 'Push-Location -LiteralPath $RepoRoot' in BUNDLE
    assert '"bodyrig\\recovery_throughput_review_bundle.py"' in BUNDLE
    assert 'bodyrig.recovery_throughput_review_bundle' in BUNDLE
    assert 'importlib.import_module(sys.argv[1])' in BUNDLE
    assert 'Recovery throughput review bundle imported BodyRig from a different checkout' in BUNDLE
    assert '[Environment]::SetEnvironmentVariable("PYTHONPATH", $boundPythonPath, "Process")' in BUNDLE
    assert '[Environment]::SetEnvironmentVariable("PYTHONPATH", $previousPythonPath, "Process")' in BUNDLE
    assert 'if ($locationPushed) { Pop-Location }' in BUNDLE


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


def test_human_review_wrapper_is_bound_to_bundle_candidate_revision_and_checkout_module() -> None:
    assert 'review-bundle.json' in RECORD
    assert 'candidate_bodyrig_revision' in RECORD
    assert 'git -C $RepoRoot rev-parse HEAD' in RECORD
    assert 'git -C $RepoRoot status --porcelain' in RECORD
    assert 'Current BodyRig checkout does not match the review bundle candidate revision' in RECORD
    assert 'Push-Location -LiteralPath $RepoRoot' in RECORD
    assert '"bodyrig\\recovery_throughput_human_review.py"' in RECORD
    assert 'bodyrig.recovery_throughput_human_review' in RECORD
    assert 'importlib.import_module(sys.argv[1])' in RECORD
    assert 'Recovery throughput human review imported BodyRig from a different checkout' in RECORD
    assert '[Environment]::SetEnvironmentVariable("PYTHONPATH", $previousPythonPath, "Process")' in RECORD
    assert 'if ($locationPushed) { Pop-Location }' in RECORD


def test_human_review_wrapper_does_not_mutate_bundle_or_git() -> None:
    for command in ("Remove-Item", "Set-Content", "Out-File", "Move-Item", "Copy-Item", "git switch", "git checkout"):
        assert command not in RECORD
    assert "bodyrig.recovery_throughput_human_review" in RECORD
