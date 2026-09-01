from __future__ import annotations

import struct
from pathlib import Path

from bodyrig.avatar import REQUIRED_HUMAN_BONES, _glb, _thumbnail_png
from bodyrig.fidelity_ab import compare_packages
from bodyrig.fidelity_ab_cli import main
from bodyrig.package import build_package


def _avatar(*, seam_split: bool, move_split: bool = False, image_payload: bytes = b"fixture-texture") -> bytes:
    positions = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
    ]
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    if seam_split:
        positions.append((0.01 if move_split else 0.0, 0.0, 0.0))
        uvs.append((0.25, 0.0))
    vertex_count = len(positions)
    normals = [(0.0, 0.0, 1.0)] * vertex_count
    joints = [(0, 1, 2, 3)] * vertex_count
    weights = [(0.25, 0.25, 0.25, 0.25)] * vertex_count
    indices = [0, 1, 2, (4 if seam_split else 0), 2, 3]

    binary = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []

    def append_bytes(payload: bytes, *, target: int | None = None) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(payload)
        view: dict = {"buffer": 0, "byteOffset": offset, "byteLength": len(payload)}
        if target is not None:
            view["target"] = target
        buffer_views.append(view)
        return len(buffer_views) - 1

    def accessor(payload: bytes, *, component_type: int, count: int, kind: str, target: int | None = None) -> int:
        view = append_bytes(payload, target=target)
        accessors.append({"bufferView": view, "componentType": component_type, "count": count, "type": kind})
        return len(accessors) - 1

    position_accessor = accessor(
        b"".join(struct.pack("<fff", *value) for value in positions),
        component_type=5126,
        count=vertex_count,
        kind="VEC3",
        target=34962,
    )
    normal_accessor = accessor(
        b"".join(struct.pack("<fff", *value) for value in normals),
        component_type=5126,
        count=vertex_count,
        kind="VEC3",
        target=34962,
    )
    joint_accessor = accessor(
        b"".join(struct.pack("<HHHH", *value) for value in joints),
        component_type=5123,
        count=vertex_count,
        kind="VEC4",
        target=34962,
    )
    weight_accessor = accessor(
        b"".join(struct.pack("<ffff", *value) for value in weights),
        component_type=5126,
        count=vertex_count,
        kind="VEC4",
        target=34962,
    )
    uv_accessor = accessor(
        b"".join(struct.pack("<ff", *value) for value in uvs),
        component_type=5126,
        count=vertex_count,
        kind="VEC2",
        target=34962,
    )
    index_accessor = accessor(
        b"".join(struct.pack("<H", value) for value in indices),
        component_type=5123,
        count=len(indices),
        kind="SCALAR",
        target=34963,
    )

    identity = [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]
    inverse_accessor = accessor(
        b"".join(struct.pack("<" + "f" * 16, *identity) for _ in REQUIRED_HUMAN_BONES),
        component_type=5126,
        count=len(REQUIRED_HUMAN_BONES),
        kind="MAT4",
    )
    image_view = append_bytes(image_payload)

    nodes = [
        {"name": bone, "translation": [0.0, float(index) * 0.01, 0.0]}
        for index, bone in enumerate(REQUIRED_HUMAN_BONES)
    ]
    mesh_node = len(nodes)
    nodes.append({"name": "Body", "mesh": 0, "skin": 0})
    human_bones = {bone: {"node": index} for index, bone in enumerate(REQUIRED_HUMAN_BONES)}

    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "images": [{"bufferView": image_view, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "samplers": [],
        "materials": [
            {
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicFactor": 0.0,
                    "roughnessFactor": 1.0,
                }
            }
        ],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": position_accessor,
                            "NORMAL": normal_accessor,
                            "JOINTS_0": joint_accessor,
                            "WEIGHTS_0": weight_accessor,
                            "TEXCOORD_0": uv_accessor,
                        },
                        "indices": index_accessor,
                        "material": 0,
                        "mode": 4,
                    }
                ]
            }
        ],
        "nodes": nodes,
        "skins": [
            {
                "joints": list(range(len(REQUIRED_HUMAN_BONES))),
                "skeleton": 0,
                "inverseBindMatrices": inverse_accessor,
            }
        ],
        "scenes": [{"nodes": [0, mesh_node]}],
        "scene": 0,
        "extensionsUsed": ["VRMC_vrm"],
        "extensions": {
            "VRMC_vrm": {
                "specVersion": "1.0",
                "meta": {
                    "name": "Fixture",
                    "authors": ["BodyRig"],
                    "licenseUrl": "https://example.invalid/license",
                },
                "humanoid": {"humanBones": human_bones},
            }
        },
    }
    return _glb(document, bytes(binary))


def _bodyprint(*, shoulder: float = 0.24) -> dict:
    return {
        "format": "modelrig-bodyprint",
        "version": 1,
        "shape": {
            "height_scale": 1.0,
            "shoulder_to_height": shoulder,
            "hip_to_height": 0.19,
            "arm_to_height": 0.36,
            "leg_to_height": 0.51,
        },
    }


def _provenance() -> dict:
    return {
        "format": "modelrig-body-provenance",
        "version": 1,
        "created_at": "2026-09-01T00:00:00Z",
        "source": {"kind": "user-supplied-local-media", "count": 1},
        "synthetic_avatar": True,
        "pipeline": [{"stage": "fit", "adapter": "fixture", "revision": "v1"}],
    }


def _package(path: Path, *, avatar: bytes, bodyprint: dict | None = None) -> Path:
    return build_package(
        path,
        body_id="fixture",
        name="Fixture",
        avatar_vrm=avatar,
        bodyprint=bodyprint or _bodyprint(),
        provenance=_provenance(),
        thumbnail_png=_thumbnail_png(16, 16),
    )


def test_clean_appearance_ab_ignores_uv_seam_vertex_duplication(tmp_path: Path) -> None:
    left = _package(tmp_path / "left.mrbody", avatar=_avatar(seam_split=False))
    right = _package(tmp_path / "right.mrbody", avatar=_avatar(seam_split=True))
    evidence = compare_packages(left, right)
    assert evidence["invariants"] == {
        "body_id_identical": True,
        "bodyprint_identical": True,
        "geometry_identical": True,
        "skin_binding_identical": True,
        "rig_identical": True,
        "appearance_identical": False,
        "appearance_changed": True,
        "clean_appearance_ab": True,
    }
    assert evidence["left"]["triangle_count"] == 2
    assert evidence["right"]["triangle_count"] == 2
    assert evidence["human_visual_authority_required"] is True
    assert evidence["production_activation"] is False


def test_clean_appearance_ab_rejects_real_geometry_change(tmp_path: Path) -> None:
    left = _package(tmp_path / "left.mrbody", avatar=_avatar(seam_split=False))
    right = _package(tmp_path / "right.mrbody", avatar=_avatar(seam_split=True, move_split=True))
    evidence = compare_packages(left, right)
    assert evidence["invariants"]["geometry_identical"] is False
    assert evidence["invariants"]["skin_binding_identical"] is False
    assert evidence["invariants"]["clean_appearance_ab"] is False


def test_clean_appearance_ab_rejects_bodyprint_drift(tmp_path: Path) -> None:
    avatar = _avatar(seam_split=False)
    left = _package(tmp_path / "left.mrbody", avatar=avatar)
    right = _package(tmp_path / "right.mrbody", avatar=avatar, bodyprint=_bodyprint(shoulder=0.25))
    evidence = compare_packages(left, right)
    assert evidence["invariants"]["bodyprint_identical"] is False
    assert evidence["invariants"]["clean_appearance_ab"] is False


def test_cli_can_fail_closed_and_write_create_only_evidence(tmp_path: Path) -> None:
    left = _package(tmp_path / "left.mrbody", avatar=_avatar(seam_split=False))
    right = _package(tmp_path / "right.mrbody", avatar=_avatar(seam_split=True))
    output = tmp_path / "ab-evidence.json"
    assert main([str(left), str(right), "--require-clean-appearance-ab", "--out", str(output)]) == 0
    assert output.is_file()
    assert main([str(left), str(right), "--require-clean-appearance-ab", "--out", str(output)]) == 1
