from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "run-photoreal-v2-exavatar-teacher.ps1").read_text(encoding="utf-8")


def test_exavatar_operator_allows_missing_preflight_output_leaf_only() -> None:
    assert "[switch]$AllowMissingLeaf" in SCRIPT
    assert "$linuxPreflight = Convert-ToWslPath -WindowsPath $strictPreflight -AllowMissingLeaf" in SCRIPT
    assert SCRIPT.count("-AllowMissingLeaf") == 2  # parameter declaration + the single prospective output call
    assert 'Translated WSL output parent does not exist' in SCRIPT
    assert '/usr/bin/test -d $candidateParent' in SCRIPT
