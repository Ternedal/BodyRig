from __future__ import annotations

from pathlib import Path

from bodyrig.repository_authority import (
    REQUIRED_CODEQL_APP_ID,
    REQUIRED_STATUS_CHECK_APP_ID,
    REQUIRED_STATUS_CHECKS,
    evaluate_repository_authority,
)


ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40


def _expected_app_id(name: str) -> int:
    return REQUIRED_CODEQL_APP_ID if name == "CodeQL" else REQUIRED_STATUS_CHECK_APP_ID


def branch(*, protected: bool = True) -> dict:
    return {"name": "main", "protected": protected, "commit": {"sha": HEAD}}


def classic(
    *,
    missing: str | None = None,
    enforce_admins: bool = True,
    bypass_category: str | None = None,
    wrong_source: str | None = None,
    strict: bool = True,
) -> dict:
    checks = [name for name in REQUIRED_STATUS_CHECKS if name != missing]
    check_entries = [
        {
            "context": name,
            "app_id": -1 if name == wrong_source else _expected_app_id(name),
        }
        for name in checks
    ]
    bypass = {"users": [], "teams": [], "apps": []}
    if bypass_category == "users":
        bypass["users"] = [{"login": "octocat"}]
    elif bypass_category == "teams":
        bypass["teams"] = [{"slug": "release-admins"}]
    elif bypass_category == "apps":
        bypass["apps"] = [{"slug": "release-app"}]
    return {
        "required_status_checks": {"strict": strict, "contexts": checks, "checks": check_entries},
        "required_pull_request_reviews": {"bypass_pull_request_allowances": bypass},
        "enforce_admins": {"enabled": enforce_admins},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_conversation_resolution": {"enabled": True},
    }


def ruleset(
    *,
    bypass: bool = False,
    missing: str | None = None,
    wrong_source: str | None = None,
    strict: bool = True,
) -> dict:
    checks = [
        {
            "context": name,
            "integration_id": -1 if name == wrong_source else _expected_app_id(name),
        }
        for name in REQUIRED_STATUS_CHECKS
        if name != missing
    ]
    return {
        "id": 42,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "bypass_actors": [{"actor_type": "RepositoryRole"}] if bypass else [],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {"required_review_thread_resolution": True},
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": strict,
                    "required_status_checks": checks,
                },
            },
        ],
    }


def test_required_checks_include_source_bound_codeql_result() -> None:
    assert "CodeQL" in REQUIRED_STATUS_CHECKS
    assert "analyze (python)" not in REQUIRED_STATUS_CHECKS
    assert len(REQUIRED_STATUS_CHECKS) == 6
    assert REQUIRED_STATUS_CHECK_APP_ID == 15368
    assert REQUIRED_CODEQL_APP_ID == 57789


def test_classic_branch_protection_can_satisfy_repository_authority() -> None:
    result = evaluate_repository_authority(branch(), classic_protection=classic(), expected_head=HEAD)
    assert result["passed"] is True
    assert result["authority_mode"] == "classic"
    assert result["required_status_check_app_id"] == 15368
    assert result["required_status_check_sources"]["CodeQL"] == 57789
    assert result["classic"]["source_bound_checks"] == sorted(REQUIRED_STATUS_CHECKS)
    assert result["classic"]["wrong_source_checks"] == []
    assert result["classic"]["pull_request_bypass_categories"] == []
    assert result["classic"]["strict_required_status_checks"] is True
    assert result["physical_acceptance_authority"] is False
    assert result["production_activation"] is False


def test_unprotected_main_fails_even_if_policy_payload_looks_valid() -> None:
    result = evaluate_repository_authority(branch(protected=False), classic_protection=classic(), expected_head=HEAD)
    assert result["passed"] is False
    assert "GitHub reports main as unprotected" in result["errors"]


def test_classic_requires_every_exact_green_check_and_admin_enforcement() -> None:
    missing = evaluate_repository_authority(branch(), classic_protection=classic(missing="adapter-log-handle"))
    assert missing["passed"] is False
    assert missing["classic"]["missing_checks"] == ["adapter-log-handle"]

    codeql_missing = evaluate_repository_authority(branch(), classic_protection=classic(missing="CodeQL"))
    assert codeql_missing["passed"] is False
    assert codeql_missing["classic"]["missing_checks"] == ["CodeQL"]

    bypass = evaluate_repository_authority(branch(), classic_protection=classic(enforce_admins=False))
    assert bypass["passed"] is False
    assert "administrators can bypass branch protection" in bypass["classic"]["errors"]


def test_classic_requires_up_to_date_branch_policy() -> None:
    result = evaluate_repository_authority(branch(), classic_protection=classic(strict=False))
    assert result["passed"] is False
    assert result["classic"]["strict_required_status_checks"] is False
    assert "required status checks do not require an up-to-date branch" in result["classic"]["errors"]


def test_classic_fails_closed_on_pull_request_bypass_allowances() -> None:
    for category in ("users", "teams", "apps"):
        result = evaluate_repository_authority(
            branch(),
            classic_protection=classic(bypass_category=category),
        )
        assert result["passed"] is False
        assert result["classic"]["pull_request_bypass_categories"] == [category]
        assert f"pull request requirements have bypass allowances: {category}" in result["classic"]["errors"]


def test_classic_requires_expected_source_binding_per_check() -> None:
    actions = evaluate_repository_authority(
        branch(),
        classic_protection=classic(wrong_source="test (3.11)"),
    )
    assert actions["passed"] is False
    assert actions["classic"]["wrong_source_checks"] == ["test (3.11)"]

    codeql = evaluate_repository_authority(
        branch(),
        classic_protection=classic(wrong_source="CodeQL"),
    )
    assert codeql["passed"] is False
    assert codeql["classic"]["wrong_source_checks"] == ["CodeQL"]
    assert codeql["classic"]["required_check_sources"]["CodeQL"] == 57789
    assert "required status checks are not bound to their expected GitHub Apps" in codeql["classic"]["errors"]


def test_active_ruleset_can_satisfy_equivalent_repository_authority() -> None:
    result = evaluate_repository_authority(branch(), rulesets=[ruleset()], expected_head=HEAD)
    assert result["passed"] is True
    assert result["authority_mode"] == "ruleset"
    assert result["rulesets"]["source_bound_checks"] == sorted(REQUIRED_STATUS_CHECKS)
    assert result["rulesets"]["required_check_sources"]["CodeQL"] == 57789
    assert result["rulesets"]["wrong_source_checks"] == []
    assert result["rulesets"]["strict_required_status_checks"] is True


def test_ruleset_fails_closed_on_bypass_actor_or_missing_check() -> None:
    bypass = evaluate_repository_authority(branch(), rulesets=[ruleset(bypass=True)])
    assert bypass["passed"] is False
    assert "ruleset 42 has bypass actors" in bypass["rulesets"]["errors"]

    missing = evaluate_repository_authority(branch(), rulesets=[ruleset(missing="test-windows-python")])
    assert missing["passed"] is False
    assert missing["rulesets"]["missing_checks"] == ["test-windows-python"]

    codeql_missing = evaluate_repository_authority(branch(), rulesets=[ruleset(missing="CodeQL")])
    assert codeql_missing["passed"] is False
    assert codeql_missing["rulesets"]["missing_checks"] == ["CodeQL"]


def test_ruleset_requires_up_to_date_branch_policy() -> None:
    result = evaluate_repository_authority(branch(), rulesets=[ruleset(strict=False)])
    assert result["passed"] is False
    assert result["rulesets"]["strict_required_status_checks"] is False
    assert "required status checks do not require an up-to-date branch" in result["rulesets"]["errors"]


def test_ruleset_requires_expected_source_binding_per_check() -> None:
    actions = evaluate_repository_authority(
        branch(),
        rulesets=[ruleset(wrong_source="adapter-log-handle")],
    )
    assert actions["passed"] is False
    assert actions["rulesets"]["wrong_source_checks"] == ["adapter-log-handle"]

    codeql = evaluate_repository_authority(
        branch(),
        rulesets=[ruleset(wrong_source="CodeQL")],
    )
    assert codeql["passed"] is False
    assert codeql["rulesets"]["wrong_source_checks"] == ["CodeQL"]
    assert "required status checks are not bound to their expected GitHub Apps" in codeql["rulesets"]["errors"]


def test_expected_head_is_revision_bound() -> None:
    result = evaluate_repository_authority(branch(), classic_protection=classic(), expected_head="b" * 40)
    assert result["passed"] is False
    assert "GitHub main head does not match the expected checkout revision" in result["errors"]


def test_repository_admin_helper_binds_codeql_result_to_ghas_app() -> None:
    text = (ROOT / "configure-repository-authority.ps1").read_text(encoding="utf-8")
    assert '$RequiredCodeQlAppId = 57789' in text
    assert '[ordered]@{ context = "CodeQL"; app_id = $RequiredCodeQlAppId }' in text
    assert 'Required CodeQL result source: GitHub Advanced Security app $RequiredCodeQlAppId' in text
