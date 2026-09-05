from __future__ import annotations

from pathlib import Path

import bodyrig.high_fidelity_physical_acceptance_audit as audit
import bodyrig.high_fidelity_release_readiness as readiness


def test_release_readiness_defaults_to_transitive_physical_authority_audit() -> None:
    assert readiness.physical_acceptance_status is audit.audited_physical_acceptance_status


def test_audit_contract_covers_receipt_gate_qa_runtime_and_source_lineage() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "bodyrig" / "high_fidelity_physical_acceptance_audit.py").read_text(encoding="utf-8")

    for authority in (
        '"highFidelityHumanReviewSha256"',
        '"skinQaSha256"',
        '"meshTopologyQaSha256"',
        '"runtimeManifestSha256"',
        '"sourceGateASha256"',
        '"sourcePhysicalSessionSha256"',
        '"sourceReadinessSha256"',
        '"receipt_sha256"',
        '"source_gate_a_sha256"',
    ):
        assert authority in source
    assert "_source_gate(preview_job_id)" in source
    assert "production_activation\": False" in source
