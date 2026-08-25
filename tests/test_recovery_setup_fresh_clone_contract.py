from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _script() -> str:
    return (ROOT / "setup-recovery-windows.ps1").read_text(encoding="utf-8")


def test_fresh_no_checkout_clone_skips_only_the_preexisting_dirty_guard() -> None:
    text = _script()

    created = text.index("$created = $false")
    clone = text.index('Invoke-Checked -Executable $script:GitExe -Arguments @(\"clone\", \"--no-checkout\"')
    existing_guard = text.index("if (-not $created)", clone)
    pre_dirty = text.index('$dirty = @(& $script:GitExe -C $Path status --porcelain)', existing_guard)
    checkout = text.index('Invoke-Checked -Executable $script:GitExe -Arguments @(\"-C\", $Path, \"checkout\", \"--detach\"', pre_dirty)
    post_dirty = text.index('$dirtyAfterCheckout = @(& $script:GitExe -C $Path status --porcelain)', checkout)

    assert created < clone < existing_guard < pre_dirty < checkout < post_dirty
    assert "BodyRig will not reset or overwrite it automatically" in text
    assert "checkout is dirty after pinned checkout" in text
