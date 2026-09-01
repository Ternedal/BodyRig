from __future__ import annotations

import ast
from pathlib import Path


def test_source_shell_repair_contract_remains_available_as_legacy_reference() -> None:
    repo = Path(__file__).resolve().parents[1]
    path = repo / "bodyrig" / "bridges" / "sith_mesh_fidelity.py"
    source = path.read_text(encoding="utf-8")

    assert "BODY_RESIDUAL_SCALE = 0.0125" in source
    assert "HEAD_MARGIN_SCALE = 0.04" in source
    assert "MAX_CROSS_REGION_REMOVAL_RATIO = 0.03" in source
    assert "head_shell_vertices_preserved" in source
    assert "body_vertices_clamped" in source
    assert "cross_region_faces_removed" in source
    assert "cross_region_face_ratio" in source
    assert "if removed_ratio > MAX_CROSS_REGION_REMOVAL_RATIO:" in source
    assert "raise MeshFidelityError" in source
    ast.parse(source)


def test_gender_wrapper_routes_through_stable_donor_topology() -> None:
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "bodyrig" / "bridges" / "sith_smplx_vrm_fitter_gender.py").read_text(encoding="utf-8")

    assert 'with_name("sith_smplx_vrm_fitter_donor.py")' in source
    assert "source-shell repair" not in source.lower()
    assert "repair_source_shell" not in source
    assert "_install_pbr_refinement" in source
    assert "GENDER_MARKER" in source
    ast.parse(source)


def test_donor_fitter_does_not_serialize_source_vertices_as_body_geometry() -> None:
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "bodyrig" / "bridges" / "sith_smplx_vrm_fitter_donor.py").read_text(encoding="utf-8")

    assert "rest_positions = v_shaped[0]" in source
    assert "full_weights = model.lbs_weights" in source
    assert "donor_faces_raw = _donor_faces(model)" in source
    assert "build_donor_faces(" in source
    assert "sourceMeshGeometryUsed" not in source  # metadata helper owns this contract
    assert "unskin(" not in source
    ast.parse(source)
