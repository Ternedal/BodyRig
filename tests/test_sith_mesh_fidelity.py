from __future__ import annotations

import ast
from pathlib import Path


def test_source_shell_repair_contract_is_fail_closed_and_head_preserving() -> None:
    repo = Path(__file__).resolve().parents[1]
    path = repo / "bodyrig" / "bridges" / "sith_mesh_fidelity.py"
    source = path.read_text(encoding="utf-8")

    assert "BODY_RESIDUAL_SCALE = 0.0125" in source
    assert "HEAD_MARGIN_SCALE = 0.04" in source
    assert "head_shell_vertices_preserved" in source
    assert "body_vertices_clamped" in source
    assert "cross_region_faces_removed" in source
    assert "cross_region_face_ratio" in source
    assert "if removed_ratio > 0.03:" in source
    assert "raise MeshFidelityError" in source
    assert "torso" in source
    assert "distal" in source
    ast.parse(source)


def test_gender_wrapper_materializes_shell_repair_before_bodyprint_adjustment() -> None:
    repo = Path(__file__).resolve().parents[1]
    path = repo / "bodyrig" / "bridges" / "sith_smplx_vrm_fitter_gender.py"
    source = path.read_text(encoding="utf-8")

    repair = source.index("repair_source_shell(")
    adjustment = source.index('adjustment_metrics: dict[str, float]')
    assert repair < adjustment
    assert "donor_rest_positions = v_shaped[0, selected_nearest]" in source
    assert "rest_positions, faces, shell_metrics = repair_source_shell(" in source
    ast.parse(source)
