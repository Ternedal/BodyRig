from __future__ import annotations

import hashlib
import json
import struct

import numpy as np
import pytest

import bodyrig.hands_feet_nails_landmark_evidence as landmark_evidence
from bodyrig.bridges.sith_pbr_material import _decode_rgb_png, _encode_rgb_png, _read_glb, _write_glb
from bodyrig.hands_feet_nails_detail_candidate import (
    CHANNEL_DELTA_CAP,
    FOOT_TARGETS,
    HAND_TARGETS,
    HandsFeetNailsDetailCandidateError,
    apply_hfn_detail_to_avatar,
)
from bodyrig.photoidentity_nail_landmarks import (
    FORMAT as PROJECTION_FORMAT,
    POLICY_REVISION as PROJECTION_POLICY_REVISION,
    VERSION as PROJECTION_VERSION,
)


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _projection(region: str, *, complete: bool = True) -> dict:
    if region.endswith("fingernails"):
        labels = ["thumb", "index", "middle", "ring", "pinky"]
        if not complete:
            labels = labels[:-1]
        positions = {
            label: {
                "x_norm": round(0.18 + index * 0.15, 8),
                "y_norm": round(0.32 + (index % 2) * 0.08, 8),
                "confidence": 0.95,
            }
            for index, label in enumerate(labels)
        }
        required = 5
    else:
        labels = ["big_toe", "small_toe", "heel"]
        positions = {
            "big_toe": {"x_norm": 0.35, "y_norm": 0.42, "confidence": 0.95},
            "small_toe": {"x_norm": 0.62, "y_norm": 0.45, "confidence": 0.94},
            "heel": {"x_norm": 0.50, "y_norm": 0.80, "confidence": 0.96},
        }
        required = 3
    return {
        "format": PROJECTION_FORMAT,
        "version": PROJECTION_VERSION,
        "policy_revision": PROJECTION_POLICY_REVISION,
        "region": region,
        "canvas_width": 1024,
        "canvas_height": 1024,
        "source_crop_px": [0, 0, 1000, 1000],
        "landmarks": positions,
        "required_landmark_count": required,
        "observed_landmark_count": len(positions),
        "application_ready": len(positions) == required,
        "source_coordinate_authority": "openpose-semantic-landmarks-explicit-crop",
        "package_application_authority": False,
        "human_review_required": True,
        "production_activation": False,
    }


def _evidence(*, complete: bool = True) -> dict:
    mapping = {
        "left_hand": "left_fingernails",
        "right_hand": "right_fingernails",
        "left_foot": "left_toenails",
        "right_foot": "right_toenails",
    }
    regions = {}
    for index, (capture_region, semantic_region) in enumerate(mapping.items(), 1):
        projection = _projection(semantic_region, complete=complete or capture_region != "left_hand")
        regions[capture_region] = {
            "capture_region": capture_region,
            "semantic_region": semantic_region,
            "scene_id": f"scene-{index}",
            "source_media_sha256": _sha(f"media-{index}"),
            "timestamp_ms": index * 1000,
            "crop_norm": [0.0, 0.0, 1.0, 1.0],
            "crop_px": [0, 0, 1000, 1000],
            "crop_projection_method": "normalized-source-crop-round-v1",
            "source_frame_sha256": _sha(f"frame-{index}"),
            "source_frame_width": 1000,
            "source_frame_height": 1000,
            "closeup_image_sha256": _sha(f"closeup-{index}"),
            "projection": projection,
        }
    return {
        "format": landmark_evidence.FORMAT,
        "version": landmark_evidence.VERSION,
        "policy_revision": landmark_evidence.POLICY_REVISION,
        "person_id": "person-" + "1" * 32,
        "body_revision": "body-r0001",
        "capture_id": "hfncap-" + "2" * 32,
        "source_bodyrig_revision": "3" * 40,
        "evidence_bodyrig_revision": "4" * 40,
        "source_capture_sha256": _sha("capture"),
        "source_manifest_sha256": _sha("manifest"),
        "frame_ffmpeg_version": "ffmpeg version 7.0-test",
        "openpose_adapter": landmark_evidence.OPENPOSE_ADAPTER,
        "openpose_revision": landmark_evidence.OPENPOSE_REVISION,
        "region_count": 4,
        "regions": regions,
        "all_regions_application_ready": all(
            item["projection"]["application_ready"] is True for item in regions.values()
        ),
        "source_paths_persisted": False,
        "package_application_authority": False,
        "human_review_required": True,
        "production_activation": False,
    }


def _closeup(color: tuple[int, int, int]) -> bytes:
    image = np.empty((1024, 1024, 3), dtype=np.uint8)
    image[:, :] = color
    # Add deterministic local structure so source-detail residual transfer is exercised.
    image[280:520:4, 140:880:7, 0] = min(255, color[0] + 22)
    image[310:550:5, 150:900:9, 1] = max(0, color[1] - 18)
    return _encode_rgb_png(np, image)


def _closeups() -> dict[str, bytes]:
    return {
        "left_hand": _closeup((188, 142, 132)),
        "right_hand": _closeup((176, 134, 126)),
        "left_foot": _closeup((170, 128, 120)),
        "right_foot": _closeup((182, 138, 128)),
    }


def _avatar(*, broad_thumb: bool = False) -> bytes:
    targets = [
        *(joint for _label, joint in HAND_TARGETS["left_hand"]),
        *(joint for _label, joint in HAND_TARGETS["right_hand"]),
        FOOT_TARGETS["left_foot"][0],
        FOOT_TARGETS["right_foot"][0],
    ]
    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    joints: list[tuple[int, int, int, int]] = []
    weights: list[tuple[float, float, float, float]] = []
    indices: list[int] = []
    columns = 4
    for group, joint in enumerate(targets):
        row = group // columns
        col = group % columns
        if broad_thumb and group == 0:
            tri = ((0.02, 0.02), (0.98, 0.02), (0.02, 0.98))
        else:
            cx = 0.10 + col * 0.22
            cy = 0.12 + row * 0.24
            tri = ((cx, cy), (cx + 0.055, cy), (cx + 0.025, cy + 0.055))
        base = len(positions)
        for offset, uv in enumerate(tri):
            positions.append((float(group), float(offset), 0.0))
            normals.append((0.0, 0.0, 1.0))
            uvs.append(uv)
            joints.append((joint, 0, 0, 0))
            weights.append((1.0, 0.0, 0.0, 0.0))
        indices.extend((base, base + 1, base + 2))

    binary = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []

    def add_view(raw: bytes, target: int | None = None) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(raw)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(raw)}
        if target is not None:
            view["target"] = target
        views.append(view)
        return len(views) - 1

    def add_accessor(raw: bytes, component: int, count: int, kind: str, target: int | None = None) -> int:
        view = add_view(raw, target)
        accessors.append({"bufferView": view, "componentType": component, "count": count, "type": kind})
        return len(accessors) - 1

    pos = add_accessor(np.asarray(positions, dtype="<f4").tobytes(), 5126, len(positions), "VEC3", 34962)
    normal = add_accessor(np.asarray(normals, dtype="<f4").tobytes(), 5126, len(normals), "VEC3", 34962)
    uv = add_accessor(np.asarray(uvs, dtype="<f4").tobytes(), 5126, len(uvs), "VEC2", 34962)
    joint = add_accessor(np.asarray(joints, dtype="<u2").tobytes(), 5123, len(joints), "VEC4", 34962)
    weight = add_accessor(np.asarray(weights, dtype="<f4").tobytes(), 5126, len(weights), "VEC4", 34962)
    index = add_accessor(np.asarray(indices, dtype="<u4").tobytes(), 5125, len(indices), "SCALAR", 34963)

    base = np.empty((512, 512, 3), dtype=np.uint8)
    base[:, :] = (132, 118, 110)
    base_png = _encode_rgb_png(np, base)
    image_view = add_view(base_png)

    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": accessors,
        "meshes": [
            {
                "name": "BodyRigSourceDerivedMesh",
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": pos,
                            "NORMAL": normal,
                            "TEXCOORD_0": uv,
                            "JOINTS_0": joint,
                            "WEIGHTS_0": weight,
                        },
                        "indices": index,
                        "material": 0,
                        "mode": 4,
                    }
                ],
            }
        ],
        "materials": [
            {
                "name": "BodyRigSourceDerivedMaterial",
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.9,
                },
            }
        ],
        "textures": [{"source": 0}],
        "images": [{"name": "BodyRigAvatarTexture", "bufferView": image_view, "mimeType": "image/png"}],
        "extras": {"bodyrig": {}},
    }
    return _write_glb(document, bytes(binary))


def _basecolor_bytes(avatar: bytes) -> bytes:
    document, binary = _read_glb(avatar)
    image = document["images"][document["textures"][0]["source"]]
    view = document["bufferViews"][image["bufferView"]]
    offset = int(view.get("byteOffset", 0))
    return binary[offset:offset + int(view["byteLength"])]


def test_apply_candidate_changes_only_bounded_basecolor_and_keeps_authority_false() -> None:
    source = _avatar()
    evidence = _evidence()
    output, receipt = apply_hfn_detail_to_avatar(
        source,
        evidence=evidence,
        evidence_sha256=_sha("landmark-evidence"),
        source_package_sha256=_sha("source-package"),
        canonical_body_id="body-" + "a" * 32,
        closeup_png=_closeups(),
        candidate_bodyrig_revision="5" * 40,
    )

    assert output != source
    assert _basecolor_bytes(output) != _basecolor_bytes(source)
    document, _ = _read_glb(output)
    embedded = document["extras"]["bodyrig"]["handsFeetNailsDetailCandidate"]
    assert embedded["method"] == "source-patch-bounded-distal-uv-refinement-v1"
    assert embedded["geometryMutationPerformed"] is False
    assert embedded["packageMutationPerformed"] is True
    assert embedded["comparisonOnly"] is True
    assert embedded["humanReviewRequired"] is True
    assert embedded["productionActivation"] is False
    assert embedded["targetPixelCount"] > 0
    assert receipt["portable_geometry_fingerprint_sha256"] == embedded["portableGeometryFingerprintSha256"]
    assert receipt["max_observed_channel_delta"] <= CHANNEL_DELTA_CAP + 1e-6
    assert receipt["source_paths_persisted"] is False
    assert receipt["generic_guessing_permitted"] is False
    assert len(receipt["domains"]) == 12

    before = _decode_rgb_png(np, _basecolor_bytes(source)).astype(np.int16)
    after = _decode_rgb_png(np, _basecolor_bytes(output)).astype(np.int16)
    observed = np.abs(after - before).max() / 255.0
    assert observed <= CHANNEL_DELTA_CAP + (1.0 / 255.0) + 1e-6


def test_apply_candidate_rejects_incomplete_landmark_authority() -> None:
    evidence = _evidence(complete=False)
    with pytest.raises(HandsFeetNailsDetailCandidateError, match="not application-ready"):
        apply_hfn_detail_to_avatar(
            _avatar(),
            evidence=evidence,
            evidence_sha256=_sha("landmark-evidence"),
            source_package_sha256=_sha("source-package"),
            canonical_body_id="body-" + "a" * 32,
            closeup_png=_closeups(),
            candidate_bodyrig_revision="5" * 40,
        )


def test_apply_candidate_rejects_broad_distal_uv_domain() -> None:
    with pytest.raises(HandsFeetNailsDetailCandidateError, match="too broad"):
        apply_hfn_detail_to_avatar(
            _avatar(broad_thumb=True),
            evidence=_evidence(),
            evidence_sha256=_sha("landmark-evidence"),
            source_package_sha256=_sha("source-package"),
            canonical_body_id="body-" + "a" * 32,
            closeup_png=_closeups(),
            candidate_bodyrig_revision="5" * 40,
        )


def test_candidate_rejects_boolean_v1_landmark_evidence() -> None:
    evidence = _evidence()
    evidence["version"] = True
    with pytest.raises(HandsFeetNailsLandmarkEvidenceError, match="format/version/identity mismatch"):
        apply_hfn_detail_to_avatar(
            _avatar(),
            evidence=evidence,
            evidence_sha256=_sha("landmark-evidence"),
            source_package_sha256=_sha("source-package"),
            canonical_body_id="body-" + "a" * 32,
            closeup_png=_closeups(),
            candidate_bodyrig_revision="5" * 40,
        )
