#!/usr/bin/env python
"""Source-shell repair for BodyRig's SiTH -> SMPL-X avatar bridge.

SiTH reconstructs the visible person surface, which may include clothing and
other offsets from the anatomical SMPL-X body.  Treating that entire shell as
skin can create the armpit/torso membranes seen in the first physical renderer
run.  This module keeps the source-derived head/hair shell, clamps non-head
surface offsets back toward the fitted body, and removes triangles that directly
bridge torso vertices to distal arm/hand skinning regions.
"""
from __future__ import annotations

from typing import Any

HEAD_JOINTS = frozenset({12, 15, 22, 23, 24})  # neck, head, jaw, eyes
TORSO_CORE_JOINTS = frozenset({0, 3, 6, 9, 12, 15, 22, 23, 24})
LEFT_DISTAL_JOINTS = frozenset({18, 20, *range(25, 40)})
RIGHT_DISTAL_JOINTS = frozenset({19, 21, *range(40, 55)})


class MeshFidelityError(RuntimeError):
    pass


def _finite_array(np: Any, value: Any, *, shape_tail: tuple[int, ...], label: str) -> Any:
    array = np.asarray(value)
    if array.ndim != 2 or tuple(array.shape[1:]) != shape_tail or array.shape[0] < 3:
        raise MeshFidelityError(f"{label} has invalid shape")
    if not bool(np.isfinite(array).all()):
        raise MeshFidelityError(f"{label} contains non-finite values")
    return array


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
    head_floor = neck_y - body_height * 0.04
    head_joint_mask = np.isin(dominant, np.asarray(sorted(HEAD_JOINTS), dtype=np.int64))
    preserve_head_shell = (rest[:, 1] >= head_floor) | head_joint_mask

    residual = rest - donor
    residual_norm = np.linalg.norm(residual, axis=1)
    body_mask = ~preserve_head_shell
    max_body_residual = body_height * 0.0125
    oversized = body_mask & (residual_norm > max_body_residual)
    if bool(np.any(oversized)):
        scale = max_body_residual / np.maximum(residual_norm[oversized], 1e-12)
        rest[oversized] = donor[oversized] + residual[oversized] * scale[:, None]

    repaired_faces: list[list[tuple[int, int]]] = []
    removed = 0
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
            removed += 1
            continue
        repaired_faces.append(face)

    if not repaired_faces:
        raise MeshFidelityError("source-shell repair removed all faces")
    removed_ratio = removed / max(1, len(faces))
    if removed_ratio > 0.20:
        raise MeshFidelityError(
            f"source-shell topology is too contaminated for bounded repair (removed_ratio={removed_ratio:.4f})"
        )

    metrics = {
        "body_height": body_height,
        "body_residual_cap": max_body_residual,
        "body_vertices_clamped": float(int(np.count_nonzero(oversized))),
        "head_shell_vertices_preserved": float(int(np.count_nonzero(preserve_head_shell))),
        "cross_region_faces_removed": float(removed),
        "cross_region_face_ratio": float(removed_ratio),
    }
    return rest, repaired_faces, metrics
