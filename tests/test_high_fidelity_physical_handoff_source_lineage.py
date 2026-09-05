from __future__ import annotations

from pathlib import Path


def test_source_gate_a_is_lineage_only_not_final_package_authority() -> None:
    source = (Path(__file__).resolve().parents[1] / "bodyrig" / "high_fidelity_physical_acceptance.py").read_text(encoding="utf-8")
    assert '"sourcePackageSha256": source_gate.package_hash' in source
    assert '"promotedPackageSha256": package_sha' in source
    assert '"sourcePhysicalSessionSha256": session_sha' in source
    assert '"sourceReadinessSha256": readiness_sha' in source
