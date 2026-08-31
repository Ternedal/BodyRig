from __future__ import annotations

import hashlib

import pytest

from bodyrig.bridges.sith_pbr_material import (
    PNG_SIGNATURE,
    PbrMaterialError,
    _read_glb,
    _write_glb,
    refine_glb_pbr,
)


def base_avatar() -> bytes:
    document = {
        "asset": {"version": "2.0"},
        "extensionsUsed": ["VRMC_vrm"],
        "extensionsRequired": ["VRMC_vrm"],
        "extensions": {
            "VRMC_vrm": {
                "specVersion": "1.0",
                "meta": {"thumbnailImage": 1},
                "humanoid": {"humanBones": {}},
            }
        },
        "materials": [{
            "name": "BodyRigSourceDerivedMaterial",
            "doubleSided": True,
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0.0,
                "roughnessFactor": 0.9,
            },
        }],
        "samplers": [{"magFilter": 9729}],
        "images": [
            {"name": "BodyRigAvatarTexture", "bufferView": 0, "mimeType": "image/png"},
            {"name": "BodyRigThumbnail", "bufferView": 1, "mimeType": "image/png"},
        ],
        "textures": [{"sampler": 0, "source": 0}],
        "buffers": [{"byteLength": 8}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 4},
            {"buffer": 0, "byteOffset": 4, "byteLength": 4},
        ],
        "extras": {"bodyrig": {"placeholder": False}},
    }
    return _write_glb(document, b"base" + b"thumb")


def metrics(normal: bytes, roughness: bytes) -> dict[str, float | str]:
    return {
        "method": "source-basecolor-highpass-pbr-v1",
        "normal_scale": 0.45,
        "roughness_min": 0.46,
        "roughness_max": 0.82,
        "roughness_mean": 0.69,
        "normal_texture_sha256": hashlib.sha256(normal).hexdigest(),
        "metallic_roughness_texture_sha256": hashlib.sha256(roughness).hexdigest(),
    }


def test_pbr_refinement_preserves_source_base_color_and_thumbnail_index() -> None:
    normal = PNG_SIGNATURE + b"normal"
    roughness = PNG_SIGNATURE + b"roughness"
    refined = refine_glb_pbr(
        base_avatar(),
        normal_png=normal,
        metallic_roughness_png=roughness,
        metrics=metrics(normal, roughness),
    )
    document, binary = _read_glb(refined)

    material = document["materials"][0]
    pbr = material["pbrMetallicRoughness"]
    assert pbr["baseColorTexture"] == {"index": 0}
    assert pbr["metallicFactor"] == 0.0
    assert pbr["roughnessFactor"] == 1.0
    assert pbr["metallicRoughnessTexture"] == {"index": 2}
    assert material["normalTexture"] == {"index": 1, "scale": 0.45}
    assert document["extensions"]["VRMC_vrm"]["meta"]["thumbnailImage"] == 1
    assert [image["name"] for image in document["images"]] == [
        "BodyRigAvatarTexture",
        "BodyRigThumbnail",
        "BodyRigSourceDerivedNormal",
        "BodyRigSourceDerivedMetallicRoughness",
    ]
    assert document["textures"] == [
        {"sampler": 0, "source": 0},
        {"sampler": 0, "source": 2},
        {"sampler": 0, "source": 3},
    ]
    assert binary.endswith(roughness)

    refinement = document["extras"]["bodyrig"]["materialRefinement"]
    assert refinement["physicalMeasurement"] is False
    assert refinement["sourceDerivedHeuristic"] is True
    assert refinement["normalTextureSha256"] == hashlib.sha256(normal).hexdigest()
    assert refinement["metallicRoughnessTextureSha256"] == hashlib.sha256(roughness).hexdigest()


def test_pbr_refinement_rejects_hash_mismatch_and_double_application() -> None:
    normal = PNG_SIGNATURE + b"normal"
    roughness = PNG_SIGNATURE + b"roughness"
    bad_metrics = metrics(normal, roughness)
    bad_metrics["normal_texture_sha256"] = "0" * 64
    with pytest.raises(PbrMaterialError, match="hashes"):
        refine_glb_pbr(
            base_avatar(),
            normal_png=normal,
            metallic_roughness_png=roughness,
            metrics=bad_metrics,
        )

    refined = refine_glb_pbr(
        base_avatar(),
        normal_png=normal,
        metallic_roughness_png=roughness,
        metrics=metrics(normal, roughness),
    )
    with pytest.raises(PbrMaterialError, match="already PBR-refined"):
        refine_glb_pbr(
            refined,
            normal_png=normal,
            metallic_roughness_png=roughness,
            metrics=metrics(normal, roughness),
        )
