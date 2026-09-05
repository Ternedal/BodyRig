from __future__ import annotations

import hashlib
import json
import struct

import pytest

import bodyrig.high_fidelity_eye_promotion as promotion
from bodyrig.bridges.sith_pbr_material import _read_glb, _write_glb
from bodyrig.high_fidelity_eye_runtime_fingerprint import semantic_eye_runtime_fingerprint


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _components(*, hair: str = "missing", eyes: str = "partial") -> dict[str, object]:
    states = {
        "body_anatomy": "complete",
        "skin_appearance": "partial",
        "hair": hair,
        "eyes": eyes,
        "face_secondary": "missing",
    }
    blockers = [name for name in ("body_anatomy", "skin_appearance", "hair", "eyes", "face_secondary") if states[name] != "complete"]
    return {
        "format": "bodyrig-avatar-fidelity-components",
        "version": 1,
        "components": states,
        "highFidelityReady": False,
        "blockers": blockers,
        "humanReviewRequired": True,
        "productionReady": False,
    }


def _anatomy(source_sha: str) -> dict[str, object]:
    return {
        "format": "bodyrig-body-anatomy-promotion",
        "version": 1,
        "policyRevision": "bodyrig-high-fidelity-anatomy-promotion-v1",
        "previewJobId": "hfpreview-" + "1" * 32,
        "componentReviewSha256": "1" * 64,
        "sourcePackageSha256": source_sha,
        "anatomyGateSha256": "2" * 64,
        "bodyrigRevision": "a" * 40,
        "targetFamily": "female",
        "component": "body_anatomy",
        "productionActivation": False,
    }


def _hair(source_sha: str) -> dict[str, object]:
    return {
        "format": "bodyrig-hair-promotion",
        "version": 1,
        "policyRevision": "bodyrig-high-fidelity-hair-promotion-v1",
        "previewJobId": "hfpreview-" + "1" * 32,
        "sourceBodyRigRevision": "a" * 40,
        "promotionBodyRigRevision": "b" * 40,
        "targetFamily": "female",
        "sourceCandidatePackageSha256": source_sha,
        "anatomyPromotedPackageSha256": "3" * 64,
        "anatomyPromotionReceiptSha256": "4" * 64,
        "hairDeformationReviewSha256": "5" * 64,
        "combinedBridgeResultSha256": "6" * 64,
        "rebuiltHairBridgeSha256": "7" * 64,
        "rebuiltHairRuntimeReceiptSha256": "8" * 64,
        "rebuiltHairReviewVrmSha256": "9" * 64,
        "component": "hair",
        "eyesImported": False,
        "productionActivation": False,
    }


def test_destination_lineage_accepts_anatomy_only_and_canonical_hair_promotion() -> None:
    source_sha = "a" * 64
    anatomy_document = {
        "extras": {"bodyrig": {"fidelityComponents": _components(), "bodyAnatomyPromotion": _anatomy(source_sha)}},
        "nodes": [],
        "materials": [],
        "images": [],
    }
    _bodyrig, before, hair_complete = promotion._assert_destination_lineage(
        anatomy_document,
        source_candidate_sha=source_sha,
        canonical_body_id="body-1",
    )
    assert before["components"]["body_anatomy"] == "complete"
    assert hair_complete is False

    hair_document = {
        "extras": {
            "bodyrig": {
                "fidelityComponents": _components(hair="complete"),
                "bodyAnatomyPromotion": _anatomy(source_sha),
                "hairPromotion": _hair(source_sha),
            }
        },
        "nodes": [],
        "materials": [],
        "images": [],
    }
    _bodyrig, before, hair_complete = promotion._assert_destination_lineage(
        hair_document,
        source_candidate_sha=source_sha,
        canonical_body_id="body-1",
    )
    assert before["components"]["hair"] == "complete"
    assert hair_complete is True


def test_destination_lineage_rejects_unproven_complete_hair() -> None:
    source_sha = "a" * 64
    document = {
        "extras": {"bodyrig": {"fidelityComponents": _components(hair="complete"), "bodyAnatomyPromotion": _anatomy(source_sha)}},
        "nodes": [],
        "materials": [],
        "images": [],
    }
    with pytest.raises(promotion.HighFidelityEyePromotionError, match="hair=complete lacks embedded hair promotion"):
        promotion._assert_destination_lineage(document, source_candidate_sha=source_sha, canonical_body_id="body-1")


def _runtime_pair() -> tuple[bytes, bytes]:
    geometry = {
        "format": "bodyrig-sith-body-geometry-authority",
        "version": 2,
        "method": "exact-sith-reconstruction-bytes-v2",
        "identity": "same-source-geometry-for-test",
    }
    source_binary = bytearray()
    source_views: list[dict[str, object]] = []
    source_accessors: list[dict[str, object]] = []

    def add_source_view(raw: bytes) -> int:
        while len(source_binary) % 4:
            source_binary.append(0)
        offset = len(source_binary)
        source_binary.extend(raw)
        source_views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw)})
        return len(source_views) - 1

    def add_accessor(raw: bytes, component: int, kind: str, count: int) -> int:
        source_accessors.append({"bufferView": add_source_view(raw), "componentType": component, "count": count, "type": kind})
        return len(source_accessors) - 1

    source_png = b"\x89PNG\r\n\x1a\nexact-source-eye-bake"
    image_view = add_source_view(source_png)
    primitives: list[dict[str, object]] = []
    for index in range(4):
        x = float(index + 1)
        pos = add_accessor(struct.pack("<9f", x, 0, 0, x, 1, 0, x, 0, 1), 5126, "VEC3", 3)
        normal = add_accessor(struct.pack("<9f", *([0.0, 0.0, 1.0] * 3)), 5126, "VEC3", 3)
        uv = add_accessor(struct.pack("<6f", 0, 0, 1, 0, 0, 1), 5126, "VEC2", 3)
        joints = add_accessor(struct.pack("<12H", *([0, 1, 0, 0] * 3)), 5123, "VEC4", 3)
        weights = add_accessor(struct.pack("<12f", *([0.5, 0.5, 0, 0] * 3)), 5126, "VEC4", 3)
        indices = add_accessor(struct.pack("<3I", 0, 1, 2), 5125, "SCALAR", 3)
        primitives.append(
            {
                "attributes": {"POSITION": pos, "NORMAL": normal, "TEXCOORD_0": uv, "JOINTS_0": joints, "WEIGHTS_0": weights},
                "indices": indices,
                "material": 1 if index % 2 else 0,
                "mode": 4,
            }
        )
    eye_metadata = {
        "format": "bodyrig-source-eye-review-runtime-metadata",
        "version": 1,
        "eyeComponentReceiptSha256": "1" * 64,
        "eyeAppearanceReceiptSha256": "2" * 64,
        "canonicalEyeBakeSha256": _sha(source_png),
        "targetModelFamily": "female",
        "leftEyeJointIndex": 0,
        "rightEyeJointIndex": 1,
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
    source_document = {
        "buffers": [{"byteLength": len(source_binary)}],
        "bufferViews": source_views,
        "accessors": source_accessors,
        "images": [{"name": "BodyRigSourceEyeBake", "bufferView": image_view, "mimeType": "image/png"}],
        "textures": [{"sampler": 0, "source": 0}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
        "materials": [
            {
                "name": "BodyRigSourceEyeSurface",
                "doubleSided": False,
                "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0, "roughnessFactor": 0.36},
            },
            {
                "name": "BodyRigCorneaReview",
                "doubleSided": False,
                "alphaMode": "BLEND",
                "pbrMetallicRoughness": {"baseColorFactor": [1.0, 1.0, 1.0, 0.11], "metallicFactor": 0.0, "roughnessFactor": 0.04},
            },
        ],
        "meshes": [{"name": "BodyRigSourceEyeReviewMesh", "primitives": primitives}],
        "nodes": [{"name": "JointA"}, {"name": "JointB"}, {"name": "BodyRigSourceEyeReview", "mesh": 0, "skin": 0}],
        "skins": [{"joints": [0, 1]}],
        "scenes": [{"nodes": [2]}],
        "extras": {"bodyrig": {"sourceGeometryAuthority": geometry, "eyeReviewRuntime": eye_metadata}},
    }
    source = _write_glb(source_document, bytes(source_binary))

    destination_binary = b"existing-destination-body-bytes"
    destination_document = {
        "buffers": [{"byteLength": len(destination_binary)}],
        "bufferViews": [],
        "accessors": [],
        "images": [],
        "textures": [],
        "samplers": [{"magFilter": 9728, "minFilter": 9728, "wrapS": 33071, "wrapT": 33071}],
        "materials": [{"name": "ExistingBodyMaterial"}],
        "meshes": [{"name": "ExistingBodyMesh", "primitives": []}],
        "nodes": [{"name": "JointA"}, {"name": "JointB"}, {"name": "ExistingBody", "mesh": 0, "skin": 0}],
        "skins": [{"joints": [0, 1]}],
        "scenes": [{"nodes": [2]}],
        "extras": {
            "bodyrig": {
                "sourceGeometryAuthority": geometry,
                "fidelityComponents": _components(hair="complete"),
                "bodyAnatomyPromotion": _anatomy("a" * 64),
                "hairPromotion": _hair("a" * 64),
                "keepMe": {"authority": "must-survive-eye-graft"},
            }
        },
    }
    destination = _write_glb(destination_document, destination_binary)
    return destination, source


def test_graft_preserves_destination_and_matches_source_eye_fingerprint() -> None:
    destination, source = _runtime_pair()
    expected = semantic_eye_runtime_fingerprint(source)

    grafted = promotion.graft_eye_stage(destination, source)
    actual = semantic_eye_runtime_fingerprint(grafted)

    assert actual == expected
    document, _binary = _read_glb(grafted)
    names = [node.get("name") for node in document["nodes"] if isinstance(node, dict)]
    assert "ExistingBody" in names
    assert "BodyRigSourceEyeReview" in names
    bodyrig = document["extras"]["bodyrig"]
    assert bodyrig["keepMe"] == {"authority": "must-survive-eye-graft"}
    assert bodyrig["fidelityComponents"]["components"]["hair"] == "complete"
    assert bodyrig["fidelityComponents"]["components"]["eyes"] == "partial"
    assert bodyrig["hairPromotion"]["eyesImported"] is False
    assert bodyrig["eyeReviewRuntime"]["irisAppearanceStatus"] == "review-pending"


def test_graft_rejects_destination_with_different_skeleton_order() -> None:
    destination, source = _runtime_pair()
    document, binary = _read_glb(destination)
    document["nodes"][0]["name"] = "DifferentJoint"
    changed = _write_glb(document, binary)

    with pytest.raises(promotion.HighFidelityEyePromotionError, match="joint ordering differs"):
        promotion.graft_eye_stage(changed, source)
