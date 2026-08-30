from __future__ import annotations

import numpy as np
import pytest

from bodyrig.bridges.sith_mesh_fidelity import MeshFidelityError, repair_source_shell


def _joints() -> np.ndarray:
    joints = np.zeros((25, 3), dtype=np.float32)
    joints[12] = (0.0, 1.50, 0.0)  # neck
    joints[15] = (0.0, 1.78, 0.0)  # head
    return joints


def test_repair_clamps_body_shell_preserves_head_and_removes_cross_region_face() -> None:
    donor = np.asarray(
        [
            (-0.10, 0.90, 0.00),
            (-0.55, 1.10, 0.00),
            (-0.30, 1.15, 0.00),
            (0.10, 0.00, 0.00),
            (0.00, 1.90, 0.00),
            (0.20, 2.00, 0.00),
        ],
        dtype=np.float32,
    )
    source = donor.copy()
    source[0, 2] += 0.20  # clothing/body-shell offset -> must be clamped
    source[4, 2] += 0.20  # head/hair shell -> must be preserved

    joints4 = np.asarray(
        [
            (3, 0, 0, 0),      # torso
            (18, 16, 13, 0),   # left distal arm
            (16, 13, 12, 0),   # left upper arm
            (1, 0, 3, 6),
            (15, 12, 22, 23),  # head
            (15, 12, 22, 24),  # head
        ],
        dtype=np.uint16,
    )
    faces = [
        [(0, 0), (1, 1), (2, 2)],  # torso -> distal arm bridge: remove
        [(3, 3), (4, 4), (5, 5)],  # safe/head face: keep
    ]

    repaired, repaired_faces, metrics = repair_source_shell(
        np=np,
        rest_positions=source,
        donor_rest_positions=donor,
        joints4=joints4,
        faces=faces,
        rest_joints=_joints(),
    )

    body_height = float(source[:, 1].max() - source[:, 1].min())
    cap = body_height * 0.0125
    assert np.linalg.norm(repaired[0] - donor[0]) == pytest.approx(cap, abs=1e-6)
    assert repaired[4].tolist() == pytest.approx(source[4].tolist())
    assert repaired_faces == [faces[1]]
    assert metrics["body_vertices_clamped"] >= 1
    assert metrics["head_shell_vertices_preserved"] >= 2
    assert metrics["cross_region_faces_removed"] == 1


def test_repair_fails_closed_on_implausible_body_height() -> None:
    positions = np.zeros((3, 3), dtype=np.float32)
    joints4 = np.zeros((3, 4), dtype=np.uint16)
    with pytest.raises(MeshFidelityError, match="body height is implausible"):
        repair_source_shell(
            np=np,
            rest_positions=positions,
            donor_rest_positions=positions,
            joints4=joints4,
            faces=[[(0, 0), (1, 1), (2, 2)]],
            rest_joints=_joints(),
        )
