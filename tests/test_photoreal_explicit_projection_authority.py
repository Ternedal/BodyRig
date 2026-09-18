from __future__ import annotations

import copy
import json

import pytest

import bodyrig.photoreal_explicit_projection_authority as explicit
import bodyrig.photoreal_projection_authority as v2_authority
from bodyrig.photoreal_explicit_projection_authority import (
    PhotorealExplicitProjectionAuthorityError,
    resolve_projection_authority,
)
from bodyrig.photoreal_scan_plan_cli import PROJECTION_AUTHORITY_ENV, main as scan_plan_main


def _plan() -> dict[str, object]:
    train = {
        "kind": "video",
        "source_id": "scene:s1:E:/vr180.mp4",
        "group_id": "scene:s1",
        "path": "E:/vr180.mp4",
        "information_score": 100.0,
        "projection": "projection-ambiguous-2to1",
        "stereo_layout": "unknown",
        "width": 4320,
        "height": 2160,
        "duration_seconds": 60.0,
        "frame_rate": 60.0,
        "performer_count": 1,
        "source_binding": "scene-performer",
    }
    evaluation = copy.deepcopy(train)
    evaluation.update(
        {
            "source_id": "scene:s2:E:/flat.mp4",
            "group_id": "scene:s2",
            "path": "E:/flat.mp4",
            "projection": "flat",
            "stereo_layout": "mono",
            "width": 3840,
            "height": 2160,
        }
    )
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


def _projection_authority() -> dict[str, object]:
    return {
        "format": "bodyrig-explicit-projection-authority",
        "version": 1,
        "projection_type": "equi",
        "pose_degrees": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        "equirectangular_bounds_fraction": {
            "top": 0.0,
            "bottom": 0.0,
            "left": 0.25,
            "right": 0.25,
        },
        "cubemap_layout": None,
        "cubemap_padding_pixels": None,
        "mesh_projection_crc32": None,
        "mesh_projection_encoding": None,
        "mesh_projection_payload_bytes": None,
        "mesh_projection_geometry_sha256": None,
        "mesh_projection_mesh_count": None,
        "mesh_projection_total_vertex_count": None,
        "mesh_projection_total_index_count": None,
        "mesh_projection_texture_ids": None,
        "mesh_projection_index_types": None,
        "mesh_projection_unknown_box_types": None,
        "deprojection_authority": False,
    }


def _manifest(plan: dict[str, object]) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-explicit-projection-authority",
        "version": 1,
        "performer_id": "42",
        "sources": [
            {
                "source_key": plan["train"][0]["source_id"],
                "source_sha256": "a" * 64,
                "stereo_layout": "side-by-side",
                "authority_basis": "operator-verified",
                "projection_authority": _projection_authority(),
            }
        ],
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _install_no_spherical_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        explicit,
        "probe_isobmff_file",
        lambda _path: {
            "probe_status": "parsed-isobmff",
            "sv3d_present": False,
            "proj_present": False,
            "spherical_v1_present": False,
            "st3d_present": False,
        },
    )


def test_explicit_equi_authority_is_sha_bound_and_skips_v2_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    manifest = _manifest(plan)
    _install_no_spherical_probe(monkeypatch)
    monkeypatch.setattr(
        v2_authority,
        "probe_isobmff_file",
        lambda _path: (_ for _ in ()).throw(AssertionError("embedded V2 probe should not run for explicit source")),
    )

    resolved, v2_count, explicit_count = resolve_projection_authority(plan, receipt, manifest)

    assert v2_count == 0
    assert explicit_count == 1
    assert plan["train"][0]["projection"] == "projection-ambiguous-2to1"
    source = resolved["train"][0]
    assert source["projection"] == "equi"
    assert source["stereo_layout"] == "side-by-side"
    assert source["projection_authority"] == _projection_authority()
    assert source["projection_authority"]["format"] == "bodyrig-explicit-projection-authority"
    assert source["projection_authority"]["deprojection_authority"] is False


def test_rejects_spherical_v2_label_inside_explicit_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    manifest = _manifest(plan)
    manifest["sources"][0]["projection_authority"]["format"] = "bodyrig-spherical-v2-projection-authority"
    _install_no_spherical_probe(monkeypatch)

    with pytest.raises(PhotorealExplicitProjectionAuthorityError, match="format/version mismatch"):
        resolve_projection_authority(plan, receipt, manifest)


def test_rejects_explicit_authority_with_wrong_source_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    manifest = _manifest(plan)
    manifest["sources"][0]["source_sha256"] = "c" * 64
    _install_no_spherical_probe(monkeypatch)

    with pytest.raises(PhotorealExplicitProjectionAuthorityError, match="SHA-256"):
        resolve_projection_authority(plan, receipt, manifest)


def test_rejects_explicit_authority_that_would_override_embedded_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    manifest = _manifest(plan)
    monkeypatch.setattr(
        explicit,
        "probe_isobmff_file",
        lambda _path: {
            "probe_status": "parsed-isobmff",
            "sv3d_present": True,
            "proj_present": True,
            "spherical_v1_present": False,
            "st3d_present": True,
            "st3d_version": 0,
            "st3d_flags": 0,
            "stereo_mode": "left-right",
        },
    )

    with pytest.raises(PhotorealExplicitProjectionAuthorityError, match="cannot override embedded"):
        resolve_projection_authority(plan, receipt, manifest)


def test_rejects_non_verified_authority_basis(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    manifest = _manifest(plan)
    manifest["sources"][0]["authority_basis"] = "filename-inferred"
    _install_no_spherical_probe(monkeypatch)

    with pytest.raises(PhotorealExplicitProjectionAuthorityError, match="operator-verified"):
        resolve_projection_authority(plan, receipt, manifest)


def test_scan_plan_cli_accepts_authority_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    manifest = _manifest(plan)
    _install_no_spherical_probe(monkeypatch)
    monkeypatch.setattr(
        v2_authority,
        "probe_isobmff_file",
        lambda _path: (_ for _ in ()).throw(AssertionError("embedded V2 probe should not run for explicit source")),
    )

    plan_path = tmp_path / "dataset-plan.json"
    receipt_path = tmp_path / "source-receipt.json"
    authority_path = tmp_path / "projection-authority.json"
    output_path = tmp_path / "scan-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    authority_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv(PROJECTION_AUTHORITY_ENV, str(authority_path))

    assert scan_plan_main(
        [
            "--plan",
            str(plan_path),
            "--receipt",
            str(receipt_path),
            "--out",
            str(output_path),
        ]
    ) == 0

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["sources"][1]["projection"] == "equi" or written["sources"][0]["projection"] == "equi"
    explicit_source = next(source for source in written["sources"] if source["projection"] == "equi")
    assert explicit_source["source_sha256"] == "a" * 64
    assert explicit_source["stereo_layout"] == "side-by-side"
    assert explicit_source["projection_authority"]["format"] == "bodyrig-explicit-projection-authority"
    summary = json.loads(capsys.readouterr().out.strip())
    assert summary["resolved_explicit_projection_source_count"] == 1
    assert summary["resolved_v2_projection_source_count"] == 0
