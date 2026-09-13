from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rig_window_planner_routes_through_hfn_migration_authority() -> None:
    script = (ROOT / "plan-rig-window.ps1").read_text(encoding="utf-8")
    assert "bodyrig.rig_window_hfn_migration_authority" in script
    assert "bodyrig.rig_window_component_authority" not in script


def test_migration_operator_surface_is_present() -> None:
    required = (
        "prepare-high-fidelity-hfn-migration.ps1",
        "high-fidelity-hfn-migrated-status.ps1",
        "prepare-high-fidelity-migrated-physical-acceptance.ps1",
    )
    for name in required:
        assert (ROOT / name).is_file(), name
