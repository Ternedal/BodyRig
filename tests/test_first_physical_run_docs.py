from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_first_physical_run_documents_stash_discovery_and_canonical_clone() -> None:
    text = (ROOT / "docs" / "FIRST_PHYSICAL_RUN.md").read_text(encoding="utf-8")
    required = (
        '.\\stash-sources.ps1 health',
        '.\\stash-sources.ps1 search "<performer name>" -Limit 10',
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


def test_first_physical_run_keeps_stash_credentials_out_of_command_arguments() -> None:
    text = (ROOT / "docs" / "FIRST_PHYSICAL_RUN.md").read_text(encoding="utf-8")
    assert '$env:STASH_API_KEY = "<local Stash API key if required>"' in text
    assert '--api-key ' not in text
    assert '-ApiKey ' not in text


def test_first_physical_run_does_not_require_console_script_path() -> None:
    text = (ROOT / "docs" / "FIRST_PHYSICAL_RUN.md").read_text(encoding="utf-8")
    assert 'Do not rely on `bodyrig-stash-sources` being present on the shell `PATH`.' in text
