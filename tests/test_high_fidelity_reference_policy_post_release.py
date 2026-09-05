from __future__ import annotations

from pathlib import Path

from bodyrig.acceptance_status import AcceptanceStatus
from bodyrig.reference_acceptance_policy import apply_reference_policy, reference_policy_violation


def test_historical_complete_status_keeps_v1_compatibility_but_strict_helper_detects_legacy_layout(tmp_path: Path) -> None:
    (tmp_path / "windows-probe.json").write_text("{}\n", encoding="utf-8")
    status = AcceptanceStatus(
        state="complete",
        gate="release",
        acceptance_dir=str(tmp_path),
        body_id="body-1",
        bodyrig_revision="a" * 40,
        message="historical release remains readable",
        next_command=None,
    )

    assert apply_reference_policy(status) == status
    violation = reference_policy_violation(tmp_path)
    assert violation is not None
    gate, message = violation
    assert gate == "reference-layout"
    assert "Legacy root renderer evidence" in message


def test_high_fidelity_audit_calls_strict_reference_policy_after_generic_policy() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "bodyrig" / "high_fidelity_physical_acceptance_audit.py").read_text(encoding="utf-8")

    generic = source.index("policy_status = apply_reference_policy(generic_status)")
    strict = source.index("violation = reference_policy_violation(acceptance)")
    transitive = source.index('expected_package = _sha(package_sha256, "continuation package SHA")')
    assert generic < strict < transitive
    assert "including after release" in source
