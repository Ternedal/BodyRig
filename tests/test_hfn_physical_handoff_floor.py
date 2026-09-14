from __future__ import annotations

from pathlib import Path

import bodyrig.high_fidelity_release_readiness_cli as cli


ROOT = Path(__file__).resolve().parents[1]
HFN_SAFE_HANDOFF = "fe04ab113c3c57ed1f3d502242fc0e51b0629b04"
LEGACY_TOENAIL_HANDOFF = "1ed3661ad61d92090e3f28222282e53163c28144"
HFN_OPERATOR_SCRIPTS = (
    "prepare-hands-feet-nails-source-capture.ps1",
    "prepare-hands-feet-nails-landmark-evidence.ps1",
    "prepare-hands-feet-nails-uv-domain-evidence.ps1",
    "prepare-hands-feet-nails-detail-candidate.ps1",
    "prepare-hands-feet-nails-fingernail-geometry-candidate.ps1",
    "prepare-hands-feet-nails-toenail-geometry-candidate.ps1",
    "prepare-hands-feet-nails-render-review.ps1",
    "record-high-fidelity-hfn-review.ps1",
)
HFN_GATES = (
    "hfn_detail_candidate",
    "hfn_render_review",
    "hfn_human_review",
)


def test_fresh_physical_handoff_floor_is_drawable_short_hair_baseline_everywhere() -> None:
    prepare = (ROOT / "prepare-high-fidelity-physical-acceptance.ps1").read_text(encoding="utf-8")
    preflight = (ROOT / "high-fidelity-rig-preflight.ps1").read_text(encoding="utf-8")

    assert cli.MINIMUM_PHYSICAL_HANDOFF_REVISION == HFN_SAFE_HANDOFF
    assert HFN_SAFE_HANDOFF in prepare
    assert HFN_SAFE_HANDOFF in preflight
    assert LEGACY_TOENAIL_HANDOFF not in prepare
    assert LEGACY_TOENAIL_HANDOFF not in preflight


def test_rig_preflight_requires_complete_hfn_operator_chain() -> None:
    preflight = (ROOT / "high-fidelity-rig-preflight.ps1").read_text(encoding="utf-8")

    for script in HFN_OPERATOR_SCRIPTS:
        assert script in preflight


def test_runbook_exposes_hfn_continuation_before_package_review_and_gate_a() -> None:
    runbook = (ROOT / "HIGH-FIDELITY-PHYSICAL-RUNBOOK.md").read_text(encoding="utf-8")

    positions = [runbook.index(gate) for gate in HFN_GATES]
    package_review = runbook.index("### `high_fidelity_human_review`")
    gate_a = runbook.index("### `physical_gate_a`")

    assert positions == sorted(positions)
    assert positions[-1] < package_review < gate_a
    assert "source-grounded HFN detail-bearing candidate" in runbook
    assert "production_activation=false" in runbook
