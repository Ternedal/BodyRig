from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "verify-repository-authority.ps1").read_text(encoding="utf-8")


def test_wrapper_is_clean_main_and_checkout_bound() -> None:
    assert 'branch --show-current' in SCRIPT
    assert 'status --porcelain' in SCRIPT
    assert 'rev-parse HEAD' in SCRIPT
    assert 'bodyrig.repository_authority' in SCRIPT
    assert 'repository_authority.py' in SCRIPT
    assert 'imported from wrong checkout' in SCRIPT
    assert '--expected-head' in SCRIPT


def test_wrapper_reads_live_github_repository_authority() -> None:
    assert 'gh auth status -h github.com' in SCRIPT
    assert 'repos/Ternedal/BodyRig/branches/main' in SCRIPT
    assert 'repos/Ternedal/BodyRig/branches/main/protection' in SCRIPT
    assert 'repos/Ternedal/BodyRig/rulesets?includes_parents=true' in SCRIPT
    assert 'repos/Ternedal/BodyRig/rulesets/$id' in SCRIPT


def test_wrapper_is_read_only_and_non_physical() -> None:
    assert 'gh api' in SCRIPT
    assert 'gh api --method' not in SCRIPT
    assert 'physical acceptance or production activation' in SCRIPT
    assert 'exit 2' in SCRIPT
    assert 'BodyRig repository authority:' in SCRIPT
