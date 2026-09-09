from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "REPOSITORY_AUTHORITY.md").read_text(encoding="utf-8")
HANDOFF = (ROOT / "HANDOFF.md").read_text(encoding="utf-8")


def test_runbook_names_canonical_verifier_and_current_fail_state() -> None:
    assert ".\\verify-repository-authority.ps1" in DOC
    assert "FAIL is the expected result" in DOC
    assert "Issue #138 remains open" in DOC


def test_runbook_lists_exact_required_checks_and_repository_boundaries() -> None:
    for name in (
        "test (3.11)",
        "test (3.12)",
        "test-windows-python",
        "acceptance-windows",
        "adapter-log-handle",
        "CodeQL",
    ):
        assert name in DOC
    assert "all six required" in DOC.lower()
    assert "require the branch to be up to date before merge" in DOC
    assert "prevent force/non-fast-forward pushes" in DOC
    assert "prevent deletion of `main`" in DOC
    assert "bypass actors" in DOC
    assert "bypass_pull_request_allowances" in DOC
    assert "users, teams and apps" in DOC
    assert "does not create or imply physical acceptance" in DOC


def test_runbook_records_the_observed_base_race_and_makes_strict_hard() -> None:
    assert "#252" in DOC
    assert "#253" in DOC
    assert "advanced `main` immediately before #252 was squash-merged" in DOC
    assert "A stale PR is a repository-authority failure, not a warning" in DOC
    assert "strict_required_status_checks_policy=true" in DOC


def test_runbook_requires_per_check_source_binding() -> None:
    assert "GitHub Actions" in DOC
    assert "app/integration ID `15368`" in DOC
    assert "GitHub Advanced Security" in DOC
    assert "app/integration ID `57789`" in DOC
    assert "`CodeQL` must be bound" in DOC
    assert "matching context name alone is not sufficient" in DOC.lower()
    assert "`analyze (python)`" in DOC
    assert "merge-bound security check is that `CodeQL` result" in DOC


def test_runbook_documents_explicit_admin_helper_and_safe_defaults() -> None:
    assert ".\\configure-repository-authority.ps1" in DOC
    assert ".\\configure-repository-authority.ps1 -Apply" in DOC
    assert "dry run" in DOC.lower()
    assert "required_approving_review_count=0" in DOC
    assert "strict=true" in DOC
    assert "refuses to compose over existing repository rulesets" in DOC
    assert "-ReplaceExistingProtection" in DOC


def test_handoff_matches_per_check_codeql_and_strict_repository_authority() -> None:
    assert "exact six checks" in HANDOFF
    assert "`CodeQL`" in HANDOFF
    assert "`57789`" in HANDOFF
    assert "`15368`" in HANDOFF
    assert "`analyze (python)`" in HANDOFF
    assert "not the merge-bound security result" in HANDOFF
    assert "strict=true" in HANDOFF
    assert "up to date before merge" in HANDOFF
    assert "all six required checks" in HANDOFF
    assert "all six required checks to GitHub Actions" not in HANDOFF
    assert "all five required checks" not in HANDOFF
    assert "exact five checks" not in HANDOFF
