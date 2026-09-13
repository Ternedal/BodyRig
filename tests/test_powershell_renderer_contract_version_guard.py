from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDERER_CONTRACT_READERS = (
    "check-reference-renderer-ready.ps1",
    "high-fidelity-rig-preflight.ps1",
    "run-windows-renderer-probe.ps1",
    "run-quest-renderer-probe.ps1",
    "run-reference-windows-renderer-probe.ps1",
    "run-reference-quest-renderer-probe.ps1",
    "record-reference-renderer-acceptance.ps1",
    "complete-reference-acceptance.ps1",
    "run-windows-digital-twin-probe.ps1",
    "run-quest-digital-twin-probe.ps1",
    "run-fidelity-windows-render-probe.ps1",
    "reference-renderer/build-reference-renderer.ps1",
)


def test_canonical_powershell_renderer_contract_readers_are_bool_safe_v1() -> None:
    for relative in RENDERER_CONTRACT_READERS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "$contractVersion = $contract.version" in source, relative
        assert "$null -eq $contractVersion" in source, relative
        assert "$contractVersion -is [bool]" in source, relative
        assert "$contractVersion -isnot [ValueType]" in source, relative
        assert "[decimal]$contractVersion -ne [decimal]1" in source, relative
        assert "[int]$contract.version" not in source, relative


def test_renderer_contract_guard_preserves_numeric_v1_without_string_coercion() -> None:
    for relative in RENDERER_CONTRACT_READERS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        # ValueType keeps JSON numeric 1 / 1.0 eligible while excluding JSON strings;
        # the explicit bool rejection is required because System.Boolean is a ValueType.
        assert "$contractVersion -isnot [ValueType]" in source, relative
        assert "$contractVersion -is [bool]" in source, relative
        assert "[decimal]$contractVersion -ne [decimal]1" in source, relative
