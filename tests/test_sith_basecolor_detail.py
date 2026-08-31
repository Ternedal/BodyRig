from __future__ import annotations

import hashlib

import pytest

from bodyrig.bridges.sith_basecolor_detail import (
    BaseColorDetailError,
    METHOD,
    refine_glb_basecolor,
)
from bodyrig.bridges.sith_pbr_material import (
    PNG_SIGNATURE,
    _read_glb,
    _write_glb,
    refine_glb_pbr,
)


def _base_avatar() -> bytes:
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


def _pbr_avatar() -> bytes:
    normal = PNG_SIGNATURE + b"normal"
    roughness = PNG_SIGNATURE + b"roughness"
    metrics = {
        "method": "source-basecolor-highpass-pbr-v1",
        "normal_scale": 0.45,
        "roughness_min": 0.46,
        "roughness_max": 0.82,
        "roughness_mean": 0.69,
        "normal_texture_sha256": hashlib.sha256(normal).hexdigest(),
        "metallic_roughness_texture_sha256": hashlib.sha256(roughness).hexdigest(),
    }
    return refine_glb_pbr(
        _base_avatar(),
        normal_png=normal,
        metallic_roughness_png=roughness,
        metrics=metrics,
    )


def _detail_metrics(refined: bytes, *, source: bytes = b"base") -> dict[str, object]:
    return {
        "method": METHOD,
        "detail_strength": 0.45,
        "channel_delta_cap": 0.035,
        "max_observed_channel_delta": 0.031,
        "mean_abs_channel_delta": 0.006,
        "changed_pixel_fraction": 0.62,
        "source_basecolor_sha256": hashlib.sha256(source).hexdigest(),
        "refined_basecolor_sha256": hashlib.sha256(refined).hexdigest(),
        "source_derived": True,
        "generative": False,
    }


def test_basecolor_refinement_preserves_texture_indices_and_pbr_maps() -> None:
    refined_png = PNG_SIGNATURE + b"bounded-detail"
    avatar = refine_glb_basecolor(
        _pbr_avatar(),
        refined_basecolor_png=refined_png,
        metrics=_detail_metrics(refined_png),
    )
    document, binary = _read_glb(avatar)

    assert document["textures"] == [
        {"sampler": 0, "source": 0},
        {"sampler": 0, "source": 2},
        {"sampler": 0, "source": 3},
    ]
    assert document["extensions"]["VRMC_vrm"]["meta"]["thumbnailImage"] == 1
    assert document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] == {"index": 0}
    assert document["materials"][0]["normalTexture"] == {"index": 1, "scale": 0.45}
    assert document["images"][0]["name"] == "BodyRigSourceDerivedBaseColorDetail"
    assert binary.startswith(b"basethmb")
    assert binary.endswith(refined_png)

    detail = document["extras"]["bodyrig"]["baseColorDetailRefinement"]
    assert detail["sourceDerived"] is True
    assert detail["generative"] is False
    assert detail["sourceBaseColorSha256"] == hashlib.sha256(b"base").hexdigest()
    assert detail["refinedBaseColorSha256"] == hashlib.sha256(refined_png).hexdigest()
    assert detail["maxObservedChannelDelta"] == pytest.approx(0.031)


def test_basecolor_refinement_rejects_wrong_source_hash() -> None:
    refined_png = PNG_SIGNATURE + b"bounded-detail"
    with pytest.raises(BaseColorDetailError, match="exact source texture"):
        refine_glb_basecolor(
            _pbr_avatar(),
            refined_basecolor_png=refined_png,
            metrics=_detail_metrics(refined_png, source=b"wrong"),
        )


def test_basecolor_refinement_rejects_metric_over_cap_and_double_application() -> None:
    refined_png = PNG_SIGNATURE + b"bounded-detail"
    bad = _detail_metrics(refined_png)
    bad["max_observed_channel_delta"] = 0.06
    with pytest.raises(BaseColorDetailError, match="declared channel delta cap"):
        refine_glb_basecolor(_pbr_avatar(), refined_basecolor_png=refined_png, metrics=bad)

    refined = refine_glb_basecolor(
        _pbr_avatar(),
        refined_basecolor_png=refined_png,
        metrics=_detail_metrics(refined_png),
    )
    with pytest.raises(BaseColorDetailError, match="already present"):
        refine_glb_basecolor(
            refined,
            refined_basecolor_png=refined_png,
            metrics=_detail_metrics(refined_png),
        )
