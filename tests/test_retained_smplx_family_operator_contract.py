from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit-retained-smplx-family.ps1"


def test_retained_smplx_family_audit_does_not_assign_powershell_home() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    lowered = source.lower()

    assert "$home =" not in lowered
    assert "$wslhomeresult = invoke-wslraw" in lowered
    assert "$wslhomeresult.exitcode" in lowered
    assert "$wslhomeresult.text.trim()" in lowered


def test_retained_smplx_family_audit_keeps_default_install_root_under_wsl_home() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'print(pathlib.Path.home().as_posix())' in source
    assert '.local/share/bodyrig/sith' in source
    assert 'BodyRig retained SMPL-X family audit: PASS' in source
