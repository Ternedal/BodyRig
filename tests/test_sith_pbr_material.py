from __future__ import annotations

import hashlib
import math

import numpy as np
import pytest

from bodyrig.bridges.sith_pbr_material import (
    PNG_SIGNATURE,
    PBR_COLOR_TRANSFER,
    PBR_METHOD,
    PBR_NORMAL_SCALE,
    PBR_ROUGHNESS_BASE,
    PBR_ROUGHNESS_DETAIL_GAIN,
    PBR_ROUGHNESS_MAX,
    PBR_ROUGHNESS_MIN,
    PbrMaterialError,
    _encode_rgb_png,
    _read_glb,
    _roughness_from_detail,
    _srgb_to_linear,
    _write_glb,
    derive_pbr_maps,
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
        "base_color_transfer": PBR_COLOR_TRANSFER,
        "normal_scale": PBR_NORMAL_SCALE,
        "roughness_min": PBR_ROUGHNESS_MIN,
        "roughness_max": PBR_ROUGHNESS_MAX,
        "roughness_mean": 0.72,
        "normal_texture_sha256": hashlib.sha256(normal).hexdigest(),
        "metallic_roughness_texture_sha256": hashlib.sha256(roughness).hexdigest(),
    }


class ScalarNp:
    @staticmethod
    def abs(value: float) -> float:
        return abs(value)

    @staticmethod
    def clip(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))


def test_pbr_v3_roughness_policy_uses_only_local_detail_and_never_adds_gloss() -> None:
    assert PBR_METHOD == "source-basecolor-linear-highpass-pbr-v3"
    assert PBR_COLOR_TRANSFER == "srgb-eotf-linear-light"
    assert PBR_NORMAL_SCALE == 0.25
    assert PBR_ROUGHNESS_BASE >= 0.68
    assert PBR_ROUGHNESS_DETAIL_GAIN > 0.0
    assert PBR_ROUGHNESS_MIN >= 0.64

    flat = _roughness_from_detail(ScalarNp, 0.0)
    positive_detail = _roughness_from_detail(ScalarNp, 0.12)
    negative_detail = _roughness_from_detail(ScalarNp, -0.12)
    extreme_detail = _roughness_from_detail(ScalarNp, 99.0)

    assert flat == pytest.approx(PBR_ROUGHNESS_BASE)
    assert positive_detail == pytest.approx(PBR_ROUGHNESS_BASE + PBR_ROUGHNESS_DETAIL_GAIN)
    assert negative_detail == pytest.approx(positive_detail)
    assert extreme_detail >= flat
    assert PBR_ROUGHNESS_MIN <= flat <= positive_detail <= extreme_detail <= PBR_ROUGHNESS_MAX


def test_pbr_v3_decodes_srgb_before_dark_detail_extraction() -> None:
    encoded = np.asarray([0.05, 0.10, 0.20, 0.50, 1.0], dtype=np.float32)
    linear = _srgb_to_linear(np, encoded)

    assert linear[-1] == pytest.approx(1.0)
    assert linear[0] < encoded[0]
    assert linear[1] < encoded[1]
    assert (linear[2] - linear[1]) < 0.03
    assert (encoded[2] - encoded[1]) / (linear[2] - linear[1]) > 4.0

    image = np.full((5, 5, 3), 51, dtype=np.uint8)
    image[2, 2, :] = 26
    normal, roughness, derived = derive_pbr_maps(np, _encode_rgb_png(np, image))
    assert normal.startswith(PNG_SIGNATURE)
    assert roughness.startswith(PNG_SIGNATURE)
    assert derived["method"] == PBR_METHOD
    assert derived["base_color_transfer"] == PBR_COLOR_TRANSFER
    assert float(derived["roughness_max"]) < 0.71


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
    assert refinement["baseColorTransfer"] == PBR_COLOR_TRANSFER
    assert refinement["normalScale"] == PBR_NORMAL_SCALE
    assert refinement["physicalMeasurement"] is False
    assert refinement["sourceDerivedHeuristic"] is True
    assert refinement["normalTextureSha256"] == hashlib.sha256(normal).hexdigest()
    assert refinement["metallicRoughnessTextureSha256"] == hashlib.sha256(roughness).hexdigest()


def test_pbr_refinement_rejects_stale_or_noncanonical_v3_receipt() -> None:
    normal = PNG_SIGNATURE + b"normal"
    roughness = PNG_SIGNATURE + b"roughness"

    stale = metrics(normal, roughness)
    stale["method"] = "source-basecolor-highpass-pbr-v2"
    with pytest.raises(PbrMaterialError, match="stale or unsupported"):
        refine_glb_pbr(
            base_avatar(),
            normal_png=normal,
            metallic_roughness_png=roughness,
            metrics=stale,
        )

    wrong_transfer = metrics(normal, roughness)
    wrong_transfer["base_color_transfer"] = "encoded-srgb"
    with pytest.raises(PbrMaterialError, match="base-color transfer"):
        refine_glb_pbr(
            base_avatar(),
            normal_png=normal,
            metallic_roughness_png=roughness,
            metrics=wrong_transfer,
        )

    wrong_scale = metrics(normal, roughness)
    wrong_scale["normal_scale"] = 1.0
    with pytest.raises(PbrMaterialError, match="normal scale does not match canonical v3"):
        refine_glb_pbr(
            base_avatar(),
            normal_png=normal,
            metallic_roughness_png=roughness,
            metrics=wrong_scale,
        )

    extra_field = metrics(normal, roughness)
    extra_field["unreviewed_override"] = 1.0
    with pytest.raises(PbrMaterialError, match="fields do not match canonical v3"):
        refine_glb_pbr(
            base_avatar(),
            normal_png=normal,
            metallic_roughness_png=roughness,
            metrics=extra_field,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("roughness_min", math.nan, "must be finite"),
        ("roughness_mean", math.inf, "must be finite"),
        ("roughness_min", 0.9, "bounds or order"),
        ("roughness_mean", 0.9, "bounds or order"),
        ("roughness_max", 0.60, "bounds or order"),
    ],
)
def test_pbr_refinement_rejects_nonfinite_or_out_of_order_roughness_metrics(
    field: str,
    value: float,
    message: str,
) -> None:
    normal = PNG_SIGNATURE + b"normal"
    roughness = PNG_SIGNATURE + b"roughness"
    invalid = metrics(normal, roughness)
    invalid[field] = value

    with pytest.raises(PbrMaterialError, match=message):
        refine_glb_pbr(
            base_avatar(),
            normal_png=normal,
            metallic_roughness_png=roughness,
            metrics=invalid,
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
