from __future__ import annotations

import copy
import json

import pytest

import bodyrig.photoreal_projection_authority as authority
from bodyrig.photoreal_projection_authority import PhotorealProjectionAuthorityError, resolve_v2_projection_ambiguity
from bodyrig.photoreal_scan_plan_cli import main as scan_plan_main


def _plan(*, projection: str = "projection-ambiguous-2to1", stereo_layout: str = "unknown") -> dict[str, object]:
    train = {
        "kind": "video", "source_id": "scene:s1:E:/video.mp4", "group_id": "scene:s1",
        "path": "E:/video.mp4", "information_score": 100.0, "projection": projection,
        "stereo_layout": stereo_layout, "width": 7680, "height": 3840, "duration_seconds": 60.0,
        "frame_rate": 60.0, "performer_count": 1, "source_binding": "scene-performer",
    }
    evaluation = copy.deepcopy(train)
    evaluation.update({
        "source_id": "scene:s2:E:/evaluation.mp4", "group_id": "scene:s2", "path": "E:/evaluation.mp4",
        "projection": "flat", "stereo_layout": "mono", "width": 3840, "height": 2160,
    })
    return {
        "format": "bodyrig-photoreal-dataset-plan", "version": 1, "performer_id": "42",
        "performer_name": "Performer 42", "train": [train], "evaluation": [evaluation],
        "identity_bootstrap_policy": "train-only-single-performer-direct-binding-v1",
        "teacher_training_authorized": False, "build_only": True, "runtime_dependency": False,
        "production_activation": False,
    }


def _receipt(plan: dict[str, object]) -> dict[str, object]:
    sources = []
    for split in ("train", "evaluation"):
        for index, item in enumerate(plan[split]):
            sources.append({
                "kind": item["kind"], "source_id": str(item["source_id"]).split(":", 2)[1],
                "source_key": item["source_id"], "resolved_path": f"/verified/{split}-{index}.mp4",
                "sha256": ("a" if split == "train" else "b") * 64,
            })
    return {
        "format": "bodyrig-photoreal-source-receipt", "version": 1, "performer_id": "42",
        "sources": sources, "all_sources_readable": True, "all_sources_sha256_bound": True,
        "source_keys_path_specific": True, "build_only": True, "runtime_dependency": False,
        "production_activation": False,
    }


def _v2_equi(*, stereo_mode: str = "left-right") -> dict[str, object]:
    return {
        "probe_status": "parsed-isobmff", "st3d_present": True, "st3d_version": 0, "st3d_flags": 0,
        "stereo_mode": stereo_mode, "sv3d_present": True, "proj_present": True, "projection_type": "equi",
        "prhd_present": True, "prhd_version": 0, "prhd_flags": 0, "projection_data_version": 0,
        "projection_data_flags": 0, "equirectangular_bounds_valid": True,
    }


def test_resolves_exact_v2_equirectangular_and_unknown_stereo(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(); receipt = _receipt(plan); calls: list[str] = []
    def probe(path): calls.append(str(path)); return _v2_equi()
    monkeypatch.setattr(authority, "probe_isobmff_file", probe)
    resolved, count = resolve_v2_projection_ambiguity(plan, receipt)
    assert count == 1 and calls == ["/verified/train-0.mp4"]
    assert plan["train"][0]["projection"] == "projection-ambiguous-2to1"
    assert plan["train"][0]["stereo_layout"] == "unknown"
    assert resolved["train"][0]["projection"] == "equirectangular"
    assert resolved["train"][0]["stereo_layout"] == "side-by-side"
    assert resolved["teacher_training_authorized"] is False and resolved["production_activation"] is False


def test_resolves_top_bottom_and_preserves_matching_explicit_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(); receipt = _receipt(plan)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _v2_equi(stereo_mode="top-bottom"))
    resolved, _ = resolve_v2_projection_ambiguity(plan, receipt)
    assert resolved["train"][0]["stereo_layout"] == "over-under"

    plan = _plan(stereo_layout="side-by-side"); receipt = _receipt(plan)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _v2_equi())
    resolved, _ = resolve_v2_projection_ambiguity(plan, receipt)
    assert resolved["train"][0]["stereo_layout"] == "side-by-side"


def test_preserves_explicit_layout_without_st3d(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(stereo_layout="side-by-side"); receipt = _receipt(plan); probe = _v2_equi()
    probe.update({"st3d_present": False, "stereo_mode": None})
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: probe)
    resolved, _ = resolve_v2_projection_ambiguity(plan, receipt)
    assert resolved["train"][0]["stereo_layout"] == "side-by-side"


def test_rejects_conflicting_explicit_stereo(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(stereo_layout="side-by-side"); receipt = _receipt(plan)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _v2_equi(stereo_mode="top-bottom"))
    with pytest.raises(PhotorealProjectionAuthorityError, match="conflicts"):
        resolve_v2_projection_ambiguity(plan, receipt)


@pytest.mark.parametrize("stereo_mode", ["right-left", "stereo-custom", "reserved-or-unknown"])
def test_refuses_unrepresentable_v2_stereo_modes(monkeypatch: pytest.MonkeyPatch, stereo_mode: str) -> None:
    plan = _plan(); receipt = _receipt(plan)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _v2_equi(stereo_mode=stereo_mode))
    with pytest.raises(PhotorealProjectionAuthorityError, match="unsupported Spherical V2 stereo mode"):
        resolve_v2_projection_ambiguity(plan, receipt)


@pytest.mark.parametrize("patch", [{"st3d_version": 1}, {"st3d_flags": 1}])
def test_refuses_unsupported_st3d_semantics(monkeypatch: pytest.MonkeyPatch, patch: dict[str, object]) -> None:
    plan = _plan(); receipt = _receipt(plan); probe = _v2_equi(); probe.update(patch)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: probe)
    with pytest.raises(PhotorealProjectionAuthorityError, match="stereo box semantics"):
        resolve_v2_projection_ambiguity(plan, receipt)


def test_unknown_stereo_requires_st3d(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(); receipt = _receipt(plan); probe = _v2_equi(); probe.update({"st3d_present": False, "stereo_mode": None})
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: probe)
    with pytest.raises(PhotorealProjectionAuthorityError, match="no authoritative Spherical V2 st3d"):
        resolve_v2_projection_ambiguity(plan, receipt)


@pytest.mark.parametrize("probe_patch", [
    {"sv3d_present": False, "spherical_v1_present": True}, {"projection_type": "mshp"},
    {"projection_type": "cbmp"}, {"projection_type": "multiple"}, {"equirectangular_bounds_valid": False},
    {"prhd_present": False}, {"projection_data_version": 1}, {"projection_data_flags": 1},
])
def test_refuses_non_authoritative_or_unsupported_projection_metadata(monkeypatch: pytest.MonkeyPatch, probe_patch: dict[str, object]) -> None:
    plan = _plan(); receipt = _receipt(plan); probe = _v2_equi(); probe.update(probe_patch)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: probe)
    with pytest.raises(PhotorealProjectionAuthorityError):
        resolve_v2_projection_ambiguity(plan, receipt)


def test_non_ambiguous_source_is_not_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(projection="flat", stereo_layout="mono"); receipt = _receipt(plan)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: (_ for _ in ()).throw(AssertionError("probe called")))
    resolved, count = resolve_v2_projection_ambiguity(plan, receipt)
    assert count == 0 and resolved == plan


def test_receipt_universe_mismatch_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(); receipt = _receipt(plan); receipt["sources"].pop()
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _v2_equi())
    with pytest.raises(PhotorealProjectionAuthorityError, match="source universe mismatch"):
        resolve_v2_projection_ambiguity(plan, receipt)


def test_scan_plan_cli_resolves_projection_and_stereo_without_granting_deprojection(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    plan = _plan(); receipt = _receipt(plan)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _v2_equi())
    plan_path = tmp_path / "dataset-plan.json"; receipt_path = tmp_path / "source-receipt.json"; output_path = tmp_path / "scan-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8"); receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert scan_plan_main(["--plan", str(plan_path), "--receipt", str(receipt_path), "--out", str(output_path)]) == 0
    scan = json.loads(output_path.read_text(encoding="utf-8"))
    source = next(item for item in scan["sources"] if item["source_key"].startswith("scene:s1:"))
    assert source["projection"] == "equirectangular" and source["stereo_layout"] == "side-by-side"
    assert source["decode_mode"] == "spatial-deprojection-required" and source["sample_count"] == 24
    assert {item["eye"] for item in source["samples"]} == {"left", "right"}
    assert source["identity_bootstrap_eligible"] is False
    assert scan["teacher_training_authorized"] is False and scan["production_activation"] is False
