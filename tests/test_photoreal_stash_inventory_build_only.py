from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "photoreal-stash-inventory.ps1").read_text(encoding="utf-8")


def test_inventory_ready_gate_requires_strict_build_only_boolean() -> None:
    assert "Test-StrictBoolean -Value $inventory.build_only -Expected $true" in SCRIPT
    assert "$inventory.build_only -ne $true" not in SCRIPT
    assert "Photoreal inventory crossed its build-only authority boundary." in SCRIPT
