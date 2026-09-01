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
    assert "GEOMETRIC_LONG_EDGE_BODY_SCALE_RATIO = 0.08" in source
    assert "GEOMETRIC_SLIVER_MIN_EDGE_BODY_SCALE_RATIO = 0.04" in source
    assert "GEOMETRIC_SLIVER_MIN_ASPECT = 12.0" in source
    assert "MAX_GEOMETRIC_REMOVAL_RATIO = 0.01" in source
    assert "head_shell_vertices_preserved" in source
    assert "body_vertices_clamped" in source
    assert "cross_region_faces_removed" in source
    assert "cross_region_face_ratio" in source
    assert "geometric_bridge_faces_removed" in source
    assert "geometric_bridge_face_ratio" in source
    assert "if geometric_ratio > MAX_GEOMETRIC_REMOVAL_RATIO:" in source
    assert "raise MeshFidelityError" in source
    assert "torso" in source.lower()
    assert "distal" in source.lower()
    ast.parse(source)


def test_source_shell_repair_removes_long_sliver_without_joint_region_signal() -> None:
    import numpy as np

    from bodyrig.bridges.sith_mesh_fidelity import repair_source_shell

    rest = np.asarray(
        [
            [0.00, 0.00, 0.00],
            [0.01, 0.00, 0.00],
            [0.00, 0.01, 0.00],
            [0.00, 0.80, 0.00],
            [0.40, 0.80, 0.00],
            [0.20, 0.801, 0.00],
            [0.00, 1.80, 0.00],
        ],
        dtype=np.float32,
    )
    donor = rest.copy()
    joints4 = np.zeros((len(rest), 4), dtype=np.int64)
    rest_joints = np.zeros((25, 3), dtype=np.float32)
    rest_joints[12, 1] = 1.50
    safe = [(0, 0), (1, 0), (2, 0)]
    bridge = [(3, 0), (4, 0), (5, 0)]
    faces = [safe[:] for _ in range(100)] + [bridge]

    _, repaired, metrics = repair_source_shell(
        np=np,
        rest_positions=rest,
        donor_rest_positions=donor,
        joints4=joints4,
        faces=faces,
        rest_joints=rest_joints,
    )

    assert len(repaired) == 100
    assert metrics["cross_region_faces_removed"] == 0.0
    assert metrics["geometric_bridge_faces_removed"] == 1.0
    assert 0.0 < metrics["geometric_bridge_face_ratio"] < 0.01


def test_gender_wrapper_contains_fail_closed_shell_patch_contract() -> None:
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "bodyrig" / "bridges" / "sith_smplx_vrm_fitter_gender.py").read_text(encoding="utf-8")

    assert "from sith_mesh_fidelity import MeshFidelityError, repair_source_shell" in source
    assert "donor_rest_positions = v_shaped[0, selected_nearest]" in source
    assert "rest_positions, faces, shell_metrics = repair_source_shell(" in source
    assert "SiTH source-shell fidelity repair failed" in source
    assert '"source_shell_cross_region_faces_removed"' in source
    ast.parse(source)
