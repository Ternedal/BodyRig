from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .bridges.avatar_fidelity_components import (
    FidelityComponentError,
    validate_receipt,
    with_component_status,
)
from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .high_fidelity_component_review import (
    HighFidelityComponentReviewError,
    read_review,
    review_path,
)
from .high_fidelity_package_audit import (
    HighFidelityPackageAuditError,
    audit_high_fidelity_package,
)
from .high_fidelity_preview_jobs import ROOT_DIRNAME
from .package import MRBodyError, validate_package
from .storage import ui_jobs_dir

FORMAT = "bodyrig-high-fidelity-anatomy-promotion"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-anatomy-promotion-v1"
EMBEDDED_FORMAT = "bodyrig-body-anatomy-promotion"
PROMOTION_ROOT = ".high-fidelity-anatomy-promotions"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "preview_job_id",
    "canonical_body_id",
    "bodyrig_revision",
    "target_family",
    "source_package_sha256",
    "component_review_sha256",
    "anatomy_gate_sha256",
    "promoted_package_sha256",
    "promoted_avatar_sha256",
    "components_before",
    "components_after",
    "promotion_component",
    "production_activation",
}


class HighFidelityAnatomyPromotionError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: Any, *, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(clean):
        raise HighFidelityAnatomyPromotionError(f"{label} is not a canonical SHA-256")
    return clean


def _preview_root(job_id: str) -> Path:
    return (ui_jobs_dir() / ROOT_DIRNAME / job_id).resolve()


def _candidate_package(review: Mapping[str, Any]) -> Path:
    job_id = str(review["preview_job_id"])
    root = _preview_root(job_id)
    summary_path = (root / "anatomy" / "subject-anatomy-physical-gate.json").resolve()
    try:
        summary_path.relative_to(root)
    except ValueError as exc:
        raise HighFidelityAnatomyPromotionError("anatomy gate summary escaped its persisted preview root") from exc
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityAnatomyPromotionError("anatomy gate summary is unreadable") from exc
    if not isinstance(summary, dict):
        raise HighFidelityAnatomyPromotionError("anatomy gate summary is invalid")
    package = Path(str(summary.get("package") or "")).expanduser().resolve()
    try:
        package.relative_to(root)
    except ValueError as exc:
        raise HighFidelityAnatomyPromotionError("anatomy candidate package escaped its persisted preview root") from exc
    if not package.is_file():
        raise HighFidelityAnatomyPromotionError("anatomy candidate package is missing")
    actual = _sha256_file(package)
    expected = _canonical_sha256(review.get("candidate_package_sha256"), label="review candidate package SHA-256")
    if actual != expected or str(summary.get("package_sha256") or "").lower() != expected:
        raise HighFidelityAnatomyPromotionError("anatomy candidate package no longer matches exact reviewed bytes")
    return package


def _review_receipt_path(review: Mapping[str, Any]) -> Path:
    path = review_path(
        str(review["preview_job_id"]),
        review_vrm_sha256=str(review["review_vrm_sha256"]),
    )
    if not path.is_file():
        raise HighFidelityAnatomyPromotionError("component visual-review receipt is missing")
    return path


def _promotion_paths(review: Mapping[str, Any]) -> tuple[Path, Path]:
    source_sha = _canonical_sha256(review.get("candidate_package_sha256"), label="candidate package SHA-256")
    review_sha = _sha256_file(_review_receipt_path(review))
    root = ui_jobs_dir() / PROMOTION_ROOT / str(review["preview_job_id"])
    stem = f"{source_sha}.{review_sha}.body-anatomy"
    return root / f"{stem}.mrbody", root / f"{stem}.json"


def _promoted_avatar(
    avatar_vrm: bytes,
    *,
    review: Mapping[str, Any],
    component_review_sha256: str,
    source_package_sha256: str,
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    try:
        document, binary = _read_glb(avatar_vrm)
    except PbrMaterialError as exc:
        raise HighFidelityAnatomyPromotionError(str(exc)) from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise HighFidelityAnatomyPromotionError("BodyRig VRM metadata is missing")
    if "bodyAnatomyPromotion" in bodyrig:
        raise HighFidelityAnatomyPromotionError("candidate avatar already carries anatomy promotion metadata")
    raw = bodyrig.get("fidelityComponents")
    if not isinstance(raw, Mapping):
        raise HighFidelityAnatomyPromotionError("candidate avatar fidelity component receipt is missing")
    try:
        before = validate_receipt(raw)
    except FidelityComponentError as exc:
        raise HighFidelityAnatomyPromotionError(str(exc)) from exc
    if before["components"]["body_anatomy"] == "complete":
        raise HighFidelityAnatomyPromotionError("body anatomy is already complete in the source candidate")
    if review.get("promotion_eligibility") != {"body_anatomy": True, "hair": False, "eyes": False}:
        raise HighFidelityAnatomyPromotionError("component review does not authorize the v1 anatomy-only promotion boundary")
    try:
        after = with_component_status(before, component="body_anatomy", status="complete")
    except FidelityComponentError as exc:
        raise HighFidelityAnatomyPromotionError(str(exc)) from exc
    for component, status in before["components"].items():
        if component != "body_anatomy" and after["components"][component] != status:
            raise HighFidelityAnatomyPromotionError("anatomy promotion attempted to change another fidelity component")
    embedded = {
        "format": EMBEDDED_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "previewJobId": str(review["preview_job_id"]),
        "componentReviewSha256": component_review_sha256,
        "sourcePackageSha256": source_package_sha256,
        "anatomyGateSha256": _canonical_sha256(review.get("anatomy_gate_sha256"), label="anatomy gate SHA-256"),
        "bodyrigRevision": str(review["bodyrig_revision"]),
        "targetFamily": str(review["target_family"]),
        "component": "body_anatomy",
        "productionActivation": False,
    }
    bodyrig["fidelityComponents"] = after
    bodyrig["bodyAnatomyPromotion"] = embedded
    return _write_glb(document, binary), before, after


def _rewrite_package(source: Path, destination: Path, *, avatar_vrm: bytes) -> None:
    try:
        with zipfile.ZipFile(source, "r") as archive:
            order = [info.filename for info in archive.infolist()]
            payload = {name: archive.read(name) for name in order}
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HighFidelityAnatomyPromotionError("could not read validated anatomy candidate package") from exc
    payload["avatar.vrm"] = avatar_vrm
    checksum_names = set(order) - {"manifest.json", "checksums.json"}
    checksums = {name: _sha256_bytes(payload[name]) for name in checksum_names}
    payload["checksums.json"] = json.dumps(
        checksums,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in order:
                archive.writestr(name, payload[name])
    except FileExistsError as exc:
        raise HighFidelityAnatomyPromotionError(f"refusing to overwrite existing promoted package: {destination}") from exc
    except OSError as exc:
        raise HighFidelityAnatomyPromotionError("could not write promoted anatomy package") from exc


def _embedded_promotion(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            avatar = archive.read("avatar.vrm")
        document, _ = _read_glb(avatar)
    except (OSError, zipfile.BadZipFile, KeyError, PbrMaterialError) as exc:
        raise HighFidelityAnatomyPromotionError("could not read promoted avatar metadata") from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    value = bodyrig.get("bodyAnatomyPromotion") if isinstance(bodyrig, dict) else None
    if not isinstance(value, dict):
        raise HighFidelityAnatomyPromotionError("promoted avatar anatomy authority is missing")
    return value


def write_promotion(preview_job_id: str, *, bodyrig_revision: str) -> dict[str, Any]:
    try:
        review = read_review(preview_job_id)
    except HighFidelityComponentReviewError as exc:
        raise HighFidelityAnatomyPromotionError(f"component visual review authority failed: {exc}") from exc
    expected_revision = str(review.get("bodyrig_revision") or "").lower()
    supplied_revision = str(bodyrig_revision or "").strip().lower()
    if not SHA1_RE.fullmatch(supplied_revision) or supplied_revision != expected_revision:
        raise HighFidelityAnatomyPromotionError(
            f"anatomy promotion checkout revision mismatch: expected {expected_revision}, got {supplied_revision or 'missing'}"
        )
    source = _candidate_package(review)
    try:
        validated = validate_package(source)
        audit_before = audit_high_fidelity_package(source)
    except (MRBodyError, HighFidelityPackageAuditError) as exc:
        raise HighFidelityAnatomyPromotionError(f"source candidate package failed strict audit: {exc}") from exc
    if str(validated.manifest["id"]) != str(review["canonical_body_id"]):
        raise HighFidelityAnatomyPromotionError("source candidate body id no longer matches component review authority")

    review_receipt_path = _review_receipt_path(review)
    review_sha = _sha256_file(review_receipt_path)
    source_sha = _sha256_file(source)
    destination, receipt_path = _promotion_paths(review)
    if destination.exists() or receipt_path.exists():
        raise HighFidelityAnatomyPromotionError("refusing to overwrite existing anatomy promotion authority")

    try:
        with zipfile.ZipFile(source, "r") as archive:
            source_avatar = archive.read("avatar.vrm")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HighFidelityAnatomyPromotionError("could not read source candidate avatar") from exc
    promoted_avatar, before, after = _promoted_avatar(
        source_avatar,
        review=review,
        component_review_sha256=review_sha,
        source_package_sha256=source_sha,
    )

    package_created = False
    receipt_created = False
    try:
        _rewrite_package(source, destination, avatar_vrm=promoted_avatar)
        package_created = True
        try:
            validate_package(destination)
            audit_after = audit_high_fidelity_package(destination)
        except (MRBodyError, HighFidelityPackageAuditError) as exc:
            raise HighFidelityAnatomyPromotionError(f"promoted package failed strict audit: {exc}") from exc
        if audit_after["components"].get("body_anatomy") != "complete":
            raise HighFidelityAnatomyPromotionError("promoted package did not make body_anatomy complete")
        for component, status in audit_before["components"].items():
            if component != "body_anatomy" and audit_after["components"].get(component) != status:
                raise HighFidelityAnatomyPromotionError("promoted package changed a non-anatomy fidelity component")
        if audit_after["production_ready"] is not False:
            raise HighFidelityAnatomyPromotionError("anatomy promotion crossed the production authority boundary")
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "policy_revision": POLICY_REVISION,
            "preview_job_id": str(review["preview_job_id"]),
            "canonical_body_id": str(review["canonical_body_id"]),
            "bodyrig_revision": expected_revision,
            "target_family": str(review["target_family"]),
            "source_package_sha256": source_sha,
            "component_review_sha256": review_sha,
            "anatomy_gate_sha256": _canonical_sha256(review.get("anatomy_gate_sha256"), label="anatomy gate SHA-256"),
            "promoted_package_sha256": _sha256_file(destination),
            "promoted_avatar_sha256": _sha256_bytes(promoted_avatar),
            "components_before": dict(before["components"]),
            "components_after": dict(after["components"]),
            "promotion_component": "body_anatomy",
            "production_activation": False,
        }
        with receipt_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
        receipt_created = True
        read_promotion(preview_job_id)
        return {**receipt, "package_path": str(destination), "receipt_path": str(receipt_path)}
    except Exception:
        if receipt_created:
            receipt_path.unlink(missing_ok=True)
        if package_created:
            destination.unlink(missing_ok=True)
        raise


def read_promotion(preview_job_id: str) -> dict[str, Any]:
    try:
        review = read_review(preview_job_id)
    except HighFidelityComponentReviewError as exc:
        raise HighFidelityAnatomyPromotionError(f"component visual review authority failed: {exc}") from exc
    source = _candidate_package(review)
    destination, receipt_path = _promotion_paths(review)
    if not destination.is_file() or not receipt_path.is_file():
        raise HighFidelityAnatomyPromotionError("anatomy promotion package/receipt is missing")
    try:
        value = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityAnatomyPromotionError("anatomy promotion receipt is unreadable") from exc
    if not isinstance(value, dict) or set(value) != TOP_FIELDS:
        raise HighFidelityAnatomyPromotionError("anatomy promotion receipt fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise HighFidelityAnatomyPromotionError("anatomy promotion format/version/policy mismatch")
    review_path_value = _review_receipt_path(review)
    expected = {
        "preview_job_id": str(review["preview_job_id"]),
        "canonical_body_id": str(review["canonical_body_id"]),
        "bodyrig_revision": str(review["bodyrig_revision"]),
        "target_family": str(review["target_family"]),
        "source_package_sha256": _sha256_file(source),
        "component_review_sha256": _sha256_file(review_path_value),
        "anatomy_gate_sha256": _canonical_sha256(review.get("anatomy_gate_sha256"), label="anatomy gate SHA-256"),
        "promoted_package_sha256": _sha256_file(destination),
        "promotion_component": "body_anatomy",
        "production_activation": False,
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise HighFidelityAnatomyPromotionError(f"anatomy promotion no longer matches exact authority: {field}")
    try:
        validated = validate_package(destination)
        source_audit = audit_high_fidelity_package(source)
        promoted_audit = audit_high_fidelity_package(destination)
    except (MRBodyError, HighFidelityPackageAuditError) as exc:
        raise HighFidelityAnatomyPromotionError(f"anatomy promotion package audit failed: {exc}") from exc
    if validated.manifest["id"] != review["canonical_body_id"]:
        raise HighFidelityAnatomyPromotionError("promoted package body id changed")
    before = dict(source_audit["components"])
    after = dict(promoted_audit["components"])
    if value.get("components_before") != before or value.get("components_after") != after:
        raise HighFidelityAnatomyPromotionError("anatomy promotion component state receipt is stale")
    if after.get("body_anatomy") != "complete":
        raise HighFidelityAnatomyPromotionError("promoted package body anatomy is not complete")
    for component, status in before.items():
        if component != "body_anatomy" and after.get(component) != status:
            raise HighFidelityAnatomyPromotionError("promoted package changed non-anatomy fidelity authority")
    if promoted_audit["production_ready"] is not False or value.get("production_activation") is not False:
        raise HighFidelityAnatomyPromotionError("anatomy promotion crossed the production authority boundary")

    embedded = _embedded_promotion(destination)
    expected_embedded = {
        "format": EMBEDDED_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "previewJobId": str(review["preview_job_id"]),
        "componentReviewSha256": expected["component_review_sha256"],
        "sourcePackageSha256": expected["source_package_sha256"],
        "anatomyGateSha256": expected["anatomy_gate_sha256"],
        "bodyrigRevision": str(review["bodyrig_revision"]),
        "targetFamily": str(review["target_family"]),
        "component": "body_anatomy",
        "productionActivation": False,
    }
    if embedded != expected_embedded:
        raise HighFidelityAnatomyPromotionError("embedded anatomy promotion authority is stale or tampered")
    try:
        with zipfile.ZipFile(destination, "r") as archive:
            avatar_sha = _sha256_bytes(archive.read("avatar.vrm"))
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HighFidelityAnatomyPromotionError("promoted avatar is unreadable") from exc
    if value.get("promoted_avatar_sha256") != avatar_sha:
        raise HighFidelityAnatomyPromotionError("promoted avatar hash no longer matches receipt")
    return {**value, "package_path": str(destination), "receipt_path": str(receipt_path)}


def promotion_status(preview_job_id: str) -> dict[str, Any]:
    try:
        review = read_review(preview_job_id)
    except HighFidelityComponentReviewError as exc:
        return {"state": "blocked", "passed": False, "reason": str(exc), "production_activation": False}
    destination, receipt_path = _promotion_paths(review)
    if not destination.exists() and not receipt_path.exists():
        return {
            "state": "required",
            "passed": False,
            "reason": "Reviewed body anatomy is promotion-eligible but has not been materialized into a new candidate package.",
            "promotion_component": "body_anatomy",
            "production_activation": False,
        }
    try:
        value = read_promotion(preview_job_id)
    except HighFidelityAnatomyPromotionError as exc:
        return {"state": "invalid", "passed": False, "reason": str(exc), "production_activation": False}
    return {
        "state": "pass",
        "passed": True,
        "promotion_component": "body_anatomy",
        "promoted_package_sha256": value["promoted_package_sha256"],
        "components_after": value["components_after"],
        "production_activation": False,
    }
