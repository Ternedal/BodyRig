from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_identity_bootstrap import (
    PhotorealIdentityBootstrapError,
    build_identity_bootstrap_plan,
)


def _source(
    key: str,
    group: str,
    *,
    kind: str,
    split: str,
    performer_count: int,
    source_binding: str,
    eligible: bool,
    stereo: bool = False,
    spatial: bool = False,
) -> dict[str, object]:
    if kind == "image":
        samples = [{"timestamp_seconds": None, "eye": "mono"}]
        projection = "flat"
        stereo_layout = "mono"
        decode_mode = "image-direct"
    else:
        projection = "vr180" if spatial else "flat"
        stereo_layout = "side-by-side" if stereo else "mono"
        decode_mode = (
            "spatial-deprojection-required"
            if spatial
            else "rectilinear-stereo-split"
            if stereo
            else "rectilinear-mono"
        )
        eyes = ("left", "right") if stereo else ("mono",)
        samples = [
            {"timestamp_seconds": float(index + 1), "eye": eye}
            for index in range(20)
            for eye in eyes
        ]
    return {
        "source_key": key,
        "source_sha256": ("a" if kind == "video" else "b") * 64,
        "resolved_path": rf"\\stash\verified\{group.replace(':', '-')}.bin",
        "kind": kind,
        "split": split,
        "group_id": group,
        "source_binding": source_binding,
        "performer_count": performer_count,
        "projection": projection,
        "stereo_layout": stereo_layout,
        "decode_mode": decode_mode,
        "sample_count": len(samples),
        "samples": samples,
        "identity_bootstrap_eligible": eligible,
    }


def _scan_plan() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-scan-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "identity_bootstrap_policy": "train-only-single-performer-direct-binding-v1",
        "sources": [
            _source(
                "scene:s1:E:/single.mp4",
                "scene:s1",
                kind="video",
                split="train",
                performer_count=1,
                source_binding="scene-performer",
                eligible=True,
                stereo=True,
            ),
            _source(
                "scene:s-vr:E:/spatial.mp4",
                "scene:s-vr",
                kind="video",
                split="train",
                performer_count=1,
                source_binding="scene-performer",
                eligible=False,
                stereo=True,
                spatial=True,
            ),
            _source(
                "image:i1:F:/portrait.jpg",
                "image:i1",
                kind="image",
                split="train",
                performer_count=1,
                source_binding="direct-performer",
                eligible=True,
            ),
            _source(
                "scene:s2:E:/multi.mp4",
                "scene:s2",
                kind="video",
                split="train",
                performer_count=2,
                source_binding="scene-performer",
                eligible=False,
            ),
            _source(
                "image:i2:F:/gallery.jpg",
                "gallery:g1",
                kind="image",
                split="train",
                performer_count=1,
                source_binding="performer-gallery",
                eligible=False,
            ),
            _source(
                "scene:s-eval:E:/eval.mp4",
                "scene:s-eval",
                kind="video",
                split="evaluation",
                performer_count=1,
                source_binding="scene-performer",
                eligible=False,
            ),
        ],
        "all_sources_sha256_bound": True,
        "train_evaluation_assignment_inherited": True,
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def test_identity_bootstrap_uses_only_authoritative_train_sources() -> None:
    result = build_identity_bootstrap_plan(_scan_plan())

    assert result["source_count"] == 2
    assert result["source_group_count"] == 2
    assert result["train_only"] is True
    assert result["evaluation_source_count"] == 0
    assert result["identity_bank_build_authorized"] is True
    assert result["teacher_training_authorized"] is False
    assert result["production_activation"] is False
    assert {item["source_key"] for item in result["sources"]} == {
        "scene:s1:E:/single.mp4",
        "image:i1:F:/portrait.jpg",
    }


def test_identity_bootstrap_uses_full_bounded_scout_pool_and_preserves_both_stereo_eyes() -> None:
    result = build_identity_bootstrap_plan(_scan_plan())
    video = next(item for item in result["sources"] if item["kind"] == "video")

    assert video["decode_mode"] == "rectilinear-stereo-split"
    assert video["reference_sample_count"] == 40
    assert {item["eye"] for item in video["reference_samples"]} == {"left", "right"}
    assert all(item["timestamp_seconds"] is not None for item in video["reference_samples"])


def test_identity_bootstrap_caps_large_stereo_candidate_pool_at_120() -> None:
    plan = _scan_plan()
    video = next(item for item in plan["sources"] if item["source_key"] == "scene:s1:E:/single.mp4")
    video["samples"] = [
        {"timestamp_seconds": float(index + 1), "eye": eye}
        for index in range(150)
        for eye in ("left", "right")
    ]
    video["sample_count"] = len(video["samples"])

    result = build_identity_bootstrap_plan(plan)
    selected = next(item for item in result["sources"] if item["source_key"] == video["source_key"])

    assert selected["reference_sample_count"] == 120
    assert sum(1 for item in selected["reference_samples"] if item["eye"] == "left") == 60
    assert sum(1 for item in selected["reference_samples"] if item["eye"] == "right") == 60


def test_identity_bootstrap_excludes_spatial_deprojection_sources() -> None:
    result = build_identity_bootstrap_plan(_scan_plan())

    assert all(item["decode_mode"] != "spatial-deprojection-required" for item in result["sources"])
    assert all(item["source_key"] != "scene:s-vr:E:/spatial.mp4" for item in result["sources"])


def test_identity_bootstrap_rejects_spatial_source_marked_eligible() -> None:
    plan = copy.deepcopy(_scan_plan())
    spatial = next(item for item in plan["sources"] if item["decode_mode"] == "spatial-deprojection-required")
    spatial["identity_bootstrap_eligible"] = True

    with pytest.raises(PhotorealIdentityBootstrapError, match="eligibility disagrees"):
        build_identity_bootstrap_plan(plan)


def test_identity_bootstrap_rejects_eval_source_marked_eligible() -> None:
    plan = copy.deepcopy(_scan_plan())
    eval_source = next(item for item in plan["sources"] if item["split"] == "evaluation")
    eval_source["identity_bootstrap_eligible"] = True

    with pytest.raises(PhotorealIdentityBootstrapError, match="eligibility disagrees"):
        build_identity_bootstrap_plan(plan)


def test_identity_bootstrap_rejects_gallery_only_reference_authority() -> None:
    plan = copy.deepcopy(_scan_plan())
    gallery = next(item for item in plan["sources"] if item["source_binding"] == "performer-gallery")
    gallery["identity_bootstrap_eligible"] = True

    with pytest.raises(PhotorealIdentityBootstrapError, match="eligibility disagrees"):
        build_identity_bootstrap_plan(plan)


def test_identity_bootstrap_requires_two_independent_authoritative_groups() -> None:
    plan = copy.deepcopy(_scan_plan())
    direct_image = next(item for item in plan["sources"] if item["source_key"].startswith("image:i1:"))
    direct_image["performer_count"] = 2
    direct_image["identity_bootstrap_eligible"] = False

    with pytest.raises(PhotorealIdentityBootstrapError, match="independent authoritative train groups"):
        build_identity_bootstrap_plan(plan)


def test_identity_bootstrap_rejects_authority_boundary_crossing() -> None:
    plan = copy.deepcopy(_scan_plan())
    plan["production_activation"] = True

    with pytest.raises(PhotorealIdentityBootstrapError, match="production authority"):
        build_identity_bootstrap_plan(plan)


def test_identity_bootstrap_accepts_authorized_equi_spatial_source() -> None:
    plan = copy.deepcopy(_scan_plan())
    spatial = next(item for item in plan["sources"] if item["decode_mode"] == "spatial-deprojection-required")
    spatial["projection"] = "equi"
    spatial["projection_authority"] = {
        "format": "bodyrig-explicit-projection-authority",
        "version": 1,
        "projection_type": "equi",
        "deprojection_authority": False,
    }
    spatial["identity_bootstrap_eligible"] = True

    result = build_identity_bootstrap_plan(plan)
    selected = next(item for item in result["sources"] if item["source_key"] == spatial["source_key"])

    assert selected["decode_mode"] == "spatial-deprojection-required"
    assert selected["projection"] == "equi"
    assert selected["projection_authority"] == spatial["projection_authority"]
    assert selected["reference_sample_count"] == 40
    assert {sample["eye"] for sample in selected["reference_samples"]} == {"left", "right"}


def test_identity_bootstrap_distributes_aggregate_budget_across_many_sources() -> None:
    plan = _scan_plan()
    template = next(item for item in plan["sources"] if item["source_key"] == "scene:s1:E:/single.mp4")
    sources = []
    for index in range(4):
        source = copy.deepcopy(template)
        source["source_key"] = f"scene:b{index}:E:/budget-{index}.mp4"
        source["group_id"] = f"scene:b{index}"
        source["source_sha256"] = format(index + 1, "x") * 64
        source["samples"] = [
            {"timestamp_seconds": float(sample + 1), "eye": eye}
            for sample in range(100)
            for eye in ("left", "right")
        ]
        source["sample_count"] = len(source["samples"])
        sources.append(source)
    plan["sources"] = sources

    result = build_identity_bootstrap_plan(plan)

    assert result["source_count"] == 4
    assert result["reference_sample_count"] == 320
    assert {item["reference_sample_count"] for item in result["sources"]} == {80}
    for item in result["sources"]:
        assert sum(1 for sample in item["reference_samples"] if sample["eye"] == "left") == 40
        assert sum(1 for sample in item["reference_samples"] if sample["eye"] == "right") == 40
