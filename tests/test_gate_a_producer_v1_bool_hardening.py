from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "accept-physical-clone-core.ps1").read_text(encoding="utf-8")
AUTHORITIES = (
    "readiness.version",
    "skinQa.version",
    "topologyQa.version",
    "runtimeManifest.version",
)


def test_gate_a_producer_uses_bool_safe_numeric_v1_guard() -> None:
    assert "function Test-V1Version($Value)" in SOURCE
    assert "$null -eq $Value" in SOURCE
    assert "$Value -is [bool]" in SOURCE
    assert "$Value -isnot [ValueType]" in SOURCE
    assert "[decimal]$Value -eq [decimal]1" in SOURCE


def test_gate_a_producer_persisted_v1_call_sites_use_guard() -> None:
    for authority in AUTHORITIES:
        assert f"Test-V1Version ${authority}" in SOURCE, authority
        assert f"[int]${authority}" not in SOURCE, authority


def test_gate_a_producer_remains_non_activating() -> None:
    assert 'format = "bodyrig-rig-acceptance"' in SOURCE
    assert 'physical_renderer_acceptance = "pending"' in SOURCE
    assert "production_activation = $false" in SOURCE
