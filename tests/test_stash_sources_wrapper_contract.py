from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_stash_discovery_wrapper_binds_to_checkout_python_authority() -> None:
    text = (ROOT / "stash-sources.ps1").read_text(encoding="utf-8")
    required = (
        '.venv\\Scripts\\python.exe',
        'Push-Location $repoRoot',
        'bodyrig\\__init__.py',
        'bodyrig.__file__',
        '-m bodyrig.stash_cli',
        '[ValidateSet("health", "search", "probe")]',
        'Probe requires -PerformerId.',
        '"--performer-id", $PerformerId',
    )
    for marker in required:
        assert marker in text


def test_stash_discovery_wrapper_does_not_depend_on_console_script_path() -> None:
    text = (ROOT / "stash-sources.ps1").read_text(encoding="utf-8")
    assert 'Resolve-CommandPath "bodyrig-stash-sources"' not in text
    assert '& bodyrig-stash-sources' not in text
