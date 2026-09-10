from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "audit-photoidentity-source-universe.ps1").read_text(encoding="utf-8")


def test_operator_requires_exact_clean_checkout_and_qualified_storage() -> None:
    lowered = SCRIPT.lower()
    assert "git -c $reporoot rev-parse head" in lowered
    assert "git -c $reporoot status --porcelain" in lowered
    assert "exact clean bodyrig checkout" in lowered
    assert '"storage-auth-status.ps1"' in lowered
    assert "-performerid $performerid -json" in lowered
    assert "$storage.qualified -ne $true" in lowered
    assert "cold_boots_passed" in lowered
    assert "cold_boots_required" in lowered
    assert "persistent storage authentication is not qualified" in lowered


def test_operator_refreshes_exact_path_map_and_uses_saved_dpapi_stash_secret() -> None:
    lowered = SCRIPT.lower()
    assert '"configure-stash-path-map.ps1"' in lowered
    assert "-performerid $performerid -forcerefresh" in lowered
    assert "api_key_dpapi" in lowered
    assert "converttosecurestring" in lowered
    assert "securestringtobstr" in lowered
    assert "zerofreebstr" in lowered
    assert "bodyrig.photoidentity_source_universe" in lowered


def test_operator_never_renders_reconstructs_or_persists_secret() -> None:
    lowered = SCRIPT.lower()
    assert "unity" not in lowered
    assert "reference-renderer" not in lowered
    assert "quest" not in lowered
    assert "sith_reconstruct" not in lowered
    assert "clone-body" not in lowered
    assert "cmdkey" not in lowered
    assert "/pass:" not in lowered
    assert "generic guessing:        false" in lowered
    assert "render permitted:        false" in lowered
