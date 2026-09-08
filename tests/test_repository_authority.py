from __future__ import annotations

from bodyrig.repository_authority import REQUIRED_STATUS_CHECKS, evaluate_repository_authority


HEAD = "a" * 40


def branch(*, protected: bool = True) -> dict:
    return {"name": "main", "protected": protected, "commit": {"sha": HEAD}}


def classic(*, missing: str | None = None, enforce_admins: bool = True) -> dict:
    checks = [name for name in REQUIRED_STATUS_CHECKS if name != missing]
    return {
        "required_status_checks": {"strict": True, "contexts": checks, "checks": []},
        "required_pull_request_reviews": {},
        "enforce_admins": {"enabled": enforce_admins},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_conversation_resolution": {"enabled": True},
    }


def ruleset(*, bypass: bool = False, missing: str | None = None) -> dict:
    checks = [{"context": name} for name in REQUIRED_STATUS_CHECKS if name != missing]
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
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": checks,
                },
            },
        ],
    }


def test_classic_branch_protection_can_satisfy_repository_authority() -> None:
    result = evaluate_repository_authority(branch(), classic_protection=classic(), expected_head=HEAD)
    assert result["passed"] is True
    assert result["authority_mode"] == "classic"
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

    bypass = evaluate_repository_authority(branch(), classic_protection=classic(enforce_admins=False))
    assert bypass["passed"] is False
    assert "administrators can bypass branch protection" in bypass["classic"]["errors"]


def test_active_ruleset_can_satisfy_equivalent_repository_authority() -> None:
    result = evaluate_repository_authority(branch(), rulesets=[ruleset()], expected_head=HEAD)
    assert result["passed"] is True
    assert result["authority_mode"] == "ruleset"


def test_ruleset_fails_closed_on_bypass_actor_or_missing_check() -> None:
    bypass = evaluate_repository_authority(branch(), rulesets=[ruleset(bypass=True)])
    assert bypass["passed"] is False
    assert "ruleset 42 has bypass actors" in bypass["rulesets"]["errors"]

    missing = evaluate_repository_authority(branch(), rulesets=[ruleset(missing="test-windows-python")])
    assert missing["passed"] is False
    assert missing["rulesets"]["missing_checks"] == ["test-windows-python"]


def test_expected_head_is_revision_bound() -> None:
    result = evaluate_repository_authority(branch(), classic_protection=classic(), expected_head="b" * 40)
    assert result["passed"] is False
    assert "GitHub main head does not match the expected checkout revision" in result["errors"]
