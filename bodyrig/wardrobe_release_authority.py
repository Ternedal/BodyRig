from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .hands_feet_nails_authority import HandsFeetNailsAuthorityError, _assembly_identity, _release_identity
from .wardrobe_authority import (
    CHECKLIST_FIELDS,
    WardrobeAuthorityError,
    _sha256_file,
    authority_dir as review_authority_dir,
    read_authority,
    validate_render_authority_bundle,
)
from .wardrobe_source_capture import REQUIRED_VIEWS

FORMAT = "bodyrig-wardrobe-release-authority"
VERSION = 1
POLICY_REVISION = "bodyrig-wardrobe-release-authority-v1"
RELEASE_ID_RE = re.compile(r"^wardrelease-[0-9a-f]{32}$")
REVIEW_ID_RE = re.compile(r"^wardreview-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
TOP_FIELDS = {
    "format", "version", "policy_revision", "release_id", "review_id", "person_id", "person_revision",
    "assembly_fingerprint", "body_revision", "body_id", "body_package_sha256", "bodyrig_revision",
    "review_authority_sha256", "source_capture_id", "source_capture_sha256", "source_manifest_sha256",
    "source_view_sha256", "garment_inventory_sha256", "garment_count", "footwear_present",
    "render_authority_sha256", "package_lineage_sha256", "comparison_authority_sha256",
    "runtime_manifest_sha256", "render_manifest_sha256", "render_view_sha256", "machine_probe_sha256",
    "deformation_probe_sha256", "deformation_sequence_revision", "finalized_utc", "state", "source_grounded",
    "operator_supplied", *CHECKLIST_FIELDS, "footwear_review_required", "footwear_review_passed",
    "production_activation",
}


class WardrobeReleaseAuthorityError(RuntimeError):
    pass


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise WardrobeReleaseAuthorityError(f"{label} is not a canonical SHA-256")
    return text


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WardrobeReleaseAuthorityError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise WardrobeReleaseAuthorityError(f"{label} must be a JSON object")
    return value


def _release_id(*, review_id: str, review_authority_sha256: str, render_authority_sha256: str, package_lineage_sha256: str, deformation_probe_sha256: str, body_package_sha256: str, bodyrig_revision: str) -> str:
    payload = {
        "review_id": review_id,
        "review_authority_sha256": review_authority_sha256,
        "render_authority_sha256": render_authority_sha256,
        "package_lineage_sha256": package_lineage_sha256,
        "deformation_probe_sha256": deformation_probe_sha256,
        "body_package_sha256": body_package_sha256,
        "bodyrig_revision": bodyrig_revision,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "wardrelease-" + hashlib.sha256(raw).hexdigest()[:32]


def release_authority_dir(root: str | os.PathLike[str], person_id: str, person_revision: str, release_id: str) -> Path:
    release = str(release_id or "").strip().lower()
    if not RELEASE_ID_RE.fullmatch(release):
        raise WardrobeReleaseAuthorityError("wardrobe release id is invalid")
    return Path(root).expanduser().resolve() / "wardrobe-release-authorities" / str(person_id) / str(person_revision) / release


def validate_release_authority_structure(value: Mapping[str, Any], *, assembly_receipt: Mapping[str, Any], body_release_status: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise WardrobeReleaseAuthorityError("finalized wardrobe authority fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise WardrobeReleaseAuthorityError("finalized wardrobe authority format/version/policy mismatch")
    try:
        assembly = _assembly_identity(assembly_receipt)
        release = _release_identity(body_release_status, assembly)
    except HandsFeetNailsAuthorityError as exc:
        raise WardrobeReleaseAuthorityError(str(exc)) from exc
    exact = {
        "person_id": assembly["person_id"], "person_revision": assembly["person_revision"],
        "assembly_fingerprint": assembly["assembly_fingerprint"], "body_revision": assembly["body_revision"],
        "body_id": assembly["body_id"], "body_package_sha256": release["package_sha256"],
    }
    for field, expected in exact.items():
        if str(value.get(field) or "").lower() != str(expected).lower():
            raise WardrobeReleaseAuthorityError(f"finalized wardrobe authority no longer matches exact {field}")
    release_id = str(value.get("release_id") or "").lower()
    review_id = str(value.get("review_id") or "").lower()
    revision = str(value.get("bodyrig_revision") or "").lower()
    if not RELEASE_ID_RE.fullmatch(release_id) or not REVIEW_ID_RE.fullmatch(review_id) or not SHA40_RE.fullmatch(revision):
        raise WardrobeReleaseAuthorityError("finalized wardrobe authority id/revision is invalid")
    for field in (
        "review_authority_sha256", "source_capture_sha256", "source_manifest_sha256", "garment_inventory_sha256",
        "render_authority_sha256", "package_lineage_sha256", "comparison_authority_sha256", "runtime_manifest_sha256",
        "render_manifest_sha256", "machine_probe_sha256", "deformation_probe_sha256",
    ):
        _sha(value.get(field), field)
    source_views = value.get("source_view_sha256")
    render_views = value.get("render_view_sha256")
    if not isinstance(source_views, Mapping) or set(source_views) != set(REQUIRED_VIEWS) or not isinstance(render_views, Mapping) or set(render_views) != set(REQUIRED_VIEWS):
        raise WardrobeReleaseAuthorityError("finalized wardrobe source/render view hashes are invalid")
    for view in REQUIRED_VIEWS:
        _sha(source_views.get(view), f"{view} source SHA-256")
        _sha(render_views.get(view), f"{view} render SHA-256")
    garment_count = value.get("garment_count")
    if isinstance(garment_count, bool) or not isinstance(garment_count, int) or not 1 <= garment_count <= 12:
        raise WardrobeReleaseAuthorityError("finalized wardrobe garment count is invalid")
    footwear_present = value.get("footwear_present")
    if not isinstance(footwear_present, bool) or value.get("footwear_review_required") is not footwear_present:
        raise WardrobeReleaseAuthorityError("finalized wardrobe footwear review requirement is inconsistent")
    if footwear_present and value.get("footwear_review_passed") is not True:
        raise WardrobeReleaseAuthorityError("finalized wardrobe footwear review is missing")
    if not footwear_present and value.get("footwear_review_passed") is not False:
        raise WardrobeReleaseAuthorityError("finalized wardrobe footwear pass must be false when absent")
    for field in CHECKLIST_FIELDS:
        if value.get(field) is not True:
            raise WardrobeReleaseAuthorityError(f"finalized wardrobe authority did not pass {field}")
    if value.get("deformation_sequence_revision") != "humanoid-muscle-sweep-v1":
        raise WardrobeReleaseAuthorityError("finalized wardrobe deformation sequence is invalid")
    if value.get("state") != "complete" or value.get("source_grounded") is not True or value.get("operator_supplied") is not True or value.get("production_activation") is not False:
        raise WardrobeReleaseAuthorityError("finalized wardrobe authority is not complete non-activating source/operator authority")
    expected_id = _release_id(
        review_id=review_id,
        review_authority_sha256=_sha(value["review_authority_sha256"], "review authority SHA-256"),
        render_authority_sha256=_sha(value["render_authority_sha256"], "render authority SHA-256"),
        package_lineage_sha256=_sha(value["package_lineage_sha256"], "package lineage SHA-256"),
        deformation_probe_sha256=_sha(value["deformation_probe_sha256"], "deformation probe SHA-256"),
        body_package_sha256=str(value["body_package_sha256"]),
        bodyrig_revision=revision,
    )
    if release_id != expected_id:
        raise WardrobeReleaseAuthorityError("finalized wardrobe release id no longer matches exact evidence identity")
    return dict(value)


def write_release_authority(root: str | os.PathLike[str], *, assembly_receipt: Mapping[str, Any], body_release_status: Mapping[str, Any], review_id: str, bodyrig_revision: str) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    revision = str(bodyrig_revision or "").strip().lower()
    if not SHA40_RE.fullmatch(revision):
        raise WardrobeReleaseAuthorityError("finalized wardrobe BodyRig revision is invalid")
    try:
        review = read_authority(root_path, assembly_receipt=assembly_receipt, body_release_status=body_release_status, review_id=review_id)
    except WardrobeAuthorityError as exc:
        raise WardrobeReleaseAuthorityError(f"M3 human-review authority failed: {exc}") from exc
    if str(review["bodyrig_revision"]).lower() != revision:
        raise WardrobeReleaseAuthorityError("wardrobe finalization must run from exact BodyRig revision that produced/reviewed M3 evidence")
    review_root = review_authority_dir(root_path, str(review["person_id"]), str(review["person_revision"]), str(review["review_id"]))
    review_path = review_root / "authority.json"
    review_sha = _sha256_file(review_path)
    render_root = review_root / "render"
    render = validate_render_authority_bundle(
        render_root / "wardrobe-render-authority.json",
        body_id=str(review["body_id"]), package_sha256=str(review["body_package_sha256"]), bodyrig_revision=revision,
    )
    release_id = _release_id(
        review_id=str(review["review_id"]), review_authority_sha256=review_sha,
        render_authority_sha256=render["sha256"], package_lineage_sha256=render["lineage_sha256"],
        deformation_probe_sha256=render["deformation_sha256"], body_package_sha256=str(review["body_package_sha256"]),
        bodyrig_revision=revision,
    )
    target = release_authority_dir(root_path, str(review["person_id"]), str(review["person_revision"]), release_id)
    if target.exists():
        raise WardrobeReleaseAuthorityError("refusing to overwrite existing finalized wardrobe authority")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    stage.mkdir(parents=False, exist_ok=False)
    try:
        shutil.copyfile(review_path, stage / "review-authority.json")
        frozen_render = stage / "render"
        shutil.copytree(render_root, frozen_render)
        receipt = {
            "format": FORMAT, "version": VERSION, "policy_revision": POLICY_REVISION, "release_id": release_id,
            "review_id": str(review["review_id"]), "person_id": str(review["person_id"]),
            "person_revision": str(review["person_revision"]), "assembly_fingerprint": str(review["assembly_fingerprint"]),
            "body_revision": str(review["body_revision"]), "body_id": str(review["body_id"]),
            "body_package_sha256": str(review["body_package_sha256"]), "bodyrig_revision": revision,
            "review_authority_sha256": review_sha, "source_capture_id": str(review["source_capture_id"]),
            "source_capture_sha256": str(review["source_capture_sha256"]), "source_manifest_sha256": str(review["source_manifest_sha256"]),
            "source_view_sha256": dict(review["source_view_sha256"]), "garment_inventory_sha256": str(review["garment_inventory_sha256"]),
            "garment_count": int(review["garment_count"]), "footwear_present": bool(review["footwear_present"]),
            "render_authority_sha256": render["sha256"], "package_lineage_sha256": render["lineage_sha256"],
            "comparison_authority_sha256": render["comparison_sha256"], "runtime_manifest_sha256": render["runtime_manifest_sha256"],
            "render_manifest_sha256": render["rendered"]["manifest_sha256"], "render_view_sha256": dict(render["rendered"]["view_sha256"]),
            "machine_probe_sha256": render["machine_sha256"], "deformation_probe_sha256": render["deformation_sha256"],
            "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
            "finalized_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "state": "complete", "source_grounded": True, "operator_supplied": True,
            **{field: True for field in sorted(CHECKLIST_FIELDS)},
            "footwear_review_required": bool(review["footwear_review_required"]),
            "footwear_review_passed": bool(review["footwear_review_passed"]),
            "production_activation": False,
        }
        validate_release_authority_structure(receipt, assembly_receipt=assembly_receipt, body_release_status=body_release_status)
        (stage / "authority.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        os.replace(stage, target)
        return read_release_authority(root_path, assembly_receipt=assembly_receipt, body_release_status=body_release_status, release_id=release_id)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def read_release_authority(root: str | os.PathLike[str], *, assembly_receipt: Mapping[str, Any], body_release_status: Mapping[str, Any], release_id: str) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    assembly = _assembly_identity(assembly_receipt)
    target = release_authority_dir(root_path, assembly["person_id"], assembly["person_revision"], release_id)
    value = validate_release_authority_structure(_read_json(target / "authority.json", "finalized wardrobe authority"), assembly_receipt=assembly_receipt, body_release_status=body_release_status)
    try:
        review = read_authority(root_path, assembly_receipt=assembly_receipt, body_release_status=body_release_status, review_id=str(value["review_id"]))
    except WardrobeAuthorityError as exc:
        raise WardrobeReleaseAuthorityError(f"finalized M3 source/review lineage failed: {exc}") from exc
    review_root = review_authority_dir(root_path, str(review["person_id"]), str(review["person_revision"]), str(review["review_id"]))
    review_path = review_root / "authority.json"
    if _sha256_file(review_path) != value["review_authority_sha256"] or _sha256_file(target / "review-authority.json") != value["review_authority_sha256"]:
        raise WardrobeReleaseAuthorityError("wardrobe human-review authority bytes changed after finalization")
    for field in (
        "person_id", "person_revision", "assembly_fingerprint", "body_revision", "body_id", "body_package_sha256",
        "bodyrig_revision", "source_capture_id", "source_capture_sha256", "source_manifest_sha256",
        "garment_inventory_sha256", "garment_count", "footwear_present", "footwear_review_required", "footwear_review_passed",
    ):
        if review[field] != value[field]:
            raise WardrobeReleaseAuthorityError(f"finalized wardrobe authority no longer matches reviewed {field}")
    if dict(review["source_view_sha256"]) != dict(value["source_view_sha256"]):
        raise WardrobeReleaseAuthorityError("finalized wardrobe source-view hashes no longer match human review")
    for field in CHECKLIST_FIELDS:
        if review[field] is not True or value[field] is not True:
            raise WardrobeReleaseAuthorityError(f"finalized wardrobe review field {field} is no longer a PASS")
    frozen_render = target / "render"
    render = validate_render_authority_bundle(
        frozen_render / "wardrobe-render-authority.json",
        body_id=str(value["body_id"]), package_sha256=str(value["body_package_sha256"]), bodyrig_revision=str(value["bodyrig_revision"]),
    )
    expected_pairs = {
        "render_authority_sha256": render["sha256"], "package_lineage_sha256": render["lineage_sha256"],
        "comparison_authority_sha256": render["comparison_sha256"], "runtime_manifest_sha256": render["runtime_manifest_sha256"],
        "render_manifest_sha256": render["rendered"]["manifest_sha256"], "machine_probe_sha256": render["machine_sha256"],
        "deformation_probe_sha256": render["deformation_sha256"],
    }
    for field, expected in expected_pairs.items():
        if value[field] != expected:
            raise WardrobeReleaseAuthorityError(f"finalized wardrobe {field} no longer matches frozen evidence")
    if dict(value["render_view_sha256"]) != dict(render["rendered"]["view_sha256"]):
        raise WardrobeReleaseAuthorityError("finalized wardrobe render-view hashes no longer match frozen evidence")
    return value
