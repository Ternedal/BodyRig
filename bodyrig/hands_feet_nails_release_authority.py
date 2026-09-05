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

from .hands_feet_nails_authority import (
    CHECKLIST_FIELDS,
    HandsFeetNailsAuthorityError,
    _assembly_identity,
    _release_identity,
    authority_dir as review_authority_dir,
    read_authority,
    validate_render_manifest,
)
from .hands_feet_nails_source_capture import REQUIRED_REGIONS

FORMAT = "bodyrig-hands-feet-nails-release-authority"
VERSION = 1
POLICY_REVISION = "bodyrig-hands-feet-nails-release-authority-v1"
RELEASE_ID_RE = re.compile(r"^hfnrelease-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RENDER_AUTHORITY_FORMAT = "bodyrig-hands-feet-nails-render-authority"
RENDER_AUTHORITY_FIELDS = {
    "format",
    "version",
    "bodyrig_revision",
    "body_id",
    "package_sha256",
    "runtime_manifest_sha256",
    "comparison_authority_sha256",
    "render_manifest_sha256",
    "render_region_sha256",
    "comparison_only",
    "human_review_required",
    "production_activation",
}
COMPARISON_FIELDS = {
    "format",
    "version",
    "authority",
    "bodyrig_revision",
    "runtime_manifest_sha256",
    "package_sha256",
    "physical_acceptance_authority",
    "comparison_only",
    "production_activation",
}
TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "release_id",
    "review_id",
    "person_id",
    "person_revision",
    "assembly_fingerprint",
    "body_revision",
    "body_id",
    "body_package_sha256",
    "bodyrig_revision",
    "review_authority_sha256",
    "source_capture_id",
    "source_capture_sha256",
    "source_manifest_sha256",
    "source_region_sha256",
    "render_authority_sha256",
    "comparison_authority_sha256",
    "runtime_manifest_sha256",
    "render_manifest_sha256",
    "render_region_sha256",
    "finalized_utc",
    "state",
    "source_grounded",
    "operator_supplied",
    *CHECKLIST_FIELDS,
    "production_activation",
}


class HandsFeetNailsReleaseAuthorityError(RuntimeError):
    pass


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise HandsFeetNailsReleaseAuthorityError(f"{label} is not a canonical SHA-256")
    return text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandsFeetNailsReleaseAuthorityError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise HandsFeetNailsReleaseAuthorityError(f"{label} must be a JSON object")
    return value


def _release_id(
    *,
    review_id: str,
    review_authority_sha256: str,
    render_authority_sha256: str,
    comparison_authority_sha256: str,
    body_package_sha256: str,
    bodyrig_revision: str,
) -> str:
    value = {
        "review_id": review_id,
        "review_authority_sha256": review_authority_sha256,
        "render_authority_sha256": render_authority_sha256,
        "comparison_authority_sha256": comparison_authority_sha256,
        "body_package_sha256": body_package_sha256,
        "bodyrig_revision": bodyrig_revision,
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "hfnrelease-" + hashlib.sha256(raw).hexdigest()[:32]


def release_authority_dir(
    root: str | os.PathLike[str],
    person_id: str,
    person_revision: str,
    release_id: str,
) -> Path:
    release = str(release_id or "").strip().lower()
    if not RELEASE_ID_RE.fullmatch(release):
        raise HandsFeetNailsReleaseAuthorityError("hands/feet/nails release id is invalid")
    return (
        Path(root).expanduser().resolve()
        / "hands-feet-nails-release-authorities"
        / str(person_id)
        / str(person_revision)
        / release
    )


def _validate_comparison(value: Mapping[str, Any], *, review: Mapping[str, Any]) -> dict[str, str]:
    if set(value) != COMPARISON_FIELDS:
        raise HandsFeetNailsReleaseAuthorityError("M2 comparison authority fields are not canonical")
    if value.get("format") != "bodyrig-fidelity-comparison-authority" or value.get("version") != 1:
        raise HandsFeetNailsReleaseAuthorityError("M2 comparison authority format/version mismatch")
    if value.get("authority") != "validated-package-comparison-only":
        raise HandsFeetNailsReleaseAuthorityError("M2 render provenance is not the canonical validated-package comparison path")
    if str(value.get("bodyrig_revision") or "").lower() != str(review["bodyrig_revision"]).lower():
        raise HandsFeetNailsReleaseAuthorityError("M2 comparison authority was produced by a different BodyRig revision")
    package_sha = _sha(value.get("package_sha256"), "comparison package SHA-256")
    if package_sha != str(review["body_package_sha256"]):
        raise HandsFeetNailsReleaseAuthorityError("M2 comparison authority belongs to a different body package")
    runtime_sha = _sha(value.get("runtime_manifest_sha256"), "comparison runtime manifest SHA-256")
    if (
        value.get("physical_acceptance_authority") is not False
        or value.get("comparison_only") is not True
        or value.get("production_activation") is not False
    ):
        raise HandsFeetNailsReleaseAuthorityError("M2 comparison authority crossed the human-review-only boundary")
    return {"package_sha256": package_sha, "runtime_manifest_sha256": runtime_sha}


def _validate_render_authority_bundle(
    render_authority_path: str | os.PathLike[str],
    *,
    review: Mapping[str, Any],
) -> dict[str, Any]:
    path = Path(render_authority_path).expanduser().resolve()
    if path.name != "hands-feet-nails-render-authority.json" or not path.is_file():
        raise HandsFeetNailsReleaseAuthorityError("canonical M2 render authority is missing")
    value = _read_json(path, "M2 render authority")
    if set(value) != RENDER_AUTHORITY_FIELDS:
        raise HandsFeetNailsReleaseAuthorityError("M2 render authority fields are not canonical")
    if value.get("format") != RENDER_AUTHORITY_FORMAT or value.get("version") != 1:
        raise HandsFeetNailsReleaseAuthorityError("M2 render authority format/version mismatch")
    if str(value.get("bodyrig_revision") or "").lower() != str(review["bodyrig_revision"]).lower():
        raise HandsFeetNailsReleaseAuthorityError("M2 detail renders were produced by a different BodyRig revision")
    if str(value.get("body_id") or "") != str(review["body_id"]):
        raise HandsFeetNailsReleaseAuthorityError("M2 detail renders belong to a different body id")
    if _sha(value.get("package_sha256"), "M2 render package SHA-256") != str(review["body_package_sha256"]):
        raise HandsFeetNailsReleaseAuthorityError("M2 detail renders belong to a different body package")
    if value.get("comparison_only") is not True or value.get("human_review_required") is not True or value.get("production_activation") is not False:
        raise HandsFeetNailsReleaseAuthorityError("M2 render authority crossed the review-only boundary")

    comparison_path = path.parent / "comparison-authority.json"
    if not comparison_path.is_file():
        raise HandsFeetNailsReleaseAuthorityError("M2 comparison authority is missing beside render authority")
    comparison = _read_json(comparison_path, "M2 comparison authority")
    comparison_identity = _validate_comparison(comparison, review=review)
    comparison_sha = _sha256_file(comparison_path)
    if _sha(value.get("comparison_authority_sha256"), "M2 comparison authority SHA-256") != comparison_sha:
        raise HandsFeetNailsReleaseAuthorityError("M2 render authority no longer matches exact comparison-authority bytes")
    if _sha(value.get("runtime_manifest_sha256"), "M2 runtime manifest SHA-256") != comparison_identity["runtime_manifest_sha256"]:
        raise HandsFeetNailsReleaseAuthorityError("M2 render authority runtime lineage does not match comparison authority")

    render_manifest = path.parent / "snapshots" / "hands-feet-nails-render-set.json"
    try:
        rendered = validate_render_manifest(
            render_manifest,
            body_id=str(review["body_id"]),
            package_sha256=str(review["body_package_sha256"]),
        )
    except HandsFeetNailsAuthorityError as exc:
        raise HandsFeetNailsReleaseAuthorityError(f"M2 detail render evidence failed: {exc}") from exc
    manifest_sha = _sha(value.get("render_manifest_sha256"), "M2 render manifest SHA-256")
    if manifest_sha != rendered["manifest_sha256"] or manifest_sha != str(review["render_manifest_sha256"]):
        raise HandsFeetNailsReleaseAuthorityError("M2 review and renderer authority do not bind the same detail manifest")
    regions = value.get("render_region_sha256")
    if not isinstance(regions, Mapping) or set(regions) != set(REQUIRED_REGIONS):
        raise HandsFeetNailsReleaseAuthorityError("M2 render authority region hash set is invalid")
    normalized_regions = {region: _sha(regions.get(region), f"{region} render SHA-256") for region in REQUIRED_REGIONS}
    if normalized_regions != rendered["region_sha256"] or normalized_regions != dict(review["render_region_sha256"]):
        raise HandsFeetNailsReleaseAuthorityError("M2 review and renderer authority do not bind the same detail image bytes")
    return {
        "path": path,
        "value": value,
        "sha256": _sha256_file(path),
        "comparison_path": comparison_path,
        "comparison": comparison,
        "comparison_sha256": comparison_sha,
        "runtime_manifest_sha256": comparison_identity["runtime_manifest_sha256"],
        "render_manifest_sha256": manifest_sha,
        "render_region_sha256": normalized_regions,
    }


def validate_release_authority_structure(
    value: Mapping[str, Any],
    *,
    assembly_receipt: Mapping[str, Any],
    body_release_status: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise HandsFeetNailsReleaseAuthorityError("hands/feet/nails finalized authority fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise HandsFeetNailsReleaseAuthorityError("hands/feet/nails finalized authority format/version/policy mismatch")
    try:
        assembly = _assembly_identity(assembly_receipt)
        release = _release_identity(body_release_status, assembly)
    except HandsFeetNailsAuthorityError as exc:
        raise HandsFeetNailsReleaseAuthorityError(str(exc)) from exc
    exact = {
        "person_id": assembly["person_id"],
        "person_revision": assembly["person_revision"],
        "assembly_fingerprint": assembly["assembly_fingerprint"],
        "body_revision": assembly["body_revision"],
        "body_id": assembly["body_id"],
        "body_package_sha256": release["package_sha256"],
    }
    for field, expected in exact.items():
        if str(value.get(field) or "").lower() != str(expected).lower():
            raise HandsFeetNailsReleaseAuthorityError(f"hands/feet/nails finalized authority no longer matches exact {field}")
    release_id = str(value.get("release_id") or "").lower()
    review_id = str(value.get("review_id") or "").lower()
    bodyrig_revision = str(value.get("bodyrig_revision") or "").lower()
    if not RELEASE_ID_RE.fullmatch(release_id) or not re.fullmatch(r"^hfnreview-[0-9a-f]{32}$", review_id):
        raise HandsFeetNailsReleaseAuthorityError("hands/feet/nails finalized authority id is invalid")
    if not re.fullmatch(r"^[0-9a-f]{40}$", bodyrig_revision):
        raise HandsFeetNailsReleaseAuthorityError("hands/feet/nails finalized BodyRig revision is invalid")
    for field in (
        "review_authority_sha256",
        "source_capture_sha256",
        "source_manifest_sha256",
        "render_authority_sha256",
        "comparison_authority_sha256",
        "runtime_manifest_sha256",
        "render_manifest_sha256",
    ):
        _sha(value.get(field), field)
    source_regions = value.get("source_region_sha256")
    render_regions = value.get("render_region_sha256")
    if not isinstance(source_regions, Mapping) or set(source_regions) != set(REQUIRED_REGIONS):
        raise HandsFeetNailsReleaseAuthorityError("hands/feet/nails finalized source-region hashes are invalid")
    if not isinstance(render_regions, Mapping) or set(render_regions) != set(REQUIRED_REGIONS):
        raise HandsFeetNailsReleaseAuthorityError("hands/feet/nails finalized render-region hashes are invalid")
    for region in REQUIRED_REGIONS:
        _sha(source_regions.get(region), f"{region} source SHA-256")
        _sha(render_regions.get(region), f"{region} render SHA-256")
    if value.get("state") != "complete" or value.get("source_grounded") is not True or value.get("operator_supplied") is not True:
        raise HandsFeetNailsReleaseAuthorityError("hands/feet/nails finalized authority is not complete source/operator authority")
    for field in CHECKLIST_FIELDS:
        if value.get(field) is not True:
            raise HandsFeetNailsReleaseAuthorityError(f"hands/feet/nails finalized authority did not pass {field}")
    if value.get("production_activation") is not False:
        raise HandsFeetNailsReleaseAuthorityError("hands/feet/nails finalized authority cannot independently activate production")
    expected_id = _release_id(
        review_id=review_id,
        review_authority_sha256=_sha(value["review_authority_sha256"], "review authority SHA-256"),
        render_authority_sha256=_sha(value["render_authority_sha256"], "render authority SHA-256"),
        comparison_authority_sha256=_sha(value["comparison_authority_sha256"], "comparison authority SHA-256"),
        body_package_sha256=str(value["body_package_sha256"]),
        bodyrig_revision=bodyrig_revision,
    )
    if release_id != expected_id:
        raise HandsFeetNailsReleaseAuthorityError("hands/feet/nails finalized release id no longer matches evidence identity")
    return dict(value)


def write_release_authority(
    root: str | os.PathLike[str],
    *,
    assembly_receipt: Mapping[str, Any],
    body_release_status: Mapping[str, Any],
    review_id: str,
    render_authority_path: str | os.PathLike[str],
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    try:
        review = read_authority(
            root_path,
            assembly_receipt=assembly_receipt,
            body_release_status=body_release_status,
            review_id=review_id,
        )
    except HandsFeetNailsAuthorityError as exc:
        raise HandsFeetNailsReleaseAuthorityError(f"M2 human-review authority failed: {exc}") from exc
    render = _validate_render_authority_bundle(render_authority_path, review=review)
    review_path = review_authority_dir(
        root_path,
        str(review["person_id"]),
        str(review["person_revision"]),
        str(review["review_id"]),
    ) / "authority.json"
    review_sha = _sha256_file(review_path)
    release_id = _release_id(
        review_id=str(review["review_id"]),
        review_authority_sha256=review_sha,
        render_authority_sha256=render["sha256"],
        comparison_authority_sha256=render["comparison_sha256"],
        body_package_sha256=str(review["body_package_sha256"]),
        bodyrig_revision=str(review["bodyrig_revision"]),
    )
    target = release_authority_dir(root_path, str(review["person_id"]), str(review["person_revision"]), release_id)
    if target.exists():
        raise HandsFeetNailsReleaseAuthorityError("refusing to overwrite existing finalized hands/feet/nails authority")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    stage.mkdir(parents=False, exist_ok=False)
    try:
        shutil.copyfile(render["path"], stage / "render-authority.json")
        shutil.copyfile(render["comparison_path"], stage / "comparison-authority.json")
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "policy_revision": POLICY_REVISION,
            "release_id": release_id,
            "review_id": str(review["review_id"]),
            "person_id": str(review["person_id"]),
            "person_revision": str(review["person_revision"]),
            "assembly_fingerprint": str(review["assembly_fingerprint"]),
            "body_revision": str(review["body_revision"]),
            "body_id": str(review["body_id"]),
            "body_package_sha256": str(review["body_package_sha256"]),
            "bodyrig_revision": str(review["bodyrig_revision"]),
            "review_authority_sha256": review_sha,
            "source_capture_id": str(review["source_capture_id"]),
            "source_capture_sha256": str(review["source_capture_sha256"]),
            "source_manifest_sha256": str(review["source_manifest_sha256"]),
            "source_region_sha256": dict(review["source_region_sha256"]),
            "render_authority_sha256": render["sha256"],
            "comparison_authority_sha256": render["comparison_sha256"],
            "runtime_manifest_sha256": render["runtime_manifest_sha256"],
            "render_manifest_sha256": render["render_manifest_sha256"],
            "render_region_sha256": dict(render["render_region_sha256"]),
            "finalized_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "state": "complete",
            "source_grounded": True,
            "operator_supplied": True,
            **{field: True for field in sorted(CHECKLIST_FIELDS)},
            "production_activation": False,
        }
        validate_release_authority_structure(
            receipt,
            assembly_receipt=assembly_receipt,
            body_release_status=body_release_status,
        )
        (stage / "authority.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(stage, target)
        return read_release_authority(
            root_path,
            assembly_receipt=assembly_receipt,
            body_release_status=body_release_status,
            release_id=release_id,
        )
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def read_release_authority(
    root: str | os.PathLike[str],
    *,
    assembly_receipt: Mapping[str, Any],
    body_release_status: Mapping[str, Any],
    release_id: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    assembly = _assembly_identity(assembly_receipt)
    target = release_authority_dir(root_path, assembly["person_id"], assembly["person_revision"], release_id)
    path = target / "authority.json"
    if not path.is_file():
        raise HandsFeetNailsReleaseAuthorityError("finalized hands/feet/nails authority is missing")
    value = validate_release_authority_structure(
        _read_json(path, "finalized hands/feet/nails authority"),
        assembly_receipt=assembly_receipt,
        body_release_status=body_release_status,
    )
    try:
        review = read_authority(
            root_path,
            assembly_receipt=assembly_receipt,
            body_release_status=body_release_status,
            review_id=str(value["review_id"]),
        )
    except HandsFeetNailsAuthorityError as exc:
        raise HandsFeetNailsReleaseAuthorityError(f"finalized M2 source/review lineage failed: {exc}") from exc
    review_path = review_authority_dir(
        root_path,
        str(review["person_id"]),
        str(review["person_revision"]),
        str(review["review_id"]),
    ) / "authority.json"
    if _sha256_file(review_path) != value["review_authority_sha256"]:
        raise HandsFeetNailsReleaseAuthorityError("M2 human-review authority bytes changed after finalization")
    for field in (
        "person_id",
        "person_revision",
        "assembly_fingerprint",
        "body_revision",
        "body_id",
        "body_package_sha256",
        "bodyrig_revision",
        "source_capture_id",
        "source_capture_sha256",
        "source_manifest_sha256",
        "render_manifest_sha256",
    ):
        if str(review[field]).lower() != str(value[field]).lower():
            raise HandsFeetNailsReleaseAuthorityError(f"finalized M2 authority no longer matches reviewed {field}")
    if dict(review["source_region_sha256"]) != dict(value["source_region_sha256"]) or dict(review["render_region_sha256"]) != dict(value["render_region_sha256"]):
        raise HandsFeetNailsReleaseAuthorityError("finalized M2 authority region hashes no longer match human review")

    render_path = target / "render-authority.json"
    comparison_path = target / "comparison-authority.json"
    if _sha256_file(render_path) != value["render_authority_sha256"]:
        raise HandsFeetNailsReleaseAuthorityError("frozen M2 render-authority bytes changed after finalization")
    if _sha256_file(comparison_path) != value["comparison_authority_sha256"]:
        raise HandsFeetNailsReleaseAuthorityError("frozen M2 comparison-authority bytes changed after finalization")
    render_value = _read_json(render_path, "frozen M2 render authority")
    if set(render_value) != RENDER_AUTHORITY_FIELDS or render_value.get("format") != RENDER_AUTHORITY_FORMAT or render_value.get("version") != 1:
        raise HandsFeetNailsReleaseAuthorityError("frozen M2 render authority is invalid")
    if str(render_value.get("bodyrig_revision") or "").lower() != str(value["bodyrig_revision"]).lower():
        raise HandsFeetNailsReleaseAuthorityError("frozen M2 render revision no longer matches final authority")
    if str(render_value.get("body_id") or "") != str(value["body_id"]) or _sha(render_value.get("package_sha256"), "frozen render package SHA-256") != str(value["body_package_sha256"]):
        raise HandsFeetNailsReleaseAuthorityError("frozen M2 render identity no longer matches final authority")
    if _sha(render_value.get("runtime_manifest_sha256"), "frozen runtime SHA-256") != str(value["runtime_manifest_sha256"]):
        raise HandsFeetNailsReleaseAuthorityError("frozen M2 runtime lineage no longer matches final authority")
    if _sha(render_value.get("comparison_authority_sha256"), "frozen comparison SHA-256") != str(value["comparison_authority_sha256"]):
        raise HandsFeetNailsReleaseAuthorityError("frozen M2 render authority no longer binds exact comparison authority")
    if _sha(render_value.get("render_manifest_sha256"), "frozen detail manifest SHA-256") != str(value["render_manifest_sha256"]):
        raise HandsFeetNailsReleaseAuthorityError("frozen M2 render authority no longer binds exact detail manifest")
    if dict(render_value.get("render_region_sha256") or {}) != dict(value["render_region_sha256"]):
        raise HandsFeetNailsReleaseAuthorityError("frozen M2 render authority no longer binds exact detail images")
    if render_value.get("comparison_only") is not True or render_value.get("human_review_required") is not True or render_value.get("production_activation") is not False:
        raise HandsFeetNailsReleaseAuthorityError("frozen M2 render authority crossed review-only boundary")
    comparison = _read_json(comparison_path, "frozen M2 comparison authority")
    identity = _validate_comparison(comparison, review=review)
    if identity["runtime_manifest_sha256"] != str(value["runtime_manifest_sha256"]):
        raise HandsFeetNailsReleaseAuthorityError("frozen M2 comparison runtime lineage no longer matches final authority")
    return value
