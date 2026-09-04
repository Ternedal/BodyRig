from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_stash_wrapper_escapes_windows_backslashes_before_wslpath():
    wrapper = (ROOT / "clone-body-from-stash.ps1").read_text(encoding="utf-8")
    setup = (ROOT / "setup-recovery-windows.ps1").read_text(encoding="utf-8")

    expected_escape = "$escapedPath = $Path.Replace('\\', '\\\\')"
    expected_call = "$raw = @(& $WslExe -d $RecoveryDistribution -- wslpath -a -u $escapedPath)"

    assert expected_escape in setup
    assert expected_escape in wrapper
    assert expected_call in wrapper
    assert "$raw = @(& $WslExe -d $RecoveryDistribution -- wslpath -a $Path)" not in wrapper
