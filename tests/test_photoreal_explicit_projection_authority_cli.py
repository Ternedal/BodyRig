from __future__ import annotations

import json

import pytest

import bodyrig.photoreal_explicit_projection_authority as explicit
from bodyrig.photoreal_explicit_projection_authority_cli import (
    PhotorealExplicitProjectionAuthorityCliError,
    build_verified_vr180_manifest,
    main,
)


def _plan() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "train": [
            {
                "kind": "video",
                "source_id": "scene:s1:E:/vr180.mp4",
                "group_id": "scene:s1",
                "projection": "projection-ambiguous-2to1",
                "stereo_layout": "unknown",
            }
        ],
        "evaluation": [
            {
                "kind": "video",
                "source_id": "scene:s2:E:/flat.mp4",
                "group_id": "scene:s2",
                "projection": "flat",
                "stereo_layout": "mono",
            }
        ],
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _receipt() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
        "sources": [
            {
                "kind": "video",
                "source_key": "scene:s1:E:/vr180.mp4",
                "resolved_path": "E:/vr180.mp4",
                "sha256": "a" * 64,
            },
            {
                "kind": "video",
                "source_key": "scene:s2:E:/flat.mp4",
                "resolved_path": "E:/flat.mp4",
                "sha256": "b" * 64,
            },
        ],
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


def test_manifest_generation_requires_explicit_operator_attestation() -> None:
    with pytest.raises(PhotorealExplicitProjectionAuthorityCliError, match="operator to verify"):
        build_verified_vr180_manifest(
            _plan(),
            _receipt(),
            stereo_layout="side-by-side",
            operator_verified=False,
        )


def test_manifest_binds_only_spatial_sources_to_receipt_sha() -> None:
    manifest = build_verified_vr180_manifest(
        _plan(),
        _receipt(),
        stereo_layout="side-by-side",
        operator_verified=True,
    )

    assert manifest["format"] == "bodyrig-photoreal-explicit-projection-authority"
    assert manifest["performer_id"] == "42"
    assert manifest["build_only"] is True
    assert manifest["runtime_dependency"] is False
    assert manifest["production_activation"] is False
    assert len(manifest["sources"]) == 1

    source = manifest["sources"][0]
    assert source["source_key"] == "scene:s1:E:/vr180.mp4"
    assert source["source_sha256"] == "a" * 64
    assert source["stereo_layout"] == "side-by-side"
    assert source["authority_basis"] == "operator-verified"
    authority = source["projection_authority"]
    assert authority["format"] == "bodyrig-explicit-projection-authority"
    assert authority["projection_type"] == "equi"
    assert authority["pose_degrees"] == {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}
    assert authority["equirectangular_bounds_fraction"] == {
        "top": 0.0,
        "bottom": 0.0,
        "left": 0.25,
        "right": 0.25,
    }
    assert authority["deprojection_authority"] is False


def test_manifest_generation_rejects_missing_spatial_receipt_binding() -> None:
    receipt = _receipt()
    receipt["sources"] = receipt["sources"][1:]

    with pytest.raises(PhotorealExplicitProjectionAuthorityCliError, match="every spatial dataset source"):
        build_verified_vr180_manifest(
            _plan(),
            receipt,
            stereo_layout="side-by-side",
            operator_verified=True,
        )


def test_cli_writes_new_sha_bound_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_no_spherical_probe(monkeypatch)
    plan_path = tmp_path / "dataset-plan.json"
    receipt_path = tmp_path / "source-receipt.json"
    output_path = tmp_path / "projection-authority.json"
    plan_path.write_text(json.dumps(_plan()), encoding="utf-8")
    receipt_path.write_text(json.dumps(_receipt()), encoding="utf-8")

    assert main(
        [
            "--plan",
            str(plan_path),
            "--receipt",
            str(receipt_path),
            "--out",
            str(output_path),
            "--stereo-layout",
            "side-by-side",
            "--operator-verified-vr180-equi",
        ]
    ) == 0

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["sources"][0]["source_sha256"] == "a" * 64
    summary = json.loads(capsys.readouterr().out.strip())
    assert summary["source_count"] == 1
    assert summary["preflight_source_count"] == 1
    assert summary["operator_verified"] is True
    assert summary["embedded_projection_override"] is False
    assert summary["production_activation"] is False

    assert main(
        [
            "--plan",
            str(plan_path),
            "--receipt",
            str(receipt_path),
            "--out",
            str(output_path),
            "--stereo-layout",
            "side-by-side",
            "--operator-verified-vr180-equi",
        ]
    ) == 1


def test_cli_rejects_manifest_when_embedded_spherical_authority_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        explicit,
        "probe_isobmff_file",
        lambda _path: {
            "probe_status": "parsed-isobmff",
            "sv3d_present": True,
            "proj_present": True,
            "spherical_v1_present": False,
            "st3d_present": False,
        },
    )
    plan_path = tmp_path / "dataset-plan.json"
    receipt_path = tmp_path / "source-receipt.json"
    output_path = tmp_path / "projection-authority.json"
    plan_path.write_text(json.dumps(_plan()), encoding="utf-8")
    receipt_path.write_text(json.dumps(_receipt()), encoding="utf-8")

    assert main(
        [
            "--plan",
            str(plan_path),
            "--receipt",
            str(receipt_path),
            "--out",
            str(output_path),
            "--stereo-layout",
            "side-by-side",
            "--operator-verified-vr180-equi",
        ]
    ) == 1
    assert not output_path.exists()
    assert "cannot override embedded spherical projection metadata" in capsys.readouterr().err
