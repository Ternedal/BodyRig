from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from bodyrig.bridges.sith_pbr_material import _read_glb, _write_glb
from bodyrig.fine_identity_application import build_requirement
import bodyrig.photoidentity_dental_graft as graft
from bodyrig.photoidentity_dental_reconstruction import (
    CONFIG_FORMAT,
    DENTAL_IMAGE,
    DENTAL_MATERIAL,
    MESH_NAME,
    MOUTH_MATERIAL,
    NODE_NAME,
    RESULT_FORMAT,
)


REVISION = "a" * 40
ATTESTATION = "c" * 64
AUTHORITY = "b" * 64
INPUT_SHA = "d" * 64


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _candidate_vrm() -> bytes:
    binary = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []

    def add(raw: bytes, *, component: int, count: int, kind: str, target: int | None = None) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(raw)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(raw)}
        if target is not None:
            view["target"] = target
        views.append(view)
        accessors.append(
            {
                "bufferView": len(views) - 1,
                "componentType": component,
                "count": count,
                "type": kind,
            }
        )
        return len(accessors) - 1

    positions = add(
        b"".join(struct.pack("<3f", *p) for p in ((-0.01, 1.52, 0.05), (0.01, 1.52, 0.05), (0.0, 1.54, 0.05))),
        component=5126,
        count=3,
        kind="VEC3",
        target=34962,
    )
    normals = add(
        b"".join(struct.pack("<3f", 0.0, 0.0, 1.0) for _ in range(3)),
        component=5126,
        count=3,
        kind="VEC3",
        target=34962,
    )
    uvs = add(
        b"".join(struct.pack("<2f", *uv) for uv in ((0.0, 0.0), (1.0, 0.0), (0.5, 1.0))),
        component=5126,
        count=3,
        kind="VEC2",
        target=34962,
    )
    joints = add(
        b"".join(struct.pack("<4H", 0, 0, 0, 0) for _ in range(3)),
        component=5123,
        count=3,
        kind="VEC4",
        target=34962,
    )
    weights = add(
        b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in range(3)),
        component=5126,
        count=3,
        kind="VEC4",
        target=34962,
    )
    indices = add(
        struct.pack("<3H", 0, 1, 2),
        component=5123,
        count=3,
        kind="SCALAR",
        target=34963,
    )

    png = b"\x89PNG\r\n\x1a\nsource-dental"
    while len(binary) % 4:
        binary.append(0)
    png_offset = len(binary)
    binary.extend(png)
    views.append({"buffer": 0, "byteOffset": png_offset, "byteLength": len(png)})
    image_view = len(views) - 1

    attrs = {
        "POSITION": positions,
        "NORMAL": normals,
        "TEXCOORD_0": uvs,
        "JOINTS_0": joints,
        "WEIGHTS_0": weights,
    }
    primitives = [
        {
            "attributes": dict(attrs),
            "indices": indices,
            "material": 0,
            "mode": 4,
            "extras": {"bodyrigDentalRole": "mouth_interior"},
        },
        {
            "attributes": dict(attrs),
            "indices": indices,
            "material": 1,
            "mode": 4,
            "extras": {"bodyrigDentalRole": "upper_teeth"},
        },
        {
            "attributes": dict(attrs),
            "indices": indices,
            "material": 1,
            "mode": 4,
            "extras": {"bodyrigDentalRole": "lower_teeth"},
        },
    ]
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": accessors,
        "images": [{"name": DENTAL_IMAGE, "bufferView": image_view, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "materials": [
            {
                "name": MOUTH_MATERIAL,
                "pbrMetallicRoughness": {"baseColorFactor": [0.2, 0.03, 0.04, 1.0]},
            },
            {
                "name": DENTAL_MATERIAL,
                "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
            },
        ],
        "meshes": [{"name": MESH_NAME, "primitives": primitives}],
        "nodes": [{"name": NODE_NAME, "mesh": 0, "skin": 0}],
        "skins": [{"joints": [0]}],
        "scenes": [{"nodes": [0]}],
        "extras": {
            "bodyrig": {
                "dentalSourceRuntime": {
                    "adapter": "fixture-dental",
                    "adapterRevision": "fixture-v1",
                    "bodyrigRevision": REVISION,
                    "performerId": "42",
                    "inputManifestSha256": INPUT_SHA,
                    "fineIdentityAttestationSha256": ATTESTATION,
                    "sourceDerivedDentalIdentity": True,
                    "genericSecondaryAnatomy": False,
                    "generativeIdentitySynthesis": False,
                    "humanReviewRequired": True,
                    "promotionAuthority": False,
                    "productionActivation": False,
                }
            }
        },
    }
    return _write_glb(document, bytes(binary))


def _result(vrm: bytes) -> dict:
    return {
        "format": RESULT_FORMAT,
        "version": 1,
        "adapter": "fixture-dental",
        "adapter_revision": "fixture-v1",
        "bodyrig_revision": REVISION,
        "performer_id": "42",
        "input_manifest_sha256": INPUT_SHA,
        "fine_identity_attestation_sha256": ATTESTATION,
        "dental_vrm_sha256": _sha(vrm),
        "source_references": ["oral-a", "oral-b"],
        "source_derived_dental_identity": True,
        "generic_secondary_anatomy": False,
        "generative_identity_synthesis": False,
        "mouth_interior_source_derived": True,
        "upper_teeth_source_derived": True,
        "lower_teeth_source_derived": True,
        "appearance_source_derived": True,
        "human_review_required": True,
        "promotion_authority": False,
        "production_activation": False,
    }


def _requirement() -> dict:
    return build_requirement(
        bodyrig_revision=REVISION,
        fine_identity_authority_sha256=AUTHORITY,
        fine_identity_attestation_sha256=ATTESTATION,
    )


def _destination_vrm() -> bytes:
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": 0}],
        "bufferViews": [],
        "accessors": [],
        "materials": [],
        "meshes": [],
        "nodes": [
            {"name": "smplx_head"},
            {"name": "smplx_jaw"},
        ],
        "skins": [{"joints": [0, 1]}],
        "scenes": [{"nodes": [0, 1]}],
        "extras": {"bodyrig": {}},
    }
    return _write_glb(document, b"")


def _accessor_raw(document: dict, binary: bytes, index: int) -> bytes:
    accessor = document["accessors"][index]
    view = document["bufferViews"][accessor["bufferView"]]
    component_bytes = {5123: 2, 5126: 4}[accessor["componentType"]]
    width = {"VEC4": 4}[accessor["type"]]
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    return binary[start : start + accessor["count"] * component_bytes * width]


def test_load_candidate_binds_exact_requirement_and_result(tmp_path: Path) -> None:
    vrm = _candidate_vrm()
    vrm_path = tmp_path / "dental-source.vrm"
    result_path = tmp_path / "dental-reconstruction.json"
    vrm_path.write_bytes(vrm)
    result_path.write_text(json.dumps(_result(vrm)), encoding="utf-8")

    loaded = graft.load_dental_candidate(
        vrm_path=vrm_path,
        result_path=result_path,
        fine_identity_requirement=_requirement(),
    )
    assert loaded["vrm_sha256"] == _sha(vrm)
    assert loaded["fine_identity_attestation_sha256"] == ATTESTATION
    assert loaded["source_references"] == ["oral-a", "oral-b"]


def test_load_candidate_rejects_attestation_drift(tmp_path: Path) -> None:
    vrm = _candidate_vrm()
    vrm_path = tmp_path / "dental-source.vrm"
    result_path = tmp_path / "dental-reconstruction.json"
    vrm_path.write_bytes(vrm)
    broken = _result(vrm)
    broken["fine_identity_attestation_sha256"] = "e" * 64
    result_path.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(graft.PhotoIdentityDentalGraftError, match="attestation"):
        graft.load_dental_candidate(
            vrm_path=vrm_path,
            result_path=result_path,
            fine_identity_requirement=_requirement(),
        )


def test_graft_preserves_source_surfaces_and_rebinds_head_jaw() -> None:
    result = graft.graft_dental_candidate(
        destination_vrm=_destination_vrm(),
        candidate_vrm=_candidate_vrm(),
        head_skin_joint=0,
        jaw_skin_joint=1,
    )
    document, binary = _read_glb(result)
    node = next(item for item in document["nodes"] if item.get("name") == graft.GRAFT_NODE_NAME)
    assert node["skin"] == 0
    mesh = document["meshes"][node["mesh"]]
    by_role = {p["extras"]["bodyrigDentalRole"]: p for p in mesh["primitives"]}
    assert set(by_role) == {"mouth_interior", "upper_teeth", "lower_teeth"}

    for role, expected_joint in {
        "mouth_interior": 1,
        "upper_teeth": 0,
        "lower_teeth": 1,
    }.items():
        primitive = by_role[role]
        raw = _accessor_raw(document, binary, primitive["attributes"]["JOINTS_0"])
        joints = [struct.unpack("<4H", raw[i : i + 8])[0] for i in range(0, len(raw), 8)]
        assert joints == [expected_joint, expected_joint, expected_joint]
        assert primitive["extras"]["sourceDerivedDentalIdentity"] is True

    material_names = {item.get("name") for item in document["materials"]}
    assert graft.GRAFT_MOUTH_MATERIAL in material_names
    assert graft.GRAFT_DENTAL_MATERIAL in material_names
