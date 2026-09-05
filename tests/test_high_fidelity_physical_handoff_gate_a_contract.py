from __future__ import annotations

from pathlib import Path


def test_promoted_gate_a_uses_canonical_gate_format_and_stops_before_physical_pass() -> None:
    source = (Path(__file__).resolve().parents[1] / "bodyrig" / "high_fidelity_physical_acceptance.py").read_text(encoding="utf-8")
    assert '"format": "bodyrig-rig-acceptance"' in source
    assert '"physical_renderer_acceptance": "pending"' in source
    assert '"automated_pass": True' in source
    assert '"production_activation": False' in source
    assert 'status.gate != "windows-probe"' in source
