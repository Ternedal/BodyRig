from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_first_physical_run_documents_stash_discovery_and_canonical_clone() -> None:
    text = (ROOT / "docs" / "FIRST_PHYSICAL_RUN.md").read_text(encoding="utf-8")
    required = (
        '.\\stash-sources.ps1 health',
        '.\\stash-sources.ps1 search "<performer name>" -Limit 10',
        '.\\stash-sources.ps1 probe -PerformerId "123"',
        '.\\clone-body-from-stash-ready.ps1',
        '-PerformerId "123"',
        '-BodyId "performer-123"',
        'bodyid-<24 lowercase hex>',
        '.\\physical-acceptance-status.ps1',
        '.\\accept-physical-clone.ps1',
        '-ConfirmQualityChecklist',
        'production_activation=true',
    )
    for marker in required:
        assert marker in text


def test_first_physical_run_requires_fresh_stash_token_health_before_clone() -> None:
    text = (ROOT / "docs" / "FIRST_PHYSICAL_RUN.md").read_text(encoding="utf-8")
    assert '$env:STASH_API_KEY = "<fresh local Stash API key>"' in text
    assert 'fresh Stash token works before search or clone' in text
    assert 'Do not continue to performer search or clone unless it succeeds with the fresh token.' in text
    assert '`performer_read=true`' in text
    assert 'the fresh Stash token passed the checkout-bound `health` gate with `ok=true` and `performer_read=true`' in text
    assert text.index('.\\stash-sources.ps1 health') < text.index('.\\stash-sources.ps1 search')
    assert text.index('.\\stash-sources.ps1 health') < text.index('.\\stash-sources.ps1 probe')
    assert text.index('.\\stash-sources.ps1 health') < text.index('.\\clone-body-from-stash-ready.ps1')


def test_first_physical_run_probes_exact_performer_without_leaking_paths_or_writing_evidence() -> None:
    text = (ROOT / "docs" / "FIRST_PHYSICAL_RUN.md").read_text(encoding="utf-8")
    assert '.\\stash-sources.ps1 probe -PerformerId "123"' in text
    assert 'usable_source_count' in text
    assert 'does **not** print local source paths' in text
    assert 'does **not** write a source manifest' in text
    assert 'repeats this same selected-performer/source-pool gate automatically' in text
    assert text.index('.\\stash-sources.ps1 search') < text.index('.\\stash-sources.ps1 probe')
    assert text.index('.\\stash-sources.ps1 probe') < text.index('.\\clone-body-from-stash-ready.ps1')


def test_first_physical_run_keeps_stash_credentials_out_of_command_arguments() -> None:
    text = (ROOT / "docs" / "FIRST_PHYSICAL_RUN.md").read_text(encoding="utf-8")
    assert '$env:STASH_API_KEY = "<fresh local Stash API key>"' in text
    assert '--api-key ' not in text
    assert '-ApiKey ' not in text


def test_first_physical_run_does_not_require_console_script_path() -> None:
    text = (ROOT / "docs" / "FIRST_PHYSICAL_RUN.md").read_text(encoding="utf-8")
    assert 'Do not rely on `bodyrig-stash-sources` being present on the shell `PATH`.' in text


def test_windows_setup_next_steps_require_authenticated_stash_discovery() -> None:
    text = (ROOT / "setup-rig-windows.ps1").read_text(encoding="utf-8")
    assert 'configure a fresh local Stash API token' in text
    assert '.\\stash-sources.ps1 health' in text
    assert '.\\stash-sources.ps1 search' in text
    assert 'docs\\FIRST_PHYSICAL_RUN.md' in text
    assert text.index('.\\stash-sources.ps1 health') < text.index('.\\stash-sources.ps1 search')
