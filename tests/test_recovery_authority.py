from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.recovery_authority import (
    RIG_SETUP_ENV,
    RecoveryAuthorityError,
    resolve_phalp_repo,
)


ROOT = Path(__file__).resolve().parents[1]


def _rig_report(tmp_path: Path, *, four_d: Path, phalp: Path) -> Path:
    report = tmp_path / "rig-setup.json"
    report.write_text(
        json.dumps(
            {
                "format": "bodyrig-rig-setup",
                "version": 1,
                "recovery": {
                    "four_d_humans_repo": str(four_d),
                    "phalp_repo": str(phalp),
                },
            }
        ),
        encoding="utf-8",
    )
    return report


def test_resolve_phalp_repo_uses_byte_bound_ready_rig_authority(tmp_path: Path):
    four_d = tmp_path / "recovery" / "4D-Humans"
    phalp = tmp_path / "recovery" / "PHALP"
    four_d.mkdir(parents=True)
    phalp.mkdir()
    report = _rig_report(tmp_path, four_d=four_d, phalp=phalp)

    resolved = resolve_phalp_repo(
        four_d,
        environ={RIG_SETUP_ENV: str(report)},
    )
    assert resolved == phalp.resolve()


def test_resolve_phalp_repo_rejects_rig_setup_for_other_4d_checkout(tmp_path: Path):
    actual_four_d = tmp_path / "actual" / "4D-Humans"
    bound_four_d = tmp_path / "bound" / "4D-Humans"
    phalp = tmp_path / "bound" / "PHALP"
    actual_four_d.mkdir(parents=True)
    bound_four_d.mkdir(parents=True)
    phalp.mkdir()
    report = _rig_report(tmp_path, four_d=bound_four_d, phalp=phalp)

    with pytest.raises(RecoveryAuthorityError, match="does not match"):
        resolve_phalp_repo(
            actual_four_d,
            environ={RIG_SETUP_ENV: str(report)},
        )


def test_resolve_phalp_repo_keeps_low_level_managed_sibling_fallback(tmp_path: Path):
    four_d = tmp_path / "recovery" / "4D-Humans"
    four_d.mkdir(parents=True)
    assert resolve_phalp_repo(four_d, environ={}) == (four_d.parent / "PHALP").resolve()


def test_clone_recovery_wiring_carries_phalp_authority_into_external_bridge():
    ready = (ROOT / "clone-body-from-stash-ready.ps1").read_text(encoding="utf-8")
    clone = (ROOT / "clone-body.ps1").read_text(encoding="utf-8")
    recover = (ROOT / "bodyrig" / "recover_cli.py").read_text(encoding="utf-8")
    bridge = (ROOT / "bodyrig" / "bridges" / "hmr2_4dhumans_bridge.py").read_text(encoding="utf-8")

    assert "BODYRIG_RIG_SETUP_REPORT = $RigSetupReport" in ready
    assert '"-m", "bodyrig.preflight_cli"' in clone
    assert '"-m", "bodyrig.recover_cli"' in clone
    assert "resolve_phalp_repo" in recover
    assert '"--phalp-repo",' in recover
    assert 'parser.add_argument("--phalp-repo", required=True' in bridge
    assert "PHALP_REVISION" in bridge
    assert "_verify_phalp_install(phalp_repo)" in bridge
    assert "installed PHALP import is not sourced from the authority checkout" in bridge
