from __future__ import annotations

from pathlib import Path


def test_handoff_does_not_copy_old_gate_a_package_or_runtime() -> None:
    source = (Path(__file__).resolve().parents[1] / "bodyrig" / "high_fidelity_physical_acceptance.py").read_text(encoding="utf-8")
    assert '_copy(package, accepted, "promoted package")' in source
    assert 'materialize_runtime(accepted, runtime_dir)' in source
    assert 'source_dir / "runtime"' not in source
    assert 'source_gate.package_hash' in source
