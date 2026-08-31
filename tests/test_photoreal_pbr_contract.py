from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_gender_aware_production_wrapper_installs_pbr_after_mesh_build() -> None:
    source = text("bodyrig/bridges/sith_smplx_vrm_fitter_gender.py")
    assert "_install_pbr_refinement" in source
    assert "derive_pbr_maps" in source
    assert "refine_glb_pbr" in source
    assert "original(*args, **kwargs)" in source
    assert "source-derived PBR material refinement failed" in source


def test_pbr_refinement_uses_core_gltf_material_features_only() -> None:
    source = text("bodyrig/bridges/sith_pbr_material.py")
    assert 'material["normalTexture"]' in source
    assert 'pbr["metallicRoughnessTexture"]' in source
    assert 'pbr["metallicFactor"] = 0.0' in source
    assert 'pbr["roughnessFactor"] = 1.0' in source
    assert "extensionsUsed" not in source.split("def refine_glb_pbr", 1)[1]
    assert '"physicalMeasurement": False' in source
    assert '"sourceDerivedHeuristic": True' in source


def test_material_refinement_does_not_modify_base_fitter_source_contract() -> None:
    base = text("bodyrig/bridges/sith_smplx_vrm_fitter.py")
    assert '"baseColorTexture": {"index": 0}' in base
    assert '"roughnessFactor": 0.9' in base
    assert "sith_pbr_material" not in base
