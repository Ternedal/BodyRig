from __future__ import annotations

from pathlib import Path

import bodyrig.high_fidelity_physical_acceptance as physical
import bodyrig.high_fidelity_release_readiness as release


ROOT = Path(__file__).resolve().parents[1]


def _physical_source() -> str:
    return (ROOT / "bodyrig" / "high_fidelity_physical_acceptance.py").read_text(encoding="utf-8")


def test_physical_handoff_modules_import_and_keep_release_activation_separate() -> None:
    assert physical.FORMAT == "bodyrig-high-fidelity-physical-handoff"
    assert release.PHYSICAL_GATE_A == "physical_gate_a"
    assert release.WINDOWS_GATE == "physical_windows_acceptance"
    assert release.QUEST_GATE == "physical_quest_acceptance"
    assert release.FINAL_RELEASE_GATE == "final_release"


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
    source = _physical_source()

    assert 'source_session = source_dir / "bodyrig-physical-clone-session.json"' in source
    assert 'source_readiness = source_dir / "bodyrig-rig-readiness.json"' in source
    assert "skin, topology = _fresh_qa(accepted)" in source
    assert "analyze_skin(package)" in source
    assert "analyze_topology(package)" in source
    assert "materialize_runtime(accepted, runtime_dir)" in source
    assert '"format": "bodyrig-rig-acceptance"' in source
    assert '"physical_renderer_acceptance": "pending"' in source
    assert '"automated_pass": True' in source
    assert 'status.gate != "windows-probe"' in source
    assert '"physicalAcceptanceAuthority": False' in source
    assert '"productionActivation": False' in source
    assert "reconstruction" not in source.lower()


def test_handoff_does_not_copy_old_gate_a_package_or_runtime() -> None:
    source = _physical_source()

    assert '_copy(package, accepted, "promoted package")' in source
    assert 'materialize_runtime(accepted, runtime_dir)' in source
    assert 'source_dir / "runtime"' not in source
    assert 'source_gate.package_hash' in source


def test_package_bound_human_review_is_copied_and_revalidated_for_gate_a_package() -> None:
    source = _physical_source()

    assert 'review_source = human_review_path(package, package_sha256=package_sha)' in source
    assert 'review_copy = human_review_path(accepted, package_sha256=package_sha)' in source
    assert '_copy(review_source, review_copy, "high-fidelity human review")' in source
    assert 'read_human_review(accepted)' in source


def test_source_gate_a_is_lineage_only_not_final_package_authority() -> None:
    source = _physical_source()

    assert '"sourcePackageSha256": source_gate.package_hash' in source
    assert '"promotedPackageSha256": package_sha' in source
    assert '"sourcePhysicalSessionSha256": session_sha' in source
    assert '"sourceReadinessSha256": readiness_sha' in source


def test_physical_handoff_is_create_only_and_rolls_back_only_new_output() -> None:
    source = _physical_source()

    assert "if final.exists()" in source
    assert "physical acceptance output is create-only" in source
    assert "os.replace(staging, final)" in source
    assert "if moved and not verified and final.exists()" in source
    assert "shutil.rmtree(final, ignore_errors=True)" in source
