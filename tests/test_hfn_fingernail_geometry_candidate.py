from __future__ import annotations

from PIL import Image

import bodyrig.hands_feet_nails_fingernail_geometry_candidate as subject
from bodyrig.bridges.sith_pbr_material import _read_glb


def _all_nails() -> list[tuple[str, str, str]]:
    return [
        (region, label, joint)
        for region in ("left_hand", "right_hand")
        for label, joint in subject.HAND_NAIL_JOINTS[region].items()
    ]


def test_fingernail_triangle_groups_bind_each_plate_to_its_distal_joint(monkeypatch) -> None:
    nails = _all_nails()
    width = height = 100
    joint_names = [joint for _region, _label, joint in nails]
    uvs: list[tuple[float, float]] = []
    joints: list[tuple[int, int, int, int]] = []
    weights: list[tuple[float, float, float, float]] = []
    indices: list[int] = []
    target_pixels: dict[tuple[str, str], tuple[int, int]] = {}

    for nail_index, (region, label, _joint) in enumerate(nails):
        x = 8 + (nail_index % 5) * 18
        y = 20 if region == "left_hand" else 70
        u = x / float(width - 1)
        v = y / float(height - 1)
        first = len(uvs)
        uvs.extend([(u - 0.002, v), (u + 0.002, v), (u, v + 0.002)])
        joints.extend([(nail_index, 0, 0, 0)] * 3)
        weights.extend([(1.0, 0.0, 0.0, 0.0)] * 3)
        indices.extend([first, first + 1, first + 2])
        target_pixels[(region, label)] = (x, y)

    monkeypatch.setattr(
        subject,
        "_body_uv_inputs",
        lambda *_args, **_kwargs: (uvs, joints, weights, indices, joint_names),
    )
    monkeypatch.setattr(
        subject,
        "_region_masks",
        lambda *_args, **_kwargs: {
            "left_hand": Image.new("L", (width, height), 255),
            "right_hand": Image.new("L", (width, height), 255),
        },
    )

    def nail_masks(*_args, **_kwargs):
        result: dict[str, dict[str, Image.Image]] = {"left_hand": {}, "right_hand": {}}
        for region, label, _joint in nails:
            mask = Image.new("L", (width, height), 0)
            mask.putpixel(target_pixels[(region, label)], 255)
            result[region][label] = mask
        return result

    monkeypatch.setattr(subject, "_fingernail_masks", nail_masks)

    groups = subject._fingernail_triangle_groups(
        {},
        b"",
        {},
        width=width,
        height=height,
    )

    assert len(groups) == 10
    assert all(len(triangles) == 1 for triangles in groups.values())
    assert {tuple(triangles[0]) for triangles in groups.values()} == {
        (offset, offset + 1, offset + 2) for offset in range(0, 30, 3)
    }


def test_append_geometry_adds_ten_skinned_nail_plates_without_mutating_body_material(monkeypatch) -> None:
    document = {
        "asset": {"version": "2.0"},
        "bufferViews": [],
        "accessors": [],
        "images": [{"name": "BodyRigHandsFeetNailsDetailBaseColor", "bufferView": 0, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "materials": [
            {
                "name": "BodySkin",
                "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
            }
        ],
        "meshes": [],
        "nodes": [],
        "skins": [{"name": "SMPLX", "joints": [0]}],
        "scenes": [{"nodes": []}],
        "scene": 0,
        "buffers": [{"byteLength": 0}],
        "extras": {"bodyrig": {}},
    }
    original_material = dict(document["materials"][0])
    positions = [(0.0, 0.0, 0.0), (0.01, 0.0, 0.0), (0.0, 0.01, 0.0)]
    normals = [(0.0, 0.0, 1.0)] * 3
    uvs = [(0.1, 0.1), (0.2, 0.1), (0.1, 0.2)]
    joints = [(0, 0, 0, 0)] * 3
    weights = [(1.0, 0.0, 0.0, 0.0)] * 3
    monkeypatch.setattr(
        subject,
        "_body_geometry_inputs",
        lambda *_args, **_kwargs: ({}, positions, normals, uvs, joints, weights, [0, 1, 2], ["smplx_left_index3"]),
    )
    groups = {
        f"plate_{index:02d}": [[0, 1, 2]]
        for index in range(10)
    }
    monkeypatch.setattr(
        subject,
        "_fingernail_triangle_groups",
        lambda *_args, **_kwargs: groups,
    )

    glb, embedded = subject._append_geometry(
        document,
        b"",
        uv_evidence={},
        width=1024,
        height=1024,
        source_detail_package_sha256="a" * 64,
        uv_evidence_sha256="b" * 64,
    )
    parsed, binary = _read_glb(glb)

    assert parsed["materials"][0] == original_material
    assert parsed["materials"][-1]["name"] == subject.MATERIAL_NAME
    assert parsed["materials"][-1]["pbrMetallicRoughness"]["baseColorTexture"] == {"index": 0}
    assert parsed["meshes"][-1]["name"] == subject.MESH_NAME
    assert parsed["nodes"][-1] == {
        "name": subject.NODE_NAME,
        "mesh": len(parsed["meshes"]) - 1,
        "skin": 0,
    }
    assert len(parsed["scenes"][0]["nodes"]) == 1
    assert parsed["scenes"][0]["nodes"][0] == len(parsed["nodes"]) - 1
    assert embedded["plateCount"] == 10
    assert embedded["triangleCount"] == 10
    assert embedded["vertexCount"] == 30
    assert embedded["geometryModified"] is True
    assert embedded["textureModified"] is False
    assert embedded["additiveGeometryOnly"] is True
    assert len(binary) > 0


def test_plate_positions_are_offset_outward_from_source_surface(monkeypatch) -> None:
    document = {
        "asset": {"version": "2.0"},
        "bufferViews": [],
        "accessors": [],
        "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
        "meshes": [],
        "nodes": [],
        "scenes": [{"nodes": []}],
        "buffers": [{"byteLength": 0}],
        "extras": {"bodyrig": {}},
    }
    positions = [(0.0, 0.0, 0.0), (0.01, 0.0, 0.0), (0.0, 0.01, 0.0)]
    normals = [(0.0, 0.0, 2.0)] * 3
    uvs = [(0.1, 0.1), (0.2, 0.1), (0.1, 0.2)]
    joints = [(0, 0, 0, 0)] * 3
    weights = [(1.0, 0.0, 0.0, 0.0)] * 3
    monkeypatch.setattr(
        subject,
        "_body_geometry_inputs",
        lambda *_args, **_kwargs: ({}, positions, normals, uvs, joints, weights, [0, 1, 2], ["joint"]),
    )
    monkeypatch.setattr(
        subject,
        "_fingernail_triangle_groups",
        lambda *_args, **_kwargs: {f"plate_{index}": [[0, 1, 2]] for index in range(10)},
    )

    glb, _embedded = subject._append_geometry(
        document,
        b"",
        uv_evidence={},
        width=64,
        height=64,
        source_detail_package_sha256="a" * 64,
        uv_evidence_sha256="b" * 64,
    )
    parsed, binary = _read_glb(glb)
    primitive = parsed["meshes"][-1]["primitives"][0]
    values = subject._accessor_values(
        parsed,
        binary,
        primitive["attributes"]["POSITION"],
        label="plate POSITION",
        component_type=5126,
        kind="VEC3",
    )
    assert abs(float(values[0][2]) - subject.OFFSET_METERS) < 1.0e-7
