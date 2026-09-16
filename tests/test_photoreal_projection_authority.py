from __future__ import annotations

import copy
import json

import pytest

import bodyrig.photoreal_projection_authority as authority
from bodyrig.photoreal_projection_authority import (
    PhotorealProjectionAuthorityError,
    resolve_v2_projection_ambiguity,
)
from bodyrig.photoreal_scan_plan_cli import main as scan_plan_main


def _plan(
    *,
    projection: str = "projection-ambiguous-2to1",
    stereo_layout: str = "unknown",
) -> dict[str, object]:
    train = {
        "kind": "video",
        "source_id": "scene:s1:E:/video.mp4",
        "group_id": "scene:s1",
        "path": "E:/video.mp4",
        "information_score": 100.0,
        "projection": projection,
        "stereo_layout": stereo_layout,
        "width": 7680,
        "height": 3840,
        "duration_seconds": 60.0,
        "frame_rate": 60.0,
        "performer_count": 1,
        "source_binding": "scene-performer",
    }
    evaluation = copy.deepcopy(train)
    evaluation["source_id"] = "scene:s2:E:/evaluation.mp4"
    evaluation["group_id"] = "scene:s2"
    evaluation["path"] = "E:/evaluation.mp4"
    evaluation["projection"] = "flat"
    evaluation["stereo_layout"] = "mono"
    evaluation["width"] = 3840
    evaluation["height"] = 2160
    return {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "train": [train],
        "evaluation": [evaluation],
        "identity_bootstrap_policy": "train-only-single-performer-direct-binding-v1",
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _receipt(plan: dict[str, object]) -> dict[str, object]:
    sources = []
    for split in ("train", "evaluation"):
        for index, item in enumerate(plan[split]):
            sources.append(
                {
                    "kind": item["kind"],
                    "source_id": str(item["source_id"]).split(":", 2)[1],
                    "source_key": item["source_id"],
                    "resolved_path": f"/verified/{split}-{index}.mp4",
                    "sha256": ("a" if split == "train" else "b") * 64,
                }
            )
    return {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "sources": sources,
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _v2_equi(*, stereo_mode: str = "left-right") -> dict[str, object]:
    return {
        "probe_status": "parsed-isobmff",
        "st3d_present": True,
        "st3d_version": 0,
        "st3d_flags": 0,
        "stereo_mode": stereo_mode,
        "sv3d_present": True,
        "proj_present": True,
        "projection_type": "equi",
        "prhd_present": True,
        "prhd_version": 0,
        "prhd_flags": 0,
        "projection_data_version": 0,
        "projection_data_flags": 0,
        "equirectangular_bounds_valid": True,
    }


def test_resolves_exact_v2_equirectangular_and_unknown_stereo(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    calls: list[str] = []

    def probe(path):
        calls.append(str(path))
        return _v2_equi()

    monkeypatch.setattr(authority, "probe_isobmff_file", probe)
    resolved, count = resolve_v2_projection_ambiguity(plan, receipt)

    assert count == 1
    assert calls == ["/verified/train-0.mp4"]
    assert plan["train"][0]["projection"] == "projection-ambiguous-2to1"
    assert plan["train"][0]["stereo_layout"] == "unknown"
    assert resolved["train"][0]["projection"] == "equirectangular"
    assert resolved["train"][0]["stereo_layout"] == "side-by-side"
    assert resolved["evaluation"][0]["projection"] == "flat"
    assert resolved["teacher_training_authorized"] is False
    assert resolved["production_activation"] is False


def test_resolves_v2_top_bottom_to_over_under(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _v2_equi(stereo_mode="top-bottom"))
    resolved, count = resolve_v2_projection_ambiguity(plan, receipt)
    assert count == 1
    assert resolved["train"][0]["stereo_layout"] == "over-under"


def test_preserves_matching_explicit_stereo_and_cross_checks_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(stereo_layout="side-by-side")
    receipt = _receipt(plan)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _v2_equi(stereo_mode="left-right"))
    resolved, count = resolve_v2_projection_ambiguity(plan, receipt)
    assert count == 1
    assert resolved["train"][0]["stereo_layout"] == "side-by-side"
    assert plan["train"][0]["stereo_layout"] == "side-by-side"


def test_preserves_explicit_stereo_when_st3d_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(stereo_layout="side-by-side")
    receipt = _receipt(plan)
    probe = _v2_equi()
    probe["st3d_present"] = False
    probe["stereo_mode"] = None
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: probe)
    resolved, count = resolve_v2_projection_ambiguity(plan, receipt)
    assert count == 1
    assert resolved["train"][0]["stereo_layout"] == "side-by-side"


def test_rejects_explicit_stereo_conflicting_with_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(stereo_layout="side-by-side")
    receipt = _receipt(plan)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _v2_equi(stereo_mode="top-bottom"))
    with pytest.raises(PhotorealProjectionAuthorityError, match="conflicts"):
        resolve_v2_projection_ambiguity(plan, receipt)


@pytest.mark.parametrize("stereo_mode", ["right-left", "stereo-custom", "reserved-or-unknown"])
def test_refuses_unrepresentable_v2_stereo_modes(monkeypatch: pytest.MonkeyPatch, stereo_mode: str) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _v2_equi(stereo_mode=stereo_mode))
    with pytest.raises(PhotorealProjectionAuthorityError, match="unsupported Spherical V2 stereo mode"):
        resolve_v2_projection_ambiguity(plan, receipt)


@pytest.mark.parametrize("patch", [{"st3d_version": 1}, {"st3d_flags": 1}])
def test_refuses_unsupported_st3d_semantics(monkeypatch: pytest.MonkeyPatch, patch: dict[str, object]) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    probe = _v2_equi()
    probe.update(patch)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: probe)
    with pytest.raises(PhotorealProjectionAuthorityError, match="stereo box semantics"):
        resolve_v2_projection_ambiguity(plan, receipt)


def test_unknown_stereo_requires_st3d_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    probe = _v2_equi()
    probe["st3d_present"] = False
    probe["stereo_mode"] = None
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: probe)
    with pytest.raises(PhotorealProjectionAuthorityError, match="no authoritative Spherical V2 st3d"):
        resolve_v2_projection_ambiguity(plan, receipt)


@pytest.mark.parametrize(
    "probe_patch",
    [
        {"sv3d_present": False, "spherical_v1_present": True, "spherical_v1_parse_status": "valid-v1-equirectangular"},
        {"projection_type": "mshp"},
        {"projection_type": "cbmp"},
        {"projection_type": "multiple"},
        {"equirectangular_bounds_valid": False},
        {"prhd_present": False},
        {"projection_data_version": 1},
        {"projection_data_flags": 1},
    ],
)
def test_refuses_non_authoritative_or_unsupported_projection_metadata(
    monkeypatch: pytest.MonkeyPatch,
    probe_patch: dict[str, object],
) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    probe = _v2_equi()
    probe.update(probe_patch)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: probe)
    with pytest.raises(PhotorealProjectionAuthorityError):
        resolve_v2_projection_ambiguity(plan, receipt)


def test_mesh_and_cubemap_are_not_relabelled_as_vr180_or_vr360(monkeypatch: pytest.MonkeyPatch) -> None:
    for projection_type in ("mshp", "cbmp"):
        plan = _plan()
        receipt = _receipt(plan)
        probe = _v2_equi()
        probe["projection_type"] = projection_type
        monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path, value=probe: value)
        with pytest.raises(PhotorealProjectionAuthorityError, match="not uniquely Spherical V2 equirectangular"):
            resolve_v2_projection_ambiguity(plan, receipt)
        assert plan["train"][0]["projection"] == "projection-ambiguous-2to1"


@pytest.mark.parametrize("probe_status", ["unsupported-container", "parse-failed"])
def test_refuses_container_without_parsed_v2_authority(monkeypatch: pytest.MonkeyPatch, probe_status: str) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: {"probe_status": probe_status})
    with pytest.raises(PhotorealProjectionAuthorityError):
        resolve_v2_projection_ambiguity(plan, receipt)


def test_non_ambiguous_sources_never_use_metadata_as_override(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(projection="flat", stereo_layout="mono")
    receipt = _receipt(plan)

    def fail_if_called(_path):
        raise AssertionError("metadata probe must not override an already authoritative projection")

    monkeypatch.setattr(authority, "probe_isobmff_file", fail_if_called)
    resolved, count = resolve_v2_projection_ambiguity(plan, receipt)
    assert count == 0
    assert resolved == plan


def test_receipt_universe_mismatch_fails_before_projection_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    receipt["sources"].pop()
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _v2_equi())
    with pytest.raises(PhotorealProjectionAuthorityError, match="source universe mismatch"):
        resolve_v2_projection_ambiguity(plan, receipt)


def test_scan_plan_cli_uses_v2_projection_and_stereo_resolution_but_keeps_spatial_deprojection_block(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _v2_equi())
    plan_path = tmp_path / "dataset-plan.json"
    receipt_path = tmp_path / "source-receipt.json"
    output_path = tmp_path / "scan-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    assert scan_plan_main(["--plan", str(plan_path), "--receipt", str(receipt_path), "--out", str(output_path)]) == 0
    scan = json.loads(output_path.read_text(encoding="utf-8"))
    source = next(item for item in scan["sources"] if item["source_key"].startswith("scene:s1:"))
    assert source["projection"] == "equirectangular"
    assert source["stereo_layout"] == "side-by-side"
    assert source["decode_mode"] == "spatial-deprojection-required"
    assert source["sample_count"] == 24
    assert {item["eye"] for item in source["samples"]} == {"left", "right"}
    assert source["identity_bootstrap_eligible"] is False
    assert scan["teacher_training_authorized"] is False
    assert scan["production_activation"] is False
