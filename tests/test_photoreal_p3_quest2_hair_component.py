from __future__ import annotations

import hashlib

import numpy as np
import pytest

import bodyrig.photoreal_p3_quest2_hair_component as hair
from bodyrig.bridges.avatar_fidelity_components import (
    current_pipeline_receipt,
    with_component_status,
)
from bodyrig.bridges.sith_pbr_material import _read_glb, _write_glb
from bodyrig.bridges.sith_smplx_vrm_fitter import (
    SMPLX_JOINT_NAMES,
    _build_vrm,
    _thumbnail_png,
)
from bodyrig.photoreal_p3_quest2_hair_component import (
    PhotorealP3Quest2HairComponentError,
    graft_teacher_hair_component,
    select_teacher_hair_faces,
)


def _donor() -> tuple[list[list[float]], list[list[float]], list[list[int]], list[float]]:
    positions = [
        [-0.20, 0.00, -0.10],
        [0.20, 0.00, -0.10],
        [-0.20, 0.40, 0.10],
        [0.20, 0.40, 0.10],
        [-0.15, 0.80, -0.08],
        [0.15, 0.80, -0.08],
        [-0.15, 1.20, 0.08],
        [0.15, 1.20, 0.08],
        [-0.12, 1.60, -0.08],
        [0.12, 1.60, -0.08],
        [-0.12, 1.72, 0.08],
        [0.12, 1.72, 0.08],
        [-0.10, 1.84, -0.06],
        [0.10, 1.84, -0.06],
        [-0.08, 1.96, 0.05],
        [0.08, 2.00, 0.05],
    ]
    head_faces = [
        [8, 9, 10],
        [9, 11, 10],
        [10, 11, 12],
        [11, 13, 12],
        [12, 13, 14],
        [13, 15, 14],
    ]
    faces = [head_faces[index % len(head_faces)] for index in range(40)]
    normals = [[0.0, 1.0, 0.0] for _ in positions]
    offsets = [0.0] * 8 + [0.024] * 8
    return positions, normals, faces, offsets


def _base_avatar() -> tuple[bytes, bytes, int]:
    positions = np.asarray(
        [
            [-0.12, 1.60, 0.02],
            [0.12, 1.60, 0.02],
            [-0.10, 1.76, 0.03],
            [0.10, 1.76, 0.03],
            [-0.08, 1.92, 0.02],
            [0.08, 1.92, 0.02],
        ],
        dtype=np.float32,
    )
    texcoords = [
        (0.05, 0.10),
        (0.95, 0.10),
        (0.10, 0.50),
        (0.90, 0.50),
        (0.20, 0.90),
        (0.80, 0.90),
    ]
    face_patterns = [
        [(0, 0), (1, 1), (2, 2)],
        [(1, 1), (3, 3), (2, 2)],
        [(2, 2), (3, 3), (4, 4)],
        [(3, 3), (5, 5), (4, 4)],
    ]
    faces = [face_patterns[index % len(face_patterns)] for index in range(36)]
    joints4 = np.zeros((6, 4), dtype=np.uint16)
    joints4[:, 0] = 15
    weights4 = np.zeros((6, 4), dtype=np.float32)
    weights4[:, 0] = 1.0
    rest_joints = np.zeros((len(SMPLX_JOINT_NAMES), 3), dtype=np.float32)
    parents = [-1] + [0] * (len(SMPLX_JOINT_NAMES) - 1)
    texture = _thumbnail_png()
    avatar, _thumb = _build_vrm(
        np=np,
        name="P3 hair fixture",
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
    return avatar, texture, len(faces)


def _envelope(face_count: int) -> dict[str, object]:
    value: dict[str, object] = {
        "body_face_count": face_count,
        "selection_mode": "strict-teacher-shell",
        "selected_faces": [
            {"face_index": index, "corner_offsets": [0.01, 0.012, 0.011]}
            for index in range(32)
        ],
        "hair_envelope_sha256": "e" * 64,
    }
    return value


def test_teacher_hair_selector_keeps_one_connected_head_shell() -> None:
    positions, normals, faces, offsets = _donor()

    result = select_teacher_hair_faces(
        donor_positions=positions,
        donor_normals=normals,
        donor_faces=faces,
        outward_offsets=offsets,
    )

    assert result["selection_mode"] == "strict-teacher-shell"
    assert result["selected_face_count"] >= hair.MIN_FACE_COUNT
    assert result["selected_vertex_count"] >= 6
    assert result["outward_offset_p95"] > 0.0
    assert result["head_footprint_span_body_ratio"] >= hair.MIN_HEAD_FOOTPRINT_BODY_RATIO


def test_teacher_hair_selector_fails_closed_without_teacher_shell() -> None:
    positions, normals, faces, _offsets = _donor()

    with pytest.raises(
        PhotorealP3Quest2HairComponentError,
        match="no connected geometric hair seed",
    ):
        select_teacher_hair_faces(
            donor_positions=positions,
            donor_normals=normals,
            donor_faces=faces,
            outward_offsets=[0.0] * len(positions),
        )


def test_teacher_hair_graft_adds_separate_skinned_primitive() -> None:
    avatar, basecolor, face_count = _base_avatar()
    envelope = _envelope(face_count)

    result, metadata = graft_teacher_hair_component(
        avatar,
        teacher_basecolor_png=basecolor,
        teacher_basecolor_sha256=hashlib.sha256(basecolor).hexdigest(),
        hair_envelope=envelope,
        source_eye_receipt_sha256="a" * 64,
    )

    document, _binary = _read_glb(result)
    nodes = [
        node for node in document["nodes"]
        if node.get("name") == hair.NODE_NAME
    ]
    assert len(nodes) == 1
    assert nodes[0]["skin"] == 0
    mesh = document["meshes"][nodes[0]["mesh"]]
    assert mesh["name"] == hair.MESH_NAME
    assert len(mesh["primitives"]) == 1
    assert mesh["primitives"][0]["extras"]["bodyrigP3HairRole"] == (
        "teacher-derived-head-hair-shell"
    )
    bodyrig = document["extras"]["bodyrig"]
    assert bodyrig["fidelityComponents"] == current_pipeline_receipt()
    embedded = bodyrig["p3QuestTeacherHairComponent"]
    assert embedded["sourceDerived"] is True
    assert embedded["generativeGeometry"] is False
    assert embedded["physicalSilhouetteReviewRequired"] is True
    assert embedded["teacherDerivedHairComponentImplemented"] is True
    assert embedded["runtimeAcceptanceAuthority"] is False
    assert metadata["outputVrmSha256"] == hashlib.sha256(result).hexdigest()


def test_teacher_hair_graft_rejects_preexisting_component_authority() -> None:
    avatar, basecolor, face_count = _base_avatar()
    document, binary = _read_glb(avatar)
    extras = document.setdefault("extras", {})
    bodyrig = extras.setdefault("bodyrig", {})
    bodyrig["fidelityComponents"] = with_component_status(
        current_pipeline_receipt(),
        component="body_anatomy",
        status="complete",
    )
    stale = _write_glb(document, binary)

    with pytest.raises(
        PhotorealP3Quest2HairComponentError,
        match="pre-existing fidelity component authority",
    ):
        graft_teacher_hair_component(
            stale,
            teacher_basecolor_png=basecolor,
            teacher_basecolor_sha256=hashlib.sha256(basecolor).hexdigest(),
            hair_envelope=_envelope(face_count),
            source_eye_receipt_sha256="f" * 64,
        )


def test_teacher_hair_graft_preserves_existing_body_mesh() -> None:
    avatar, basecolor, face_count = _base_avatar()
    before, _ = _read_glb(avatar)
    before_mesh = before["meshes"][0]

    result, _metadata = graft_teacher_hair_component(
        avatar,
        teacher_basecolor_png=basecolor,
        teacher_basecolor_sha256=hashlib.sha256(basecolor).hexdigest(),
        hair_envelope=_envelope(face_count),
        source_eye_receipt_sha256="b" * 64,
    )
    after, _ = _read_glb(result)

    assert after["meshes"][0] == before_mesh
    assert len(after["meshes"]) == len(before["meshes"]) + 1


def test_teacher_hair_graft_rejects_basecolor_drift() -> None:
    avatar, basecolor, face_count = _base_avatar()

    with pytest.raises(
        PhotorealP3Quest2HairComponentError,
        match="basecolor digest mismatch",
    ):
        graft_teacher_hair_component(
            avatar,
            teacher_basecolor_png=basecolor,
            teacher_basecolor_sha256="0" * 64,
            hair_envelope=_envelope(face_count),
            source_eye_receipt_sha256="c" * 64,
        )
