from __future__ import annotations

import hashlib

import numpy as np
import pytest

import bodyrig.photoreal_p3_quest2_eye_component as eye
from bodyrig.bridges.sith_pbr_material import _read_glb
from bodyrig.bridges.sith_smplx_vrm_fitter import (
    SMPLX_JOINT_NAMES,
    _build_vrm,
    _thumbnail_png,
)
from bodyrig.photoreal_p3_quest2_eye_component import (
    PhotorealP3Quest2EyeComponentError,
    graft_specialized_eye_component,
    select_eye_triangles,
)


def _base_avatar() -> tuple[bytes, bytes]:
    positions = np.asarray(
        [
            [-0.04, 1.60, 0.08],
            [-0.02, 1.62, 0.08],
            [-0.02, 1.58, 0.08],
            [0.04, 1.60, 0.08],
            [0.02, 1.62, 0.08],
            [0.02, 1.58, 0.08],
        ],
        dtype=np.float32,
    )
    texcoords = [
        (0.05, 0.45),
        (0.15, 0.55),
        (0.15, 0.35),
        (0.85, 0.45),
        (0.95, 0.55),
        (0.95, 0.35),
    ]
    left_face = [(0, 0), (1, 1), (2, 2)]
    right_face = [(3, 3), (4, 4), (5, 5)]
    faces = [left_face[:] for _ in range(8)] + [
        right_face[:] for _ in range(8)
    ]

    joints4 = np.zeros((6, 4), dtype=np.uint16)
    joints4[:3, 0] = eye.LEFT_EYE_JOINT
    joints4[3:, 0] = eye.RIGHT_EYE_JOINT
    weights4 = np.zeros((6, 4), dtype=np.float32)
    weights4[:, 0] = 1.0

    rest_joints = np.zeros((len(SMPLX_JOINT_NAMES), 3), dtype=np.float32)
    rest_joints[eye.LEFT_EYE_JOINT] = np.asarray(
        [-0.03, 1.60, 0.08],
        dtype=np.float32,
    )
    rest_joints[eye.RIGHT_EYE_JOINT] = np.asarray(
        [0.03, 1.60, 0.08],
        dtype=np.float32,
    )
    parents = [-1] + [0] * (len(SMPLX_JOINT_NAMES) - 1)
    texture = _thumbnail_png()
    avatar, _thumb = _build_vrm(
        np=np,
        name="P3 eye fixture",
        rest_positions=positions,
        texcoords=texcoords,
        faces=faces,
        joints4=joints4,
        weights4=weights4,
        rest_joints=rest_joints,
        parents=parents,
        texture_png=texture,
        quality={"nearest_p95": 0.0, "nearest_max": 0.0},
    )
    return avatar, texture


def test_select_eye_triangles_uses_skinning_authority() -> None:
    joints = [
        (23, 0, 0, 0),
        (23, 0, 0, 0),
        (23, 0, 0, 0),
        (24, 0, 0, 0),
        (24, 0, 0, 0),
        (24, 0, 0, 0),
    ]
    weights = [(1.0, 0.0, 0.0, 0.0)] * 6
    indices = [0, 1, 2, 3, 4, 5]

    assert select_eye_triangles(
        indices=indices,
        joints=joints,
        weights=weights,
        joint_index=23,
        minimum_faces=1,
    ) == [0]
    assert select_eye_triangles(
        indices=indices,
        joints=joints,
        weights=weights,
        joint_index=24,
        minimum_faces=1,
    ) == [1]


def test_specialized_eye_graft_adds_four_skinned_primitives() -> None:
    avatar, basecolor = _base_avatar()

    result, metadata = graft_specialized_eye_component(
        avatar,
        teacher_basecolor_png=basecolor,
        source_candidate_receipt_sha256="a" * 64,
        teacher_basecolor_sha256=hashlib.sha256(basecolor).hexdigest(),
    )

    document, _binary = _read_glb(result)
    nodes = [
        node
        for node in document["nodes"]
        if node.get("name") == eye.NODE_NAME
    ]
    assert len(nodes) == 1
    assert nodes[0]["skin"] == 0

    mesh = document["meshes"][nodes[0]["mesh"]]
    assert mesh["name"] == eye.MESH_NAME
    assert len(mesh["primitives"]) == 4
    assert [
        primitive["extras"]["bodyrigP3EyeRole"]
        for primitive in mesh["primitives"]
    ] == list(eye.PRIMITIVE_ROLES)

    embedded = document["extras"]["bodyrig"]["p3QuestEyeComponent"]
    assert embedded["specializedEyeComponentImplemented"] is True
    assert embedded["teacherDerivedAppearance"] is True
    assert embedded["leftEyeFaceCount"] == 8
    assert embedded["rightEyeFaceCount"] == 8
    assert embedded["runtimeAcceptanceAuthority"] is False
    assert embedded["productionActivation"] is False
    assert metadata["outputVrmSha256"] == hashlib.sha256(result).hexdigest()


def test_specialized_eye_graft_preserves_base_body_mesh() -> None:
    avatar, basecolor = _base_avatar()
    before, _ = _read_glb(avatar)
    before_mesh = before["meshes"][0]

    result, _metadata = graft_specialized_eye_component(
        avatar,
        teacher_basecolor_png=basecolor,
        source_candidate_receipt_sha256="b" * 64,
        teacher_basecolor_sha256=hashlib.sha256(basecolor).hexdigest(),
    )
    after, _ = _read_glb(result)

    assert after["meshes"][0] == before_mesh
    assert len(after["meshes"]) == len(before["meshes"]) + 1


def test_specialized_eye_graft_rejects_basecolor_digest_drift() -> None:
    avatar, basecolor = _base_avatar()

    with pytest.raises(
        PhotorealP3Quest2EyeComponentError,
        match="basecolor digest mismatch",
    ):
        graft_specialized_eye_component(
            avatar,
            teacher_basecolor_png=basecolor,
            source_candidate_receipt_sha256="c" * 64,
            teacher_basecolor_sha256="0" * 64,
        )


def test_eye_selection_rejects_mixed_boundary_triangles() -> None:
    joints = [
        (23, 0, 0, 0),
        (23, 0, 0, 0),
        (0, 23, 0, 0),
    ]
    weights = [
        (1.0, 0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0, 0.0),
        (0.8, 0.2, 0.0, 0.0),
    ]

    with pytest.raises(
        PhotorealP3Quest2EyeComponentError,
        match="insufficiently isolated",
    ):
        select_eye_triangles(
            indices=[0, 1, 2],
            joints=joints,
            weights=weights,
            joint_index=23,
            minimum_faces=1,
        )


def test_specialized_eye_graft_rejects_duplicate_component() -> None:
    avatar, basecolor = _base_avatar()
    first, _metadata = graft_specialized_eye_component(
        avatar,
        teacher_basecolor_png=basecolor,
        source_candidate_receipt_sha256="d" * 64,
        teacher_basecolor_sha256=hashlib.sha256(basecolor).hexdigest(),
    )

    with pytest.raises(
        PhotorealP3Quest2EyeComponentError,
        match="already present",
    ):
        graft_specialized_eye_component(
            first,
            teacher_basecolor_png=basecolor,
            source_candidate_receipt_sha256="d" * 64,
            teacher_basecolor_sha256=hashlib.sha256(basecolor).hexdigest(),
        )
