#!/usr/bin/env python
"""Source-shell repair for BodyRig's SiTH -> SMPL-X avatar bridge.

SiTH reconstructs the visible person surface, which may include clothing and
other offsets from the anatomical SMPL-X body. Treating that entire shell as
skin can create the armpit/torso membranes seen in physical renderer runs.

The repair is intentionally bounded and source preserving:
* keep the source-derived head/hair shell untouched,
* clamp non-head offsets back toward the fitted SMPL-X donor surface,
* remove explicit torso->distal-arm skinning bridges,
* remove geometrically implausible long/sliver bridge triangles even when their
  skin-joint labels do not expose the bridge.

The geometric thresholds are expressed relative to the final repaired body
scale so they are independent of absolute avatar units.
"""
from __future__ import annotations

from typing import Any

HEAD_JOINTS = frozenset({12, 15, 22, 23, 24})  # neck, head, jaw, eyes
TORSO_CORE_JOINTS = frozenset({0, 3, 6, 9, 12, 15, 22, 23, 24})
LEFT_DISTAL_JOINTS = frozenset({18, 20, *range(25, 40)})
RIGHT_DISTAL_JOINTS = frozenset({19, 21, *range(40, 55)})
BODY_RESIDUAL_SCALE = 0.0125
HEAD_MARGIN_SCALE = 0.04
MAX_CROSS_REGION_REMOVAL_RATIO = 0.03
GEOMETRIC_LONG_EDGE_BODY_SCALE_RATIO = 0.08
GEOMETRIC_SLIVER_MIN_EDGE_BODY_SCALE_RATIO = 0.04
GEOMETRIC_SLIVER_MIN_ASPECT = 12.0
MAX_GEOMETRIC_REMOVAL_RATIO = 0.01


class MeshFidelityError(RuntimeError):
    pass


def _finite_array(np: Any, value: Any, *, shape_tail: tuple[int, ...], label: str) -> Any:
    array = np.asarray(value)
    if array.ndim != 2 or tuple(array.shape[1:]) != shape_tail or array.shape[0] < 3:
        raise MeshFidelityError(f"{label} has invalid shape")
    if not bool(np.isfinite(array).all()):
        raise MeshFidelityError(f"{label} contains non-finite values")
    return array


def _triangle_metrics(np: Any, positions: Any, indices: list[int]) -> tuple[float, float]:
    a, b, c = (positions[index] for index in indices)
    ab = float(np.linalg.norm(a - b))
    bc = float(np.linalg.norm(b - c))
    ca = float(np.linalg.norm(c - a))
    max_edge = max(ab, bc, ca)
    double_area = float(np.linalg.norm(np.cross(b - a, c - a)))
    altitude = double_area / max(max_edge, 1e-12)
    aspect = max_edge / max(altitude, 1e-12)
    return max_edge, aspect


def repair_source_shell(
    *,
    np: Any,
    rest_positions: Any,
    donor_rest_positions: Any,
    joints4: Any,
    faces: list[list[tuple[int, int]]],
    rest_joints: Any,
) -> tuple[Any, list[list[tuple[int, int]]], dict[str, float]]:
    rest = _finite_array(np, rest_positions, shape_tail=(3,), label="source rest positions").astype(np.float32, copy=True)
    donor = _finite_array(np, donor_rest_positions, shape_tail=(3,), label="SMPL-X donor rest positions").astype(np.float32, copy=False)
    influences = np.asarray(joints4)
    joints = _finite_array(np, rest_joints, shape_tail=(3,), label="SMPL-X rest joints").astype(np.float32, copy=False)
    if donor.shape != rest.shape or influences.shape != (len(rest), 4):
        raise MeshFidelityError("source shell/donor/influence shapes do not match")
    if joints.shape[0] < 25:
        raise MeshFidelityError("SMPL-X rest joint set is incomplete")

    body_height = float(rest[:, 1].max() - rest[:, 1].min())
    if not 0.2 <= body_height <= 4.0:
        raise MeshFidelityError(f"body height is implausible: {body_height:.6f}")

    dominant = influences[:, 0].astype(np.int64, copy=False)
    neck_y = float(joints[12, 1])
    head_floor = neck_y - body_height * HEAD_MARGIN_SCALE
    head_joint_mask = np.isin(dominant, np.asarray(sorted(HEAD_JOINTS), dtype=np.int64))
    preserve_head_shell = (rest[:, 1] >= head_floor) | head_joint_mask

    residual = rest - donor
    residual_norm = np.linalg.norm(residual, axis=1)
    body_mask = ~preserve_head_shell
    max_body_residual = body_height * BODY_RESIDUAL_SCALE
    oversized = body_mask & (residual_norm > max_body_residual)
    if bool(np.any(oversized)):
        scale = max_body_residual / np.maximum(residual_norm[oversized], 1e-12)
        rest[oversized] = donor[oversized] + residual[oversized] * scale[:, None]

    extents = rest.max(axis=0) - rest.min(axis=0)
    body_scale = float(np.linalg.norm(extents))
    if not np.isfinite(body_scale) or body_scale <= 1e-6:
        raise MeshFidelityError("source-shell repaired body scale is invalid")

    repaired_faces: list[list[tuple[int, int]]] = []
    cross_region_removed = 0
    geometric_removed = 0
    for face in faces:
        if len(face) != 3:
            raise MeshFidelityError("source mesh contains a non-triangular face")
        vertex_indices = [int(vertex) for vertex, _ in face]
        if any(index < 0 or index >= len(rest) for index in vertex_indices):
            raise MeshFidelityError("source mesh face index is outside vertex range")
        face_joints = {int(dominant[index]) for index in vertex_indices}
        face_is_head = all(bool(preserve_head_shell[index]) for index in vertex_indices)
        torso_to_left_distal = bool(face_joints & TORSO_CORE_JOINTS and face_joints & LEFT_DISTAL_JOINTS)
        torso_to_right_distal = bool(face_joints & TORSO_CORE_JOINTS and face_joints & RIGHT_DISTAL_JOINTS)
        if not face_is_head and (torso_to_left_distal or torso_to_right_distal):
            cross_region_removed += 1
            continue

        if not face_is_head:
            max_edge, aspect = _triangle_metrics(np, rest, vertex_indices)
            edge_ratio = max_edge / body_scale
            geometric_bridge = (
                edge_ratio >= GEOMETRIC_LONG_EDGE_BODY_SCALE_RATIO
                or (
                    edge_ratio >= GEOMETRIC_SLIVER_MIN_EDGE_BODY_SCALE_RATIO
                    and aspect >= GEOMETRIC_SLIVER_MIN_ASPECT
                )
            )
            if geometric_bridge:
                geometric_removed += 1
                continue
        repaired_faces.append(face)

    if not repaired_faces:
        raise MeshFidelityError("source-shell repair removed all faces")
    face_count = max(1, len(faces))
    cross_region_ratio = cross_region_removed / face_count
    geometric_ratio = geometric_removed / face_count
    total_removed = cross_region_removed + geometric_removed
    total_removed_ratio = total_removed / face_count
    if cross_region_ratio > MAX_CROSS_REGION_REMOVAL_RATIO:
        raise MeshFidelityError(
            "source-shell skin-region topology is too contaminated for bounded repair "
            f"(removed_ratio={cross_region_ratio:.4f})"
        )
    if geometric_ratio > MAX_GEOMETRIC_REMOVAL_RATIO:
        raise MeshFidelityError(
            "source-shell geometric topology is too contaminated for bounded repair "
            f"(removed_ratio={geometric_ratio:.4f})"
        )

    metrics = {
        "body_height": body_height,
        "body_scale": body_scale,
        "body_residual_cap": max_body_residual,
        "body_vertices_clamped": float(int(np.count_nonzero(oversized))),
        "head_shell_vertices_preserved": float(int(np.count_nonzero(preserve_head_shell))),
        "cross_region_faces_removed": float(cross_region_removed),
        "cross_region_face_ratio": float(cross_region_ratio),
        "geometric_bridge_faces_removed": float(geometric_removed),
        "geometric_bridge_face_ratio": float(geometric_ratio),
        "total_faces_removed": float(total_removed),
        "total_face_ratio": float(total_removed_ratio),
    }
    return rest, repaired_faces, metrics
