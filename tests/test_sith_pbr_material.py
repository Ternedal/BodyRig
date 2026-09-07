from __future__ import annotations

import hashlib
import inspect

import pytest

import bodyrig.bridges.sith_pbr_material as pbr_module
from bodyrig.bridges.sith_pbr_material import (
    PNG_SIGNATURE,
    PBR_METHOD,
    PBR_NORMAL_SCALE,
    PBR_ROUGHNESS_BASE,
    PBR_ROUGHNESS_DETAIL_GAIN,
    PBR_ROUGHNESS_MIN,
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
    return _write_glb(document, b"base" + b"thmb")


def metrics(normal: bytes, roughness: bytes) -> dict[str, float | str]:
    return {
        "method": PBR_METHOD,
        "normal_scale": PBR_NORMAL_SCALE,
        "roughness_min": PBR_ROUGHNESS_MIN,
        "roughness_max": 0.82,
        "roughness_mean": 0.72,
        "normal_texture_sha256": hashlib.sha256(normal).hexdigest(),
        "metallic_roughness_texture_sha256": hashlib.sha256(roughness).hexdigest(),
    }


def test_pbr_v2_does_not_turn_dark_or_saturated_albedo_into_gloss() -> None:
    source = inspect.getsource(pbr_module.derive_pbr_maps)

    assert PBR_METHOD == "source-basecolor-highpass-pbr-v2"
    assert PBR_NORMAL_SCALE == 0.25
    assert PBR_ROUGHNESS_BASE >= 0.68
    assert PBR_ROUGHNESS_DETAIL_GAIN > 0.0
    assert PBR_ROUGHNESS_MIN >= 0.64
    assert "saturation * darkness" not in source
    assert "PBR_ROUGHNESS_BASE + PBR_ROUGHNESS_DETAIL_GAIN * micro" in source
    assert "normal_strength = 6.0" in source


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
    assert material["normalTexture"] == {"index": 1, "scale": PBR_NORMAL_SCALE}
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
    assert binary.startswith(b"basethmb")
    assert binary.endswith(roughness)

    refinement = document["extras"]["bodyrig"]["materialRefinement"]
    assert refinement["method"] == PBR_METHOD
    assert refinement["normalScale"] == PBR_NORMAL_SCALE
    assert refinement["physicalMeasurement"] is False
    assert refinement["sourceDerivedHeuristic"] is True
    assert refinement["normalTextureSha256"] == hashlib.sha256(normal).hexdigest()
    assert refinement["metallicRoughnessTextureSha256"] == hashlib.sha256(roughness).hexdigest()


def test_pbr_refinement_rejects_stale_v1_receipt() -> None:
    normal = PNG_SIGNATURE + b"normal"
    roughness = PNG_SIGNATURE + b"roughness"
    stale = metrics(normal, roughness)
    stale["method"] = "source-basecolor-highpass-pbr-v1"

    with pytest.raises(PbrMaterialError, match="stale or unsupported"):
        refine_glb_pbr(
            base_avatar(),
            normal_png=normal,
            metallic_roughness_png=roughness,
            metrics=stale,
        )


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
    with pytest.raises(PbrMaterialError, match="PBR refinement"):
        refine_glb_pbr(
            refined,
            normal_png=normal,
            metallic_roughness_png=roughness,
            metrics=metrics(normal, roughness),
        )
