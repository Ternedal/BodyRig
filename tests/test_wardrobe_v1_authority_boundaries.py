from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.wardrobe_authority as wardrobe
from bodyrig.wardrobe_source_capture import REQUIRED_VIEWS

BODY_ID = "body-test"
PACKAGE_SHA = "b" * 64
REVISION = "1" * 40
RUNTIME_SHA = "a" * 64
AVATAR_SHA = "c" * 64
GEOMETRY_SHA = "d" * 64
MESH_SHA = "e" * 64
MATERIAL_SHA = "f" * 64
TEXTURE_SHA = "0" * 64


def _hashes() -> dict[str, str]:
    return {
        "wardrobe-render-authority.json": "1" * 64,
        "comparison-authority.json": "2" * 64,
        "wardrobe-package-lineage.json": "3" * 64,
        "machine-probe.json": "4" * 64,
        "deformation-probe.json": "5" * 64,
    }


def _comparison(version: object = 1) -> dict[str, object]:
    return {
        "format": "bodyrig-fidelity-comparison-authority",
        "version": version,
        "authority": "validated-package-comparison-only",
        "bodyrig_revision": REVISION,
        "runtime_manifest_sha256": RUNTIME_SHA,
        "package_sha256": PACKAGE_SHA,
        "physical_acceptance_authority": False,
        "comparison_only": True,
        "production_activation": False,
    }


def _lineage(version: object = 1) -> dict[str, object]:
    return {
        "format": "bodyrig-wardrobe-package-lineage",
        "version": version,
        "policy_revision": "fixture-v1",
        "canonical_body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "avatar_sha256": AVATAR_SHA,
        "source_geometry_authority_sha256": GEOMETRY_SHA,
        "reconstruction_sha256": "6" * 64,
        "reconstruction_authority_sha256": "7" * 64,
        "source_mesh_sha256": MESH_SHA,
        "source_material_sha256": MATERIAL_SHA,
        "source_texture_sha256": TEXTURE_SHA,
        "source_texture_name": "source.png",
        "body_model_gender": "neutral",
        "smplx_fit_profile": "fixture",
        "source_outer_surface_used": True,
        "source_grounded": True,
        "comparison_only": True,
        "human_review_required": True,
        "production_activation": False,
    }


def _machine(version: object = 1) -> dict[str, object]:
    return {
        "format": "bodyrig-renderer-probe",
        "version": version,
        "platform": "windows-unity-univrm",
        "bodyrig_revision": REVISION,
        "body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "runtime_manifest_sha256": RUNTIME_SHA,
        "avatar_sha256": AVATAR_SHA,
        "build_guid": "fixture-build",
        "vrm10_loaded": True,
        "humanoid_valid": True,
        "required_bones_valid": True,
    }


def _deformation(version: object = 1) -> dict[str, object]:
    pose_ids = (
        "neutral",
        "arms_abduction",
        "elbows_flexed",
        "arms_forward",
        "left_leg_lift",
        "knee_flexion",
    )
    return {
        "format": "bodyrig-deformation-probe",
        "version": version,
        "platform": "windows-unity-univrm",
        "bodyrig_revision": REVISION,
        "body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "runtime_manifest_sha256": RUNTIME_SHA,
        "avatar_sha256": AVATAR_SHA,
        "build_guid": "fixture-build",
        "sequence_revision": "humanoid-muscle-sweep-v1",
        "pose_count": 6,
        "poses": [{"id": value} for value in pose_ids],
        "required_muscles_resolved": True,
        "restored_neutral": True,
        "complete": True,
        "manual_review_required": True,
    }


def _render_authority(version: object = 1) -> dict[str, object]:
    hashes = _hashes()
    return {
        "format": "bodyrig-wardrobe-render-authority",
        "version": version,
        "bodyrig_revision": REVISION,
        "body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "avatar_sha256": AVATAR_SHA,
        "runtime_manifest_sha256": RUNTIME_SHA,
        "comparison_authority_sha256": hashes["comparison-authority.json"],
        "package_lineage_sha256": hashes["wardrobe-package-lineage.json"],
        "source_geometry_authority_sha256": GEOMETRY_SHA,
        "source_mesh_sha256": MESH_SHA,
        "source_material_sha256": MATERIAL_SHA,
        "source_texture_sha256": TEXTURE_SHA,
        "render_manifest_sha256": "8" * 64,
        "render_view_sha256": {view: "9" * 64 for view in REQUIRED_VIEWS},
        "machine_probe_sha256": hashes["machine-probe.json"],
        "deformation_probe_sha256": hashes["deformation-probe.json"],
        "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
        "deformation_machine_pass": True,
        "comparison_only": True,
        "human_review_required": True,
        "production_activation": False,
    }


def _install_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    versions: dict[str, object] | None = None,
) -> Path:
    versions = versions or {}
    root = tmp_path / "render"
    (root / "snapshots").mkdir(parents=True)
    names = (
        "wardrobe-render-authority.json",
        "comparison-authority.json",
        "wardrobe-package-lineage.json",
        "machine-probe.json",
        "deformation-probe.json",
    )
    for name in names:
        (root / name).write_text("{}\n", encoding="utf-8")

    objects = {
        "wardrobe-render-authority.json": _render_authority(versions.get("render", 1)),
        "comparison-authority.json": _comparison(versions.get("comparison", 1)),
        "wardrobe-package-lineage.json": _lineage(versions.get("lineage", 1)),
        "machine-probe.json": _machine(versions.get("machine", 1)),
        "deformation-probe.json": _deformation(versions.get("deformation", 1)),
    }
    monkeypatch.setattr(
        wardrobe,
        "_read_json",
        lambda path, label: objects[Path(path).name],
    )
    hashes = _hashes()
    monkeypatch.setattr(
        wardrobe,
        "_sha256_file",
        lambda path: hashes.get(Path(path).name, "8" * 64),
    )
    monkeypatch.setattr(
        wardrobe,
        "validate_render_manifest",
        lambda *args, **kwargs: {
            "manifest_sha256": "8" * 64,
            "view_sha256": {view: "9" * 64 for view in REQUIRED_VIEWS},
        },
    )
    return root / "wardrobe-render-authority.json"


@pytest.mark.parametrize("value", [True, False, "1", None, {}, [], 2, float("nan"), float("inf")])
def test_numeric_v1_predicate_rejects_aliases(value: object) -> None:
    assert wardrobe._is_numeric_v1(value) is False


@pytest.mark.parametrize("value", [1, 1.0])
def test_numeric_v1_predicate_preserves_json_numeric_v1(value: object) -> None:
    assert wardrobe._is_numeric_v1(value) is True


@pytest.mark.parametrize("target", ["render", "comparison", "lineage", "machine", "deformation"])
def test_persisted_render_bundle_rejects_boolean_v1_at_each_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    path = _install_bundle(tmp_path, monkeypatch, versions={target: True})
    with pytest.raises(wardrobe.WardrobeAuthorityError):
        wardrobe.validate_render_authority_bundle(
            path,
            body_id=BODY_ID,
            package_sha256=PACKAGE_SHA,
            bodyrig_revision=REVISION,
        )


def test_persisted_render_bundle_preserves_float_v1_at_all_readers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _install_bundle(
        tmp_path,
        monkeypatch,
        versions={
            "render": 1.0,
            "comparison": 1.0,
            "lineage": 1.0,
            "machine": 1.0,
            "deformation": 1.0,
        },
    )
    result = wardrobe.validate_render_authority_bundle(
        path,
        body_id=BODY_ID,
        package_sha256=PACKAGE_SHA,
        bodyrig_revision=REVISION,
    )
    assert result["runtime_manifest_sha256"] == RUNTIME_SHA


def _human_authority(version: object) -> dict[str, object]:
    assembly = {
        "person_id": "person-" + "1" * 32,
        "person_revision": "person-r0001",
        "assembly_fingerprint": "2" * 64,
        "body_revision": "body-r0001",
        "body_id": "body-" + "3" * 32,
    }
    source_capture_sha = "4" * 64
    review_id = "wardreview-" + "5" * 32
    return {
        "format": wardrobe.FORMAT,
        "version": version,
        "policy_revision": wardrobe.POLICY_REVISION,
        "review_id": review_id,
        **assembly,
        "body_package_sha256": "6" * 64,
        "bodyrig_revision": REVISION,
        "source_capture_id": "wardcap-" + "7" * 32,
        "source_capture_sha256": source_capture_sha,
        "source_manifest_sha256": "8" * 64,
        "source_view_sha256": {view: "9" * 64 for view in REQUIRED_VIEWS},
        "garment_inventory_sha256": "a" * 64,
        "garment_count": 2,
        "footwear_present": False,
        "render_authority_sha256": "b" * 64,
        "package_lineage_sha256": "c" * 64,
        "comparison_authority_sha256": "d" * 64,
        "runtime_manifest_sha256": "e" * 64,
        "render_manifest_sha256": "f" * 64,
        "render_view_sha256": {view: "0" * 64 for view in REQUIRED_VIEWS},
        "machine_probe_sha256": "1" * 64,
        "deformation_probe_sha256": "2" * 64,
        "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
        "reviewed_utc": "2026-09-18T00:00:00Z",
        "checklist": {field: True for field in wardrobe.CHECKLIST_FIELDS},
        "quality_note": "Reviewed exact source-grounded wardrobe evidence.",
        "state": "complete",
        "source_grounded": True,
        "operator_supplied": True,
        **{field: True for field in wardrobe.CHECKLIST_FIELDS},
        "footwear_review_required": False,
        "footwear_review_passed": False,
        "production_activation": False,
    }


def test_human_review_authority_rejects_bool_and_accepts_float_v1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assembly = {
        "person_id": "person-" + "1" * 32,
        "person_revision": "person-r0001",
        "assembly_fingerprint": "2" * 64,
        "body_revision": "body-r0001",
        "body_id": "body-" + "3" * 32,
    }
    monkeypatch.setattr(wardrobe, "_assembly_identity", lambda receipt: dict(assembly))
    monkeypatch.setattr(
        wardrobe,
        "_release_identity",
        lambda status, observed: {"package_sha256": "6" * 64},
    )
    monkeypatch.setattr(
        wardrobe,
        "_review_id",
        lambda **kwargs: "wardreview-" + "5" * 32,
    )

    with pytest.raises(wardrobe.WardrobeAuthorityError, match="format/version/policy"):
        wardrobe.validate_authority_structure(
            _human_authority(True),
            assembly_receipt={},
            body_release_status={},
        )

    result = wardrobe.validate_authority_structure(
        _human_authority(1.0),
        assembly_receipt={},
        body_release_status={},
    )
    assert result["version"] == 1.0
