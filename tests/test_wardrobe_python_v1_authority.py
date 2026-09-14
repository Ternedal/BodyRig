from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

import bodyrig.wardrobe_authority as authority
from bodyrig.wardrobe_source_capture import REQUIRED_VIEWS

BODY_ID = "body-fixture"
PACKAGE_SHA = "1" * 64
AVATAR_SHA = "2" * 64
REVISION = "a" * 40
RUNTIME_SHA = "3" * 64
SOURCE_GEOMETRY_SHA = "4" * 64
SOURCE_MESH_SHA = "5" * 64
SOURCE_MATERIAL_SHA = "6" * 64
SOURCE_TEXTURE_SHA = "7" * 64
INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_png(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", 1024, 1024)
    )
    return _file_sha(path)


def _bundle(root: Path, *, target: str | None = None, version: object = 1) -> Path:
    versions = {
        "render_authority": 1,
        "comparison": 1,
        "lineage": 1,
        "machine": 1,
        "deformation": 1,
        "manifest": 1,
    }
    if target is not None:
        versions[target] = version

    snapshots_root = root / "snapshots"
    view_hashes: dict[str, str] = {}
    snapshots: list[dict[str, object]] = []
    for view in REQUIRED_VIEWS:
        path = snapshots_root / f"{view}.png"
        digest = _write_png(path)
        view_hashes[view] = digest
        snapshots.append({
            "view": view,
            "file": path.name,
            "sha256": digest,
            "width": 1024,
            "height": 1024,
        })
    manifest_path = snapshots_root / "wardrobe-render-set.json"
    _write_json(manifest_path, {
        "format": "bodyrig-wardrobe-render-set",
        "version": versions["manifest"],
        "body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "semantics": "human-review-diagnostic-not-physical-pass",
        "snapshots": snapshots,
    })

    comparison_path = root / "comparison-authority.json"
    _write_json(comparison_path, {
        "format": "bodyrig-fidelity-comparison-authority",
        "version": versions["comparison"],
        "authority": "validated-package-comparison-only",
        "bodyrig_revision": REVISION,
        "runtime_manifest_sha256": RUNTIME_SHA,
        "package_sha256": PACKAGE_SHA,
        "physical_acceptance_authority": False,
        "comparison_only": True,
        "production_activation": False,
    })

    lineage_path = root / "wardrobe-package-lineage.json"
    _write_json(lineage_path, {
        "format": "bodyrig-wardrobe-package-lineage",
        "version": versions["lineage"],
        "policy_revision": "bodyrig-wardrobe-package-lineage-v1",
        "canonical_body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "avatar_sha256": AVATAR_SHA,
        "source_geometry_authority_sha256": SOURCE_GEOMETRY_SHA,
        "reconstruction_sha256": _sha("reconstruction"),
        "reconstruction_authority_sha256": _sha("reconstruction-authority"),
        "source_mesh_sha256": SOURCE_MESH_SHA,
        "source_material_sha256": SOURCE_MATERIAL_SHA,
        "source_texture_sha256": SOURCE_TEXTURE_SHA,
        "source_texture_name": "source.png",
        "body_model_gender": "neutral",
        "smplx_fit_profile": "fixture",
        "source_outer_surface_used": True,
        "source_grounded": True,
        "comparison_only": True,
        "human_review_required": True,
        "production_activation": False,
    })

    machine_path = root / "machine-probe.json"
    _write_json(machine_path, {
        "format": "bodyrig-renderer-probe",
        "version": versions["machine"],
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
    })

    deformation_path = root / "deformation-probe.json"
    pose_ids = ("neutral", "arms_abduction", "elbows_flexed", "arms_forward", "left_leg_lift", "knee_flexion")
    _write_json(deformation_path, {
        "format": "bodyrig-deformation-probe",
        "version": versions["deformation"],
        "platform": "windows-unity-univrm",
        "bodyrig_revision": REVISION,
        "body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "runtime_manifest_sha256": RUNTIME_SHA,
        "avatar_sha256": AVATAR_SHA,
        "build_guid": "fixture-build",
        "sequence_revision": "humanoid-muscle-sweep-v1",
        "pose_count": 6,
        "poses": [{"id": pose_id} for pose_id in pose_ids],
        "required_muscles_resolved": True,
        "restored_neutral": True,
        "complete": True,
        "manual_review_required": True,
    })

    render_authority_path = root / "wardrobe-render-authority.json"
    _write_json(render_authority_path, {
        "format": "bodyrig-wardrobe-render-authority",
        "version": versions["render_authority"],
        "bodyrig_revision": REVISION,
        "body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "avatar_sha256": AVATAR_SHA,
        "runtime_manifest_sha256": RUNTIME_SHA,
        "comparison_authority_sha256": _file_sha(comparison_path),
        "package_lineage_sha256": _file_sha(lineage_path),
        "source_geometry_authority_sha256": SOURCE_GEOMETRY_SHA,
        "source_mesh_sha256": SOURCE_MESH_SHA,
        "source_material_sha256": SOURCE_MATERIAL_SHA,
        "source_texture_sha256": SOURCE_TEXTURE_SHA,
        "render_manifest_sha256": _file_sha(manifest_path),
        "render_view_sha256": view_hashes,
        "machine_probe_sha256": _file_sha(machine_path),
        "deformation_probe_sha256": _file_sha(deformation_path),
        "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
        "deformation_machine_pass": True,
        "comparison_only": True,
        "human_review_required": True,
        "production_activation": False,
    })
    return render_authority_path


@pytest.mark.parametrize("target", [
    "render_authority", "comparison", "lineage", "machine", "deformation", "manifest",
])
@pytest.mark.parametrize("bad_version", INVALID_V1_VALUES)
def test_persisted_wardrobe_bundle_rejects_non_numeric_v1(
    tmp_path: Path,
    target: str,
    bad_version: object,
) -> None:
    render_authority_path = _bundle(tmp_path / f"{target}-{type(bad_version).__name__}", target=target, version=bad_version)
    with pytest.raises(authority.WardrobeAuthorityError):
        authority.validate_render_authority_bundle(
            render_authority_path,
            body_id=BODY_ID,
            package_sha256=PACKAGE_SHA,
            bodyrig_revision=REVISION,
        )


@pytest.mark.parametrize("target", [
    "render_authority", "comparison", "lineage", "machine", "deformation", "manifest",
])
def test_persisted_wardrobe_bundle_preserves_numeric_float_v1(tmp_path: Path, target: str) -> None:
    render_authority_path = _bundle(tmp_path / target, target=target, version=1.0)
    result = authority.validate_render_authority_bundle(
        render_authority_path,
        body_id=BODY_ID,
        package_sha256=PACKAGE_SHA,
        bodyrig_revision=REVISION,
    )
    assert result["value"]["production_activation"] is False
    assert result["value"]["comparison_only"] is True
    assert result["value"]["human_review_required"] is True


def _top_receipt(version: object) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    assembly = {
        "person_id": "person-" + "1" * 32,
        "person_revision": "person-r0001",
        "assembly_fingerprint": _sha("assembly"),
        "body_revision": "body-r0001",
        "body_id": BODY_ID,
    }
    release = {"package_sha256": PACKAGE_SHA}
    source_capture_sha = _sha("source-capture")
    render_authority_sha = _sha("render-authority")
    review_id = authority._review_id(
        person_id=str(assembly["person_id"]),
        person_revision=str(assembly["person_revision"]),
        assembly_fingerprint=str(assembly["assembly_fingerprint"]),
        body_package_sha256=PACKAGE_SHA,
        bodyrig_revision=REVISION,
        source_capture_sha256=source_capture_sha,
        render_authority_sha256=render_authority_sha,
    )
    checklist = {field: True for field in authority.CHECKLIST_FIELDS}
    receipt: dict[str, object] = {
        "format": authority.FORMAT,
        "version": version,
        "policy_revision": authority.POLICY_REVISION,
        "review_id": review_id,
        "person_id": assembly["person_id"],
        "person_revision": assembly["person_revision"],
        "assembly_fingerprint": assembly["assembly_fingerprint"],
        "body_revision": assembly["body_revision"],
        "body_id": BODY_ID,
        "body_package_sha256": PACKAGE_SHA,
        "bodyrig_revision": REVISION,
        "source_capture_id": "wardcap-" + "2" * 32,
        "source_capture_sha256": source_capture_sha,
        "source_manifest_sha256": _sha("source-manifest"),
        "source_view_sha256": {view: _sha(f"source-{view}") for view in REQUIRED_VIEWS},
        "garment_inventory_sha256": _sha("garments"),
        "garment_count": 1,
        "footwear_present": False,
        "render_authority_sha256": render_authority_sha,
        "package_lineage_sha256": _sha("lineage"),
        "comparison_authority_sha256": _sha("comparison"),
        "runtime_manifest_sha256": RUNTIME_SHA,
        "render_manifest_sha256": _sha("render-manifest"),
        "render_view_sha256": {view: _sha(f"render-{view}") for view in REQUIRED_VIEWS},
        "machine_probe_sha256": _sha("machine"),
        "deformation_probe_sha256": _sha("deformation"),
        "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
        "reviewed_utc": "2026-09-14T00:00:00Z",
        "checklist": checklist,
        "quality_note": "Source-grounded wardrobe review fixture.",
        "state": "complete",
        "source_grounded": True,
        "operator_supplied": True,
        **checklist,
        "footwear_review_required": False,
        "footwear_review_passed": False,
        "production_activation": False,
    }
    return receipt, assembly, release


@pytest.mark.parametrize("bad_version", INVALID_V1_VALUES)
def test_top_level_human_review_authority_rejects_non_numeric_v1(
    monkeypatch: pytest.MonkeyPatch,
    bad_version: object,
) -> None:
    receipt, assembly, release = _top_receipt(bad_version)
    monkeypatch.setattr(authority, "_assembly_identity", lambda _value: assembly)
    monkeypatch.setattr(authority, "_release_identity", lambda _value, _assembly: release)
    with pytest.raises(authority.WardrobeAuthorityError, match="format/version/policy"):
        authority.validate_authority_structure(
            receipt,
            assembly_receipt={},
            body_release_status={},
        )


def test_top_level_human_review_authority_preserves_numeric_float_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    receipt, assembly, release = _top_receipt(1.0)
    monkeypatch.setattr(authority, "_assembly_identity", lambda _value: assembly)
    monkeypatch.setattr(authority, "_release_identity", lambda _value, _assembly: release)
    validated = authority.validate_authority_structure(
        receipt,
        assembly_receipt={},
        body_release_status={},
    )
    assert validated["version"] == 1.0
    assert validated["operator_supplied"] is True
    assert validated["production_activation"] is False
