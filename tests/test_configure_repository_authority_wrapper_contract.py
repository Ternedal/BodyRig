from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "configure-repository-authority.ps1").read_text(encoding="utf-8")


def test_admin_helper_is_exact_clean_main_and_checkout_bound() -> None:
    assert 'branch --show-current' in SCRIPT
    assert 'status --porcelain' in SCRIPT
    assert 'rev-parse HEAD' in SCRIPT
    assert 'repos/Ternedal/BodyRig/branches/main' in SCRIPT
    assert 'GitHub main does not match the exact local checkout' in SCRIPT


def test_admin_helper_requires_explicit_apply_and_refuses_unsafe_composition() -> None:
    assert '[switch]$Apply' in SCRIPT
    assert 'if (-not $Apply)' in SCRIPT
    assert 'DRY RUN' in SCRIPT
    assert 'No repository setting was changed' in SCRIPT
    assert '$rulesetPayload = Invoke-GhJson' in SCRIPT
    assert 'if ($null -eq $rulesetPayload) { @() } else { @($rulesetPayload) }' in SCRIPT
    assert 'Existing repository rulesets detected' in SCRIPT
    assert '[switch]$ReplaceExistingProtection' in SCRIPT
    assert 'Refusing to replace it without -ReplaceExistingProtection' in SCRIPT


def test_admin_helper_writes_exact_classic_authority_policy() -> None:
    for name in (
        'test (3.11)',
        'test (3.12)',
        'test-windows-python',
        'acceptance-windows',
        'adapter-log-handle',
    ):
        assert name in SCRIPT
    assert '$RequiredStatusCheckAppId = 15368' in SCRIPT
    assert 'app_id = $RequiredStatusCheckAppId' in SCRIPT
    assert 'strict = $true' in SCRIPT
    assert 'enforce_admins = $true' in SCRIPT
    assert 'required_approving_review_count = 0' in SCRIPT
    assert 'allow_force_pushes = $false' in SCRIPT
    assert 'allow_deletions = $false' in SCRIPT
    assert 'required_conversation_resolution = $true' in SCRIPT
    assert '--method PUT' in SCRIPT
    assert 'repos/Ternedal/BodyRig/branches/main/protection' in SCRIPT
    assert 'X-GitHub-Api-Version: 2026-03-10' in SCRIPT


def test_admin_helper_reverifies_and_never_claims_physical_authority() -> None:
    assert 'verify-repository-authority.ps1' in SCRIPT
    assert 'did not PASS' in SCRIPT
    assert 'no physical acceptance, candidate promotion, or production activation' in SCRIPT
