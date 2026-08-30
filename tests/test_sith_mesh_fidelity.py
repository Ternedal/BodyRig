from __future__ import annotations

import ast
from pathlib import Path


def test_source_shell_repair_contract_is_fail_closed_and_head_preserving() -> None:
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
    assert "torso" in source.lower()
    assert "distal" in source.lower()
    ast.parse(source)


def test_gender_wrapper_contains_fail_closed_shell_patch_contract() -> None:
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "bodyrig" / "bridges" / "sith_smplx_vrm_fitter_gender.py").read_text(encoding="utf-8")

    assert "from sith_mesh_fidelity import MeshFidelityError, repair_source_shell" in source
    assert "donor_rest_positions = v_shaped[0, selected_nearest]" in source
    assert "rest_positions, faces, shell_metrics = repair_source_shell(" in source
    assert "SiTH source-shell fidelity repair failed" in source
    assert '"source_shell_cross_region_faces_removed"' in source
    ast.parse(source)
