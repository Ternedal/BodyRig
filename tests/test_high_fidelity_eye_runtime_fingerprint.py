from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

import bodyrig.high_fidelity_eye_runtime_fingerprint as fingerprint
from bodyrig.bridges.sith_pbr_material import _write_glb


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _build_eye_glb(*, shifted: bool = False, position_tamper: bool = False, roughness: float = 0.36) -> bytes:
    binary = bytearray()
    views: list[dict[str, object]] = []
    accessors: list[dict[str, object]] = []
    images: list[dict[str, object]] = []
    textures: list[dict[str, object]] = []
    materials: list[dict[str, object]] = []
    meshes: list[dict[str, object]] = []
    nodes: list[dict[str, object]] = []
    samplers: list[dict[str, object]] = []

    def add_view(raw: bytes) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(raw)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw)})
        return len(views) - 1

    def add_accessor(raw: bytes, *, component: int, kind: str, count: int) -> int:
        view = add_view(raw)
        accessors.append({"bufferView": view, "componentType": component, "count": count, "type": kind})
        return len(accessors) - 1

    if shifted:
        add_view(b"dummy-layout-prefix")
        accessors.append({"bufferView": 0, "componentType": 5121, "count": 1, "type": "SCALAR"})
        images.append({"name": "DummyImage", "bufferView": 0, "mimeType": "application/octet-stream"})
        samplers.append({"magFilter": 9728, "minFilter": 9728, "wrapS": 33071, "wrapT": 33071})
        textures.append({"sampler": 0, "source": 0})
        materials.append({"name": "DummyMaterial"})
        meshes.append({"name": "DummyMesh", "primitives": []})
        nodes.append({"name": "DummyNode"})

    sampler_index = len(samplers)
    samplers.append({"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497})
    source_png = b"\x89PNG\r\n\x1a\nsource-eye-bake-v1"
    image_view = add_view(source_png)
    image_index = len(images)
    images.append({"name": fingerprint.SOURCE_IMAGE_NAME, "bufferView": image_view, "mimeType": "image/png"})
    texture_index = len(textures)
    textures.append({"sampler": sampler_index, "source": image_index})

    source_material_index = len(materials)
    materials.append(
        {
            "name": fingerprint.SOURCE_MATERIAL_NAME,
            "doubleSided": False,
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": texture_index},
                "metallicFactor": 0.0,
                "roughnessFactor": roughness,
            },
        }
    )
    cornea_material_index = len(materials)
    materials.append(
        {
            "name": fingerprint.CORNEA_MATERIAL_NAME,
            "doubleSided": False,
            "alphaMode": "BLEND",
            "pbrMetallicRoughness": {
                "baseColorFactor": [1.0, 1.0, 1.0, 0.11],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.04,
            },
        }
    )

    primitives: list[dict[str, object]] = []
    for role_index, role in enumerate(fingerprint.PRIMITIVE_ROLES):
        base = float(role_index + 1)
        positions = [
            base, 0.0, 0.0,
            base, 1.0, 0.0,
            base, 0.0, 1.0,
        ]
        if position_tamper and role_index == 0:
            positions[0] += 0.125
        pos = add_accessor(struct.pack("<9f", *positions), component=5126, kind="VEC3", count=3)
        normal = add_accessor(struct.pack("<9f", *([0.0, 0.0, 1.0] * 3)), component=5126, kind="VEC3", count=3)
        uv = add_accessor(struct.pack("<6f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0), component=5126, kind="VEC2", count=3)
        joints = add_accessor(struct.pack("<12H", *([23, 24, 0, 0] * 3)), component=5123, kind="VEC4", count=3)
        weights = add_accessor(struct.pack("<12f", *([0.5, 0.5, 0.0, 0.0] * 3)), component=5126, kind="VEC4", count=3)
        indices = add_accessor(struct.pack("<3I", 0, 1, 2), component=5125, kind="SCALAR", count=3)
        primitives.append(
            {
                "attributes": {
                    "POSITION": pos,
                    "NORMAL": normal,
                    "TEXCOORD_0": uv,
                    "JOINTS_0": joints,
                    "WEIGHTS_0": weights,
                },
                "indices": indices,
                "material": cornea_material_index if role.endswith("cornea") else source_material_index,
                "mode": 4,
            }
        )

    mesh_index = len(meshes)
    meshes.append({"name": fingerprint.EYE_MESH_NAME, "primitives": primitives})
    nodes.append({"name": fingerprint.EYE_NODE_NAME, "mesh": mesh_index, "skin": 0})
    eye_metadata = {
        "format": "bodyrig-source-eye-review-runtime-metadata",
        "version": 1,
        "eyeComponentReceiptSha256": "1" * 64,
        "eyeAppearanceReceiptSha256": "2" * 64,
        "canonicalEyeBakeSha256": _sha(source_png),
        "targetModelFamily": "female",
        "leftEyeJointIndex": 23,
        "rightEyeJointIndex": 24,
        "sourceEyeSurfaceApplied": True,
        "irisIdentityIsolated": False,
        "irisAppearanceStatus": "review-pending",
        "cornealMaterialStatus": "runtime-applied",
        "eyelashStatus": "missing",
        "skinIndex": 0,
        "physicalFaceCloseupReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "eyeComponentAuthority": False,
        "productionActivation": False,
    }
    document = {
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": accessors,
        "images": images,
        "textures": textures,
        "materials": materials,
        "meshes": meshes,
        "nodes": nodes,
        "samplers": samplers,
        "extras": {"bodyrig": {"eyeReviewRuntime": eye_metadata}},
    }
    return _write_glb(document, bytes(binary))


def test_semantic_fingerprint_ignores_absolute_indices_and_buffer_offsets() -> None:
    canonical = fingerprint.semantic_eye_runtime_fingerprint(_build_eye_glb(shifted=False))
    shifted = fingerprint.semantic_eye_runtime_fingerprint(_build_eye_glb(shifted=True))

    assert canonical == shifted
    assert canonical["payload"]["semantics"] == "index-and-buffer-offset-independent-eye-stage-v1"
    assert canonical["payload"]["primitiveOrder"] == list(fingerprint.PRIMITIVE_ROLES)


def test_semantic_fingerprint_changes_when_eye_geometry_bytes_change() -> None:
    canonical = fingerprint.semantic_eye_runtime_fingerprint(_build_eye_glb())
    tampered = fingerprint.semantic_eye_runtime_fingerprint(_build_eye_glb(position_tamper=True))

    assert canonical["fingerprintSha256"] != tampered["fingerprintSha256"]
    assert (
        canonical["payload"]["primitives"]["left_surface"]["attributes"]["POSITION"]["payloadSha256"]
        != tampered["payload"]["primitives"]["left_surface"]["attributes"]["POSITION"]["payloadSha256"]
    )


def test_semantic_fingerprint_rejects_noncanonical_source_material() -> None:
    with pytest.raises(fingerprint.HighFidelityEyeRuntimeFingerprintError, match="material factors"):
        fingerprint.semantic_eye_runtime_fingerprint(_build_eye_glb(roughness=0.52))


def test_write_fingerprint_is_create_only_and_cleans_failed_post_write_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fingerprint, "ui_jobs_dir", lambda: tmp_path / "ui")
    eligibility_file = tmp_path / "eligibility.json"
    reviewed_receipt = tmp_path / "reviewed-runtime.json"
    reviewed_vrm = tmp_path / "reviewed.vrm"
    eligibility_file.write_text("{}\n", encoding="utf-8")
    reviewed_receipt.write_text("{}\n", encoding="utf-8")
    reviewed_vrm.write_bytes(_build_eye_glb())
    review_sha = _sha(reviewed_vrm.read_bytes())
    semantic = fingerprint.semantic_eye_runtime_fingerprint(reviewed_vrm.read_bytes())
    eligibility = {
        "bodyrigRevision": "a" * 40,
        "previewJobId": "hfpreview-" + "1" * 32,
        "canonicalBodyId": "body-1",
        "candidatePackageSha256": "b" * 64,
        "reviewVrmSha256": review_sha,
    }
    reviewed = {"bodyrigRevision": "c" * 40}

    monkeypatch.setattr(
        fingerprint,
        "_authorities",
        lambda *args, **kwargs: (eligibility, eligibility_file, reviewed, reviewed_receipt, reviewed_vrm, semantic),
    )
    value = fingerprint.write_fingerprint(
        eligibility["previewJobId"],
        base_runtime_dir=tmp_path,
        iris_candidate_dir=tmp_path,
        source_eye_appearance_dir=tmp_path,
        reviewed_runtime_dir=tmp_path,
        bodyrig_revision="d" * 40,
    )
    path = Path(value["fingerprintPath"])
    assert path.is_file()
    assert value["fingerprintSha256"] == semantic["fingerprintSha256"]
    assert value["eyeComponentAuthority"] is False
    assert value["packageMutationPerformed"] is False
    assert value["eyesPromoted"] is False
    assert value["productionActivation"] is False

    with pytest.raises(fingerprint.HighFidelityEyeRuntimeFingerprintError, match="overwrite"):
        fingerprint.write_fingerprint(
            eligibility["previewJobId"],
            base_runtime_dir=tmp_path,
            iris_candidate_dir=tmp_path,
            source_eye_appearance_dir=tmp_path,
            reviewed_runtime_dir=tmp_path,
            bodyrig_revision="d" * 40,
        )

    path.unlink()
    original_read = fingerprint.read_fingerprint
    monkeypatch.setattr(
        fingerprint,
        "read_fingerprint",
        lambda *args, **kwargs: (_ for _ in ()).throw(fingerprint.HighFidelityEyeRuntimeFingerprintError("post-write fail")),
    )
    with pytest.raises(fingerprint.HighFidelityEyeRuntimeFingerprintError, match="post-write fail"):
        fingerprint.write_fingerprint(
            eligibility["previewJobId"],
            base_runtime_dir=tmp_path,
            iris_candidate_dir=tmp_path,
            source_eye_appearance_dir=tmp_path,
            reviewed_runtime_dir=tmp_path,
            bodyrig_revision="d" * 40,
        )
    assert not path.exists()
    monkeypatch.setattr(fingerprint, "read_fingerprint", original_read)


def test_receipt_payload_hash_is_self_consistent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fingerprint, "ui_jobs_dir", lambda: tmp_path / "ui")
    eligibility_file = tmp_path / "eligibility.json"
    reviewed_receipt = tmp_path / "reviewed-runtime.json"
    reviewed_vrm = tmp_path / "reviewed.vrm"
    eligibility_file.write_text(json.dumps({"authority": "eligibility"}), encoding="utf-8")
    reviewed_receipt.write_text(json.dumps({"authority": "iris-runtime"}), encoding="utf-8")
    reviewed_vrm.write_bytes(_build_eye_glb())
    semantic = fingerprint.semantic_eye_runtime_fingerprint(reviewed_vrm.read_bytes())
    eligibility = {
        "bodyrigRevision": "a" * 40,
        "previewJobId": "hfpreview-" + "2" * 32,
        "canonicalBodyId": "body-2",
        "candidatePackageSha256": "b" * 64,
        "reviewVrmSha256": _sha(reviewed_vrm.read_bytes()),
    }
    reviewed = {"bodyrigRevision": "c" * 40}
    monkeypatch.setattr(
        fingerprint,
        "_authorities",
        lambda *args, **kwargs: (eligibility, eligibility_file, reviewed, reviewed_receipt, reviewed_vrm, semantic),
    )
    value = fingerprint.write_fingerprint(
        eligibility["previewJobId"],
        base_runtime_dir=tmp_path,
        iris_candidate_dir=tmp_path,
        source_eye_appearance_dir=tmp_path,
        reviewed_runtime_dir=tmp_path,
        bodyrig_revision="d" * 40,
    )
    assert fingerprint._canonical_sha(value["fingerprint"]) == value["fingerprintSha256"]
