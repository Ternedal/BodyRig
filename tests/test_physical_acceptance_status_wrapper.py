from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _wrapper() -> str:
    return (ROOT / "physical-acceptance-status.ps1").read_text(encoding="utf-8")


def test_status_wrapper_binds_python_import_and_operator_root_to_checkout() -> None:
    text = _wrapper()
    authority = text.index('$bodyRigAuthorityRaw = @(& $BodyRigPython -c')
    args = text.index('$argsList = @("-m", "bodyrig.acceptance_status_cli"')

    assert 'bodyrig\\__init__.py' in text
    assert 'pathlib.Path(bodyrig.__file__).resolve()' in text
    assert "could not prove a single checkout-bound bodyrig import for acceptance status" in text.lower()
    assert "imports bodyrig from unexpected location" in text
    assert '[System.StringComparison]::OrdinalIgnoreCase' in text
    assert '"--operator-root", $repoRoot' in text
    assert authority < args
