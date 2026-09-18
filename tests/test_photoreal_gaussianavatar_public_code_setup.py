from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "setup-photoreal-gaussianavatar-public-code.ps1").read_text(encoding="utf-8")


def test_gaussianavatar_public_code_setup_pins_exact_revisions() -> None:
    assert 'd981c62238ef64e89dcc04719d2ebbb4758b080a' in SCRIPT
    assert '3cdfd49d00a5e6c1ebde4d6ae2784b5d6f7cd2bc' in SCRIPT
    assert 'git", "clone", "--no-checkout"' in SCRIPT
    assert '"checkout", "--detach"' in SCRIPT


def test_gaussianavatar_public_code_setup_is_atomic_and_clean() -> None:
    assert '.$leaf.stage-$PID' in SCRIPT
    assert 'status", "--porcelain"' in SCRIPT
    assert 'Invoke-Wsl -Root -Arguments @("/bin/mv", $stage, $LinuxDependencyRoot)' in SCRIPT
    assert SCRIPT.index('status", "--porcelain"') < SCRIPT.index('/bin/mv')


def test_gaussianavatar_public_code_setup_never_downloads_model_assets_or_grants_authority() -> None:
    assert '"automatic_model_asset_download": False' in SCRIPT
    assert '"production_dependency_authorized": False' in SCRIPT
    assert '"photoreal_acceptance_authority": False' in SCRIPT
    assert 'Model assets:       NOT DOWNLOADED' in SCRIPT
    assert 'Production:          FALSE' in SCRIPT
