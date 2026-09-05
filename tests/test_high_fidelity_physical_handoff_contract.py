from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_readiness_delegates_physical_progress_to_canonical_acceptance_state_machine() -> None:
    source = (ROOT / "bodyrig" / "high_fidelity_release_readiness.py").read_text(encoding="utf-8")

    assert "physical_acceptance_status" in source
    assert 'PHYSICAL_GATE_A = "physical_gate_a"' in source
    assert 'WINDOWS_GATE = "physical_windows_acceptance"' in source
    assert 'QUEST_GATE = "physical_quest_acceptance"' in source
    assert 'FINAL_RELEASE_GATE = "final_release"' in source
    assert 'physical.get("production_activation") is True' in source
    assert 'result["production_ready"] = True' in source
    assert 'result["production_activation"] = True' in source


def test_fresh_gate_a_reuses_only_physical_origin_and_regenerates_package_authority() -> None:
    source = (ROOT / "bodyrig" / "high_fidelity_physical_acceptance.py").read_text(encoding="utf-8")

    assert 'source_session = source_dir / "bodyrig-physical-clone-session.json"' in source
    assert 'source_readiness = source_dir / "bodyrig-rig-readiness.json"' in source
    assert "analyze_skin(accepted)" in source
    assert "analyze_topology(accepted)" in source
    assert "materialize_runtime(accepted, runtime_dir)" in source
    assert 'status.gate != "windows-probe"' in source
    assert '"physicalAcceptanceAuthority": False' in source
    assert '"productionActivation": False' in source
    assert "reconstruction" not in source.lower()
