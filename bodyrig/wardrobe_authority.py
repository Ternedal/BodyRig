from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .hands_feet_nails_authority import (
    HandsFeetNailsAuthorityError,
    _assembly_identity,
    _release_identity,
)
from .wardrobe_source_capture import (
    REQUIRED_VIEWS,
    WardrobeSourceCaptureError,
    capture_dir,
    read_source_capture,
)

FORMAT = "bodyrig-wardrobe-authority"
VERSION = 1
POLICY_REVISION = "bodyrig-wardrobe-authority-v1"
REVIEW_ID_RE = re.compile(r"^wardreview-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BODYRIG_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHECKLIST_FIELDS = {
    "source_presentation_identity_review_passed",
    "garment_geometry_review_passed",
    "material_review_passed",
    "layering_review_passed",
    "attachment_review_passed",
    "deformation_review_passed",
}
RENDER_AUTHORITY_FIELDS = {
    "format", "version", "bodyrig_revision", "body_id", "package_sha256", "avatar_sha256",
    "runtime_manifest_sha256", "comparison_authority_sha256", "package_lineage_sha256",
    "source_geometry_authority_sha256", "source_mesh_sha256", "source_material_sha256",
    "source_texture_sha256", "render_manifest_sha256", "render_view_sha256",
    "machine_probe_sha256", "deformation_probe_sha256", "deformation_sequence_revision",
    "deformation_machine_pass", "comparison_only", "human_review_required", "production_activation",
}
PACKAGE_LINEAGE_FIELDS = {
    "format", "version", "policy_revision", "canonical_body_id", "package_sha256", "avatar_sha256",
    "source_geometry_authority_sha256", "reconstruction_sha256", "reconstruction_authority_sha256",
    "source_mesh_sha256", "source_material_sha256", "source_texture_sha256", "source_texture_name",
    "body_model_gender", "smplx_fit_profile", "source_outer_surface_used", "source_grounded",
    "comparison_only", "human_review_required", "production_activation",
}
COMPARISON_FIELDS = {
    "format", "version", "authority", "bodyrig_revision", "runtime_manifest_sha256", "package_sha256",
    "physical_acceptance_authority", "comparison_only", "production_activation",
}
RENDER_MANIFEST_FIELDS = {"format", "version", "body_id", "package_sha256", "semantics", "snapshots"}
RENDER_ENTRY_FIELDS = {"view", "file", "sha256", "width", "height"}
TOP_FIELDS = {
    "format", "version", "policy_revision", "review_id", "person_id", "person_revision",
    "assembly_fingerprint", "body_revision", "body_id", "body_package_sha256", "bodyrig_revision",
    "source_capture_id", "source_capture_sha256", "source_manifest_sha256", "source_view_sha256",
    "garment_inventory_sha256", "garment_count", "footwear_present", "render_authority_sha256",
    "package_lineage_sha256", "comparison_authority_sha256", "runtime_manifest_sha256",
    "render_manifest_sha256", "render_view_sha256", "machine_probe_sha256", "deformation_probe_sha256",
    "deformation_sequence_revision", "reviewed_utc", "checklist", "quality_note", "state",
    "source_grounded", "operator_supplied", *CHECKLIST_FIELDS, "footwear_review_required",
    "footwear_review_passed", "production_activation",
}


class WardrobeAuthorityError(RuntimeError):
    pass


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise WardrobeAuthorityError(f"{label} is not a canonical SHA-256")
    return text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WardrobeAuthorityError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise WardrobeAuthorityError(f"{label} must be a JSON object")
    return value


def _png_dimensions(path: Path) -> tuple[int, int]:
    raw = path.read_bytes()[:24]
    if len(raw) < 24 or raw[:8] != PNG_SIGNATURE or raw[12:16] != b"IHDR":
        raise WardrobeAuthorityError(f"wardrobe render is not a canonical PNG: {path.name}")
    width, height = struct.unpack(">II", raw[16:24])
    if width != 1024 or height != 1024:
        raise WardrobeAuthorityError(f"wardrobe render must be 1024x1024: {path.name}")
    return width, height


def validate_render_manifest(path: str | os.PathLike[str], *, body_id: str, package_sha256: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    value = _read_json(source, "wardrobe render manifest")
    if set(value) != RENDER_MANIFEST_FIELDS:
        raise WardrobeAuthorityError("wardrobe render manifest fields are not canonical")
    if value.get("format") != "bodyrig-wardrobe-render-set" or value.get("version") != 1:
        raise WardrobeAuthorityError("wardrobe render manifest format/version mismatch")
    if value.get("semantics") != "human-review-diagnostic-not-physical-pass":
        raise WardrobeAuthorityError("wardrobe render manifest crossed the human-review-only boundary")
    if str(value.get("body_id") or "") != body_id or _sha(value.get("package_sha256"), "wardrobe render package SHA-256") != package_sha256:
        raise WardrobeAuthorityError("wardrobe render manifest belongs to different body/package bytes")
    snapshots = value.get("snapshots")
    if not isinstance(snapshots, list) or len(snapshots) != len(REQUIRED_VIEWS):
        raise WardrobeAuthorityError("wardrobe render manifest does not contain four canonical views")
    if [item.get("view") for item in snapshots if isinstance(item, Mapping)] != list(REQUIRED_VIEWS):
        raise WardrobeAuthorityError("wardrobe render view order is not canonical")
    hashes: dict[str, str] = {}
    root = source.parent
    for view, item in zip(REQUIRED_VIEWS, snapshots, strict=True):
        if not isinstance(item, Mapping) or set(item) != RENDER_ENTRY_FIELDS:
            raise WardrobeAuthorityError(f"{view} wardrobe render entry fields are invalid")
        filename = str(item.get("file") or "")
        if filename != f"{view}.png":
            raise WardrobeAuthorityError(f"{view} wardrobe render filename is invalid")
        image = root / filename
        if not image.is_file():
            raise WardrobeAuthorityError(f"{view} wardrobe render image is missing")
        width, height = _png_dimensions(image)
        actual = _sha256_file(image)
        if item.get("width") != width or item.get("height") != height or _sha(item.get("sha256"), f"{view} render SHA-256") != actual:
            raise WardrobeAuthorityError(f"{view} wardrobe render bytes no longer match manifest")
        hashes[view] = actual
    return {"manifest": value, "manifest_path": source, "manifest_sha256": _sha256_file(source), "view_sha256": hashes}


def _validate_comparison(value: Mapping[str, Any], *, revision: str, package_sha256: str) -> str:
    if set(value) != COMPARISON_FIELDS:
        raise WardrobeAuthorityError("wardrobe comparison authority fields are not canonical")
    if value.get("format") != "bodyrig-fidelity-comparison-authority" or value.get("version") != 1 or value.get("authority") != "validated-package-comparison-only":
        raise WardrobeAuthorityError("wardrobe comparison authority is not canonical validated-package comparison")
    if str(value.get("bodyrig_revision") or "").lower() != revision or _sha(value.get("package_sha256"), "comparison package SHA-256") != package_sha256:
        raise WardrobeAuthorityError("wardrobe comparison authority belongs to different revision/package bytes")
    if value.get("physical_acceptance_authority") is not False or value.get("comparison_only") is not True or value.get("production_activation") is not False:
        raise WardrobeAuthorityError("wardrobe comparison authority crossed review-only boundary")
    return _sha(value.get("runtime_manifest_sha256"), "comparison runtime manifest SHA-256")


def validate_render_authority_bundle(
    render_authority_path: str | os.PathLike[str],
    *,
    body_id: str,
    package_sha256: str,
    bodyrig_revision: str,
) -> dict[str, Any]:
    path = Path(render_authority_path).expanduser().resolve()
    if path.name != "wardrobe-render-authority.json" or not path.is_file():
        raise WardrobeAuthorityError("canonical wardrobe render authority is missing")
    value = _read_json(path, "wardrobe render authority")
    if set(value) != RENDER_AUTHORITY_FIELDS or value.get("format") != "bodyrig-wardrobe-render-authority" or value.get("version") != 1:
        raise WardrobeAuthorityError("wardrobe render authority fields/format are invalid")
    revision = str(bodyrig_revision or "").lower()
    if not BODYRIG_REVISION_RE.fullmatch(revision) or str(value.get("bodyrig_revision") or "").lower() != revision:
        raise WardrobeAuthorityError("wardrobe renders were produced by a different BodyRig revision")
    if str(value.get("body_id") or "") != body_id or _sha(value.get("package_sha256"), "wardrobe authority package SHA-256") != package_sha256:
        raise WardrobeAuthorityError("wardrobe render authority belongs to different body/package bytes")
    if value.get("deformation_sequence_revision") != "humanoid-muscle-sweep-v1" or value.get("deformation_machine_pass") is not True:
        raise WardrobeAuthorityError("wardrobe render authority lacks canonical deformation machine evidence")
    if value.get("comparison_only") is not True or value.get("human_review_required") is not True or value.get("production_activation") is not False:
        raise WardrobeAuthorityError("wardrobe render authority crossed review-only boundary")

    root = path.parent
    comparison_path = root / "comparison-authority.json"
    lineage_path = root / "wardrobe-package-lineage.json"
    machine_path = root / "machine-probe.json"
    deformation_path = root / "deformation-probe.json"
    for required, label in (
        (comparison_path, "comparison authority"), (lineage_path, "package lineage"),
        (machine_path, "machine probe"), (deformation_path, "deformation probe"),
    ):
        if not required.is_file():
            raise WardrobeAuthorityError(f"wardrobe {label} is missing beside render authority")

    comparison = _read_json(comparison_path, "wardrobe comparison authority")
    runtime_sha = _validate_comparison(comparison, revision=revision, package_sha256=package_sha256)
    if _sha(value.get("comparison_authority_sha256"), "comparison authority SHA-256") != _sha256_file(comparison_path):
        raise WardrobeAuthorityError("wardrobe render authority no longer matches comparison-authority bytes")
    if _sha(value.get("runtime_manifest_sha256"), "runtime manifest SHA-256") != runtime_sha:
        raise WardrobeAuthorityError("wardrobe runtime lineage differs from comparison authority")

    lineage = _read_json(lineage_path, "wardrobe package lineage")
    if set(lineage) != PACKAGE_LINEAGE_FIELDS or lineage.get("format") != "bodyrig-wardrobe-package-lineage" or lineage.get("version") != 1:
        raise WardrobeAuthorityError("wardrobe package lineage fields/format are invalid")
    if str(lineage.get("canonical_body_id") or "") != body_id or _sha(lineage.get("package_sha256"), "lineage package SHA-256") != package_sha256:
        raise WardrobeAuthorityError("wardrobe package lineage belongs to different body/package bytes")
    if lineage.get("source_outer_surface_used") is not True or lineage.get("source_grounded") is not True or lineage.get("comparison_only") is not True or lineage.get("human_review_required") is not True or lineage.get("production_activation") is not False:
        raise WardrobeAuthorityError("wardrobe package lineage is not source-grounded review-only authority")
    if _sha(value.get("package_lineage_sha256"), "package lineage SHA-256") != _sha256_file(lineage_path):
        raise WardrobeAuthorityError("wardrobe render authority no longer matches package-lineage bytes")
    for authority_field, lineage_field in (
        ("avatar_sha256", "avatar_sha256"),
        ("source_geometry_authority_sha256", "source_geometry_authority_sha256"),
        ("source_mesh_sha256", "source_mesh_sha256"),
        ("source_material_sha256", "source_material_sha256"),
        ("source_texture_sha256", "source_texture_sha256"),
    ):
        if _sha(value.get(authority_field), authority_field) != _sha(lineage.get(lineage_field), lineage_field):
            raise WardrobeAuthorityError(f"wardrobe render authority {authority_field} differs from package lineage")

    machine = _read_json(machine_path, "wardrobe machine probe")
    deformation = _read_json(deformation_path, "wardrobe deformation probe")
    if machine.get("format") != "bodyrig-renderer-probe" or machine.get("version") != 1 or machine.get("platform") != "windows-unity-univrm":
        raise WardrobeAuthorityError("wardrobe machine probe format/platform is invalid")
    if str(machine.get("bodyrig_revision") or "").lower() != revision or str(machine.get("body_id") or "") != body_id:
        raise WardrobeAuthorityError("wardrobe machine probe revision/body is mismatched")
    if _sha(machine.get("package_sha256"), "machine package SHA-256") != package_sha256 or _sha(machine.get("runtime_manifest_sha256"), "machine runtime SHA-256") != runtime_sha:
        raise WardrobeAuthorityError("wardrobe machine probe package/runtime is mismatched")
    if _sha(machine.get("avatar_sha256"), "machine avatar SHA-256") != _sha(value.get("avatar_sha256"), "authority avatar SHA-256"):
        raise WardrobeAuthorityError("wardrobe machine probe loaded different avatar bytes")
    if machine.get("vrm10_loaded") is not True or machine.get("humanoid_valid") is not True or machine.get("required_bones_valid") is not True:
        raise WardrobeAuthorityError("wardrobe machine probe did not pass VRM/Humanoid/bone checks")
    if _sha(value.get("machine_probe_sha256"), "machine probe SHA-256") != _sha256_file(machine_path):
        raise WardrobeAuthorityError("wardrobe machine probe bytes changed")

    expected_poses = ("neutral", "arms_abduction", "elbows_flexed", "arms_forward", "left_leg_lift", "knee_flexion")
    poses = deformation.get("poses")
    pose_ids = tuple(str(item.get("id") or "") for item in poses if isinstance(item, Mapping)) if isinstance(poses, list) else ()
    if deformation.get("format") != "bodyrig-deformation-probe" or deformation.get("version") != 1 or deformation.get("platform") != "windows-unity-univrm":
        raise WardrobeAuthorityError("wardrobe deformation probe format/platform is invalid")
    if str(deformation.get("bodyrig_revision") or "").lower() != revision or str(deformation.get("body_id") or "") != body_id:
        raise WardrobeAuthorityError("wardrobe deformation probe revision/body is mismatched")
    if _sha(deformation.get("package_sha256"), "deformation package SHA-256") != package_sha256 or _sha(deformation.get("runtime_manifest_sha256"), "deformation runtime SHA-256") != runtime_sha:
        raise WardrobeAuthorityError("wardrobe deformation probe package/runtime is mismatched")
    if _sha(deformation.get("avatar_sha256"), "deformation avatar SHA-256") != _sha(value.get("avatar_sha256"), "authority avatar SHA-256"):
        raise WardrobeAuthorityError("wardrobe deformation probe used different avatar bytes")
    if str(deformation.get("build_guid") or "") != str(machine.get("build_guid") or ""):
        raise WardrobeAuthorityError("wardrobe deformation probe build differs from machine probe")
    if deformation.get("sequence_revision") != "humanoid-muscle-sweep-v1" or deformation.get("pose_count") != 6 or pose_ids != expected_poses:
        raise WardrobeAuthorityError("wardrobe deformation sequence/order is invalid")
    for field in ("required_muscles_resolved", "restored_neutral", "complete", "manual_review_required"):
        if deformation.get(field) is not True:
            raise WardrobeAuthorityError(f"wardrobe deformation probe field {field} is not true")
    if _sha(value.get("deformation_probe_sha256"), "deformation probe SHA-256") != _sha256_file(deformation_path):
        raise WardrobeAuthorityError("wardrobe deformation probe bytes changed")

    rendered = validate_render_manifest(root / "snapshots" / "wardrobe-render-set.json", body_id=body_id, package_sha256=package_sha256)
    if _sha(value.get("render_manifest_sha256"), "wardrobe render manifest SHA-256") != rendered["manifest_sha256"]:
        raise WardrobeAuthorityError("wardrobe render authority no longer matches manifest bytes")
    raw_views = value.get("render_view_sha256")
    if not isinstance(raw_views, Mapping) or set(raw_views) != set(REQUIRED_VIEWS):
        raise WardrobeAuthorityError("wardrobe render authority view hash set is invalid")
    view_hashes = {view: _sha(raw_views.get(view), f"{view} render SHA-256") for view in REQUIRED_VIEWS}
    if view_hashes != rendered["view_sha256"]:
        raise WardrobeAuthorityError("wardrobe render authority no longer matches snapshot bytes")
    return {
        "path": path,
        "value": value,
        "sha256": _sha256_file(path),
        "comparison_path": comparison_path,
        "comparison_sha256": _sha256_file(comparison_path),
        "lineage_path": lineage_path,
        "lineage_sha256": _sha256_file(lineage_path),
        "machine_path": machine_path,
        "machine_sha256": _sha256_file(machine_path),
        "deformation_path": deformation_path,
        "deformation_sha256": _sha256_file(deformation_path),
        "rendered": rendered,
        "runtime_manifest_sha256": runtime_sha,
    }


def _review_id(*, person_id: str, person_revision: str, assembly_fingerprint: str, body_package_sha256: str, bodyrig_revision: str, source_capture_sha256: str, render_authority_sha256: str) -> str:
    payload = {
        "person_id": person_id,
        "person_revision": person_revision,
        "assembly_fingerprint": assembly_fingerprint,
        "body_package_sha256": body_package_sha256,
        "bodyrig_revision": bodyrig_revision,
        "source_capture_sha256": source_capture_sha256,
        "render_authority_sha256": render_authority_sha256,
    }
    return "wardreview-" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]


def authority_dir(root: str | os.PathLike[str], person_id: str, person_revision: str, review_id: str) -> Path:
    review = str(review_id or "").strip().lower()
    if not REVIEW_ID_RE.fullmatch(review):
        raise WardrobeAuthorityError("wardrobe review id is invalid")
    return Path(root).expanduser().resolve() / "wardrobe-authorities" / str(person_id) / str(person_revision) / review


def validate_authority_structure(value: Mapping[str, Any], *, assembly_receipt: Mapping[str, Any], body_release_status: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise WardrobeAuthorityError("wardrobe human-review authority fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise WardrobeAuthorityError("wardrobe authority format/version/policy mismatch")
    try:
        assembly = _assembly_identity(assembly_receipt)
        release = _release_identity(body_release_status, assembly)
    except HandsFeetNailsAuthorityError as exc:
        raise WardrobeAuthorityError(str(exc)) from exc
    exact = {
        "person_id": assembly["person_id"], "person_revision": assembly["person_revision"],
        "assembly_fingerprint": assembly["assembly_fingerprint"], "body_revision": assembly["body_revision"],
        "body_id": assembly["body_id"], "body_package_sha256": release["package_sha256"],
    }
    for field, expected in exact.items():
        if str(value.get(field) or "").lower() != str(expected).lower():
            raise WardrobeAuthorityError(f"wardrobe authority no longer matches exact {field}")
    review_id = str(value.get("review_id") or "").lower()
    revision = str(value.get("bodyrig_revision") or "").lower()
    if not REVIEW_ID_RE.fullmatch(review_id) or not BODYRIG_REVISION_RE.fullmatch(revision):
        raise WardrobeAuthorityError("wardrobe authority review/revision identity is invalid")
    for field in (
        "source_capture_sha256", "source_manifest_sha256", "garment_inventory_sha256", "render_authority_sha256",
        "package_lineage_sha256", "comparison_authority_sha256", "runtime_manifest_sha256", "render_manifest_sha256",
        "machine_probe_sha256", "deformation_probe_sha256",
    ):
        _sha(value.get(field), field)
    source_views = value.get("source_view_sha256")
    render_views = value.get("render_view_sha256")
    if not isinstance(source_views, Mapping) or set(source_views) != set(REQUIRED_VIEWS) or not isinstance(render_views, Mapping) or set(render_views) != set(REQUIRED_VIEWS):
        raise WardrobeAuthorityError("wardrobe source/render view hash sets are invalid")
    for view in REQUIRED_VIEWS:
        _sha(source_views.get(view), f"{view} source SHA-256")
        _sha(render_views.get(view), f"{view} render SHA-256")
    garment_count = value.get("garment_count")
    if isinstance(garment_count, bool) or not isinstance(garment_count, int) or not 1 <= garment_count <= 12:
        raise WardrobeAuthorityError("wardrobe garment count is invalid")
    footwear_present = value.get("footwear_present")
    if not isinstance(footwear_present, bool) or value.get("footwear_review_required") is not footwear_present:
        raise WardrobeAuthorityError("wardrobe footwear review requirement is inconsistent")
    if footwear_present and value.get("footwear_review_passed") is not True:
        raise WardrobeAuthorityError("wardrobe source contains footwear but footwear review did not pass")
    if not footwear_present and value.get("footwear_review_passed") is not False:
        raise WardrobeAuthorityError("wardrobe footwear review pass must be false when footwear is absent")
    checklist = value.get("checklist")
    if not isinstance(checklist, Mapping) or set(checklist) != CHECKLIST_FIELDS or any(checklist.get(field) is not True for field in CHECKLIST_FIELDS):
        raise WardrobeAuthorityError("wardrobe review checklist is not fully passed")
    for field in CHECKLIST_FIELDS:
        if value.get(field) is not True:
            raise WardrobeAuthorityError(f"wardrobe authority did not pass {field}")
    note = str(value.get("quality_note") or "").strip()
    if not note or re.fullmatch(r"<[^>]+>", note) or len(note) > 4000:
        raise WardrobeAuthorityError("wardrobe review requires a real non-placeholder quality note")
    if value.get("deformation_sequence_revision") != "humanoid-muscle-sweep-v1":
        raise WardrobeAuthorityError("wardrobe review deformation sequence is invalid")
    if value.get("state") != "complete" or value.get("source_grounded") is not True or value.get("operator_supplied") is not True or value.get("production_activation") is not False:
        raise WardrobeAuthorityError("wardrobe authority is not complete non-activating operator/source authority")
    expected_id = _review_id(
        person_id=assembly["person_id"], person_revision=assembly["person_revision"],
        assembly_fingerprint=assembly["assembly_fingerprint"], body_package_sha256=release["package_sha256"],
        bodyrig_revision=revision, source_capture_sha256=str(value["source_capture_sha256"]),
        render_authority_sha256=str(value["render_authority_sha256"]),
    )
    if review_id != expected_id:
        raise WardrobeAuthorityError("wardrobe review id no longer matches exact evidence identity")
    return dict(value)


def write_authority(
    root: str | os.PathLike[str], *, assembly_receipt: Mapping[str, Any], body_release_status: Mapping[str, Any],
    source_capture_id: str, render_authority_path: str | os.PathLike[str], bodyrig_revision: str,
    checklist: Mapping[str, Any], footwear_review_passed: bool, quality_note: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    assembly = _assembly_identity(assembly_receipt)
    release = _release_identity(body_release_status, assembly)
    revision = str(bodyrig_revision or "").strip().lower()
    if not BODYRIG_REVISION_RE.fullmatch(revision):
        raise WardrobeAuthorityError("BodyRig wardrobe review revision is invalid")
    normalized = dict(checklist)
    if set(normalized) != CHECKLIST_FIELDS or any(normalized.get(field) is not True for field in CHECKLIST_FIELDS):
        raise WardrobeAuthorityError("wardrobe review requires explicit PASS for every checklist field")
    note = str(quality_note or "").strip()
    if not note or re.fullmatch(r"<[^>]+>", note) or len(note) > 4000:
        raise WardrobeAuthorityError("wardrobe review requires a real non-placeholder quality note")
    try:
        source = read_source_capture(root_path, assembly["person_id"], body_revision=assembly["body_revision"], capture_id=source_capture_id)
    except WardrobeSourceCaptureError as exc:
        raise WardrobeAuthorityError(f"wardrobe source capture failed: {exc}") from exc
    if str(source.get("bodyrig_revision") or "").lower() != revision:
        raise WardrobeAuthorityError("wardrobe source capture and human review must use same exact BodyRig revision")
    footwear_present = source.get("footwear_present") is True
    if footwear_present and footwear_review_passed is not True:
        raise WardrobeAuthorityError("source presentation contains footwear; explicit footwear review is required")
    if not footwear_present and footwear_review_passed:
        raise WardrobeAuthorityError("footwear review cannot be recorded when source inventory contains no footwear")
    render = validate_render_authority_bundle(
        render_authority_path, body_id=assembly["body_id"], package_sha256=release["package_sha256"], bodyrig_revision=revision,
    )
    source_root = capture_dir(root_path, assembly["person_id"], assembly["body_revision"], str(source["capture_id"]))
    source_manifest = source_root / "source-capture.json"
    source_sha = _sha256_file(source_manifest)
    source_view_sha = {view: str(source["views"][view]["image_sha256"]) for view in REQUIRED_VIEWS}
    garment_sha = _canonical_json_sha(source["garments"])
    review_id = _review_id(
        person_id=assembly["person_id"], person_revision=assembly["person_revision"], assembly_fingerprint=assembly["assembly_fingerprint"],
        body_package_sha256=release["package_sha256"], bodyrig_revision=revision, source_capture_sha256=source_sha,
        render_authority_sha256=render["sha256"],
    )
    target = authority_dir(root_path, assembly["person_id"], assembly["person_revision"], review_id)
    if target.exists():
        raise WardrobeAuthorityError("refusing to overwrite existing wardrobe authority")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    stage.mkdir(parents=False, exist_ok=False)
    try:
        source_out = stage / "source"
        render_out = stage / "render"
        source_out.mkdir()
        render_out.mkdir()
        for name in ["source-capture.json", *[view.replace("_", "-") + ".png" for view in REQUIRED_VIEWS]]:
            shutil.copyfile(source_root / name, source_out / name)
        for source_path, name in (
            (render["path"], "wardrobe-render-authority.json"),
            (render["comparison_path"], "comparison-authority.json"),
            (render["lineage_path"], "wardrobe-package-lineage.json"),
            (render["machine_path"], "machine-probe.json"),
            (render["deformation_path"], "deformation-probe.json"),
        ):
            shutil.copyfile(source_path, render_out / name)
        snapshot_out = render_out / "snapshots"
        snapshot_out.mkdir()
        manifest_path = Path(render["rendered"]["manifest_path"])
        shutil.copyfile(manifest_path, snapshot_out / "wardrobe-render-set.json")
        for view in REQUIRED_VIEWS:
            shutil.copyfile(manifest_path.parent / f"{view}.png", snapshot_out / f"{view}.png")
        receipt = {
            "format": FORMAT, "version": VERSION, "policy_revision": POLICY_REVISION, "review_id": review_id,
            "person_id": assembly["person_id"], "person_revision": assembly["person_revision"],
            "assembly_fingerprint": assembly["assembly_fingerprint"], "body_revision": assembly["body_revision"],
            "body_id": assembly["body_id"], "body_package_sha256": release["package_sha256"], "bodyrig_revision": revision,
            "source_capture_id": str(source["capture_id"]), "source_capture_sha256": source_sha,
            "source_manifest_sha256": str(source["source_manifest_sha256"]), "source_view_sha256": source_view_sha,
            "garment_inventory_sha256": garment_sha, "garment_count": len(source["garments"]), "footwear_present": footwear_present,
            "render_authority_sha256": render["sha256"], "package_lineage_sha256": render["lineage_sha256"],
            "comparison_authority_sha256": render["comparison_sha256"], "runtime_manifest_sha256": render["runtime_manifest_sha256"],
            "render_manifest_sha256": render["rendered"]["manifest_sha256"], "render_view_sha256": dict(render["rendered"]["view_sha256"]),
            "machine_probe_sha256": render["machine_sha256"], "deformation_probe_sha256": render["deformation_sha256"],
            "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
            "reviewed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "checklist": {field: True for field in sorted(CHECKLIST_FIELDS)}, "quality_note": note,
            "state": "complete", "source_grounded": True, "operator_supplied": True,
            **{field: True for field in sorted(CHECKLIST_FIELDS)},
            "footwear_review_required": footwear_present, "footwear_review_passed": bool(footwear_review_passed),
            "production_activation": False,
        }
        validate_authority_structure(receipt, assembly_receipt=assembly_receipt, body_release_status=body_release_status)
        (stage / "authority.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        os.replace(stage, target)
        return read_authority(root_path, assembly_receipt=assembly_receipt, body_release_status=body_release_status, review_id=review_id)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def read_authority(root: str | os.PathLike[str], *, assembly_receipt: Mapping[str, Any], body_release_status: Mapping[str, Any], review_id: str) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    assembly = _assembly_identity(assembly_receipt)
    target = authority_dir(root_path, assembly["person_id"], assembly["person_revision"], review_id)
    value = validate_authority_structure(_read_json(target / "authority.json", "wardrobe authority"), assembly_receipt=assembly_receipt, body_release_status=body_release_status)
    if value["review_id"] != review_id:
        raise WardrobeAuthorityError("wardrobe authority path/review id mismatch")
    try:
        source = read_source_capture(root_path, assembly["person_id"], body_revision=assembly["body_revision"], capture_id=str(value["source_capture_id"]))
    except WardrobeSourceCaptureError as exc:
        raise WardrobeAuthorityError(f"wardrobe source lineage failed during readback: {exc}") from exc
    canonical_source_root = capture_dir(root_path, assembly["person_id"], assembly["body_revision"], str(value["source_capture_id"]))
    frozen_source = target / "source"
    for manifest_path in (canonical_source_root / "source-capture.json", frozen_source / "source-capture.json"):
        if _sha256_file(manifest_path) != value["source_capture_sha256"]:
            raise WardrobeAuthorityError("wardrobe source-capture bytes changed after human review")
    if _canonical_json_sha(source["garments"]) != value["garment_inventory_sha256"] or len(source["garments"]) != value["garment_count"]:
        raise WardrobeAuthorityError("wardrobe garment inventory changed after human review")
    for view in REQUIRED_VIEWS:
        expected = str(value["source_view_sha256"][view])
        filename = view.replace("_", "-") + ".png"
        if _sha256_file(canonical_source_root / filename) != expected or _sha256_file(frozen_source / filename) != expected:
            raise WardrobeAuthorityError(f"{view} source presentation bytes changed after human review")
    frozen_render = target / "render"
    if _sha256_file(frozen_render / "wardrobe-render-authority.json") != value["render_authority_sha256"]:
        raise WardrobeAuthorityError("frozen wardrobe render-authority bytes changed after human review")
    render = validate_render_authority_bundle(
        frozen_render / "wardrobe-render-authority.json",
        body_id=str(value["body_id"]), package_sha256=str(value["body_package_sha256"]), bodyrig_revision=str(value["bodyrig_revision"]),
    )
    if render["lineage_sha256"] != value["package_lineage_sha256"] or render["comparison_sha256"] != value["comparison_authority_sha256"]:
        raise WardrobeAuthorityError("frozen wardrobe package/comparison lineage changed after human review")
    if render["machine_sha256"] != value["machine_probe_sha256"] or render["deformation_sha256"] != value["deformation_probe_sha256"]:
        raise WardrobeAuthorityError("frozen wardrobe machine/deformation evidence changed after human review")
    if render["rendered"]["manifest_sha256"] != value["render_manifest_sha256"] or render["rendered"]["view_sha256"] != dict(value["render_view_sha256"]):
        raise WardrobeAuthorityError("frozen wardrobe render evidence changed after human review")
    return value
