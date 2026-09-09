from __future__ import annotations

from pathlib import Path


DOC = (Path(__file__).resolve().parents[1] / "docs" / "REPOSITORY_AUTHORITY.md").read_text(encoding="utf-8")


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
        "analyze (python)",
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
    assert "PR #252" in DOC
    assert "PR #253" in DOC
    assert "advanced `main` immediately before #252 was squash-merged" in DOC
    assert "A stale PR is a repository-authority failure, not a warning" in DOC
    assert "strict_required_status_checks_policy=true" in DOC


def test_runbook_requires_github_actions_source_binding() -> None:
    assert "GitHub Actions" in DOC
    assert "app/integration ID `15368`" in DOC
    assert "app_id=15368" in DOC
    assert "integration_id=15368" in DOC
    assert "matching context name alone is not sufficient" in DOC
    assert "separate GitHub Advanced Security bot/summary surface is not a substitute" in DOC


def test_runbook_documents_explicit_admin_helper_and_safe_defaults() -> None:
    assert ".\\configure-repository-authority.ps1" in DOC
    assert ".\\configure-repository-authority.ps1 -Apply" in DOC
    assert "dry run" in DOC.lower()
    assert "required_approving_review_count=0" in DOC
    assert "strict=true" in DOC
    assert "refuses to compose over existing repository rulesets" in DOC
    assert "-ReplaceExistingProtection" in DOC
