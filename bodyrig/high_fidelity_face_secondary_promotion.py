from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .bridges.avatar_fidelity_components import (
    FidelityComponentError,
    validate_receipt,
    with_face_secondary_receipt,
)
from .bridges.face_secondary_fidelity import (
    REQUIRED_SUBCOMPONENTS,
    FaceSecondaryFidelityError,
    validate_face_secondary_receipt,
    with_face_secondary_status,
)
from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .high_fidelity_face_secondary_review import (
    HighFidelityFaceSecondaryReviewError,
    read_review,
)
from .high_fidelity_face_secondary_runtime import (
    HighFidelityFaceSecondaryRuntimeError,
    read_runtime,
)
from .high_fidelity_package_audit import HighFidelityPackageAuditError, audit_high_fidelity_package
from .package import MRBodyError, validate_package

FORMAT = "bodyrig-high-fidelity-face-secondary-promotion"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-face-secondary-promotion-v1"
EMBEDDED_FORMAT = "bodyrig-face-secondary-promotion"
PACKAGE_NAME = "promoted.mrbody"
RECEIPT_NAME = "promotion.json"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")


class HighFidelityFaceSecondaryPromotionError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(clean):
        raise HighFidelityFaceSecondaryPromotionError(f"{label} is not a canonical SHA-256")
    return clean


def _revision(value: Any, *, label: str = "BodyRig revision") -> str:
    clean = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(clean):
        raise HighFidelityFaceSecondaryPromotionError(f"{label} is not a canonical Git SHA")
    return clean


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityFaceSecondaryPromotionError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise HighFidelityFaceSecondaryPromotionError(f"{label} must be a JSON object")
    return value


def _bodyrig(document: Mapping[str, Any]) -> dict[str, Any]:
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, Mapping) else None
    if not isinstance(bodyrig, dict):
        raise HighFidelityFaceSecondaryPromotionError("avatar lacks mutable BodyRig metadata")
    return bodyrig


def _package_avatar(path: Path) -> tuple[bytes, str]:
    try:
        validated = validate_package(path)
        with zipfile.ZipFile(path, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (MRBodyError, OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HighFidelityFaceSecondaryPromotionError("source package is invalid or lacks avatar.vrm") from exc
    return avatar, str(validated.manifest["id"])


def _rewrite_package(source: Path, destination: Path, *, avatar_vrm: bytes) -> None:
    try:
        with zipfile.ZipFile(source, "r") as archive:
            order = [info.filename for info in archive.infolist()]
            payload = {name: archive.read(name) for name in order}
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HighFidelityFaceSecondaryPromotionError("could not read source package") from exc
    if "avatar.vrm" not in payload or "checksums.json" not in payload:
        raise HighFidelityFaceSecondaryPromotionError("source package lacks canonical avatar/checksum files")
    payload["avatar.vrm"] = avatar_vrm
    checksum_names = set(order) - {"manifest.json", "checksums.json"}
    payload["checksums.json"] = json.dumps(
        {name: _sha256_bytes(payload[name]) for name in checksum_names},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    try:
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in order:
                archive.writestr(name, payload[name])
    except FileExistsError as exc:
        raise HighFidelityFaceSecondaryPromotionError("promoted package is create-only") from exc
    except OSError as exc:
        raise HighFidelityFaceSecondaryPromotionError("could not write promoted package") from exc


def _completed_face_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        receipt = validate_face_secondary_receipt(value)
        for component in REQUIRED_SUBCOMPONENTS:
            receipt = with_face_secondary_status(
                receipt,
                component=component,
                status="complete",
                semantic_vertex_map_authority="licensed-smplx-verified",
            )
    except FaceSecondaryFidelityError as exc:
        raise HighFidelityFaceSecondaryPromotionError(str(exc)) from exc
    if receipt["components"] != {component: "complete" for component in REQUIRED_SUBCOMPONENTS}:
        raise HighFidelityFaceSecondaryPromotionError("not all face-secondary subcomponents became complete")
    if receipt["faceSecondaryReady"] is not True or receipt["blockers"] != []:
        raise HighFidelityFaceSecondaryPromotionError("nested face-secondary receipt did not become ready")
    if receipt["semanticVertexMapAuthority"] != "licensed-smplx-verified":
        raise HighFidelityFaceSecondaryPromotionError("face-secondary semantic authority is not canonical")
    if receipt["productionReady"] is not False or receipt["humanReviewRequired"] is not True:
        raise HighFidelityFaceSecondaryPromotionError("nested face-secondary receipt crossed its authority boundary")
    return receipt


def _authority(
    preparation_dir: Path,
    runtime_dir: Path,
    render_dir: Path,
    human_review_dir: Path,
    source_package: Path,
) -> tuple[dict[str, Any], dict[str, Any], bytes, str]:
    try:
        review = read_review(preparation_dir, runtime_dir, render_dir, human_review_dir)
        runtime = read_runtime(runtime_dir)
    except (HighFidelityFaceSecondaryReviewError, HighFidelityFaceSecondaryRuntimeError) as exc:
        raise HighFidelityFaceSecondaryPromotionError(str(exc)) from exc
    if review.get("faceSecondaryPromotionEligible") is not True or review.get("humanReviewComplete") is not True:
        raise HighFidelityFaceSecondaryPromotionError("face-secondary human review is not promotion-eligible")
    if review.get("faceSecondaryComponentAuthority") is not False or review.get("packageMutationPerformed") is not False or review.get("productionActivation") is not False:
        raise HighFidelityFaceSecondaryPromotionError("human review crossed pre-promotion authority boundary")
    source_sha = _sha256_file(source_package)
    if review.get("sourcePackageSha256") != source_sha or runtime.get("sourcePackageSha256") != source_sha:
        raise HighFidelityFaceSecondaryPromotionError("human review/runtime target different source package bytes")
    if review.get("sourceRuntimeReceiptSha256") != _sha256_file(Path(runtime["receiptPath"])):
        raise HighFidelityFaceSecondaryPromotionError("human review no longer binds exact runtime receipt bytes")
    review_vrm_path = Path(runtime["reviewVrmPath"]).resolve()
    review_vrm = review_vrm_path.read_bytes()
    if review.get("sourceReviewVrmSha256") != _sha256_bytes(review_vrm) or runtime.get("reviewVrmSha256") != _sha256_bytes(review_vrm):
        raise HighFidelityFaceSecondaryPromotionError("human review/runtime no longer bind exact review VRM bytes")
    return review, runtime, review_vrm, source_sha


def _build_promoted_avatar(
    *,
    source_avatar: bytes,
    review_vrm: bytes,
    source_package_sha: str,
    review: Mapping[str, Any],
    runtime: Mapping[str, Any],
    promotion_revision: str,
    human_review_sha: str,
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    try:
        source_document, _source_binary = _read_glb(source_avatar)
        review_document, review_binary = _read_glb(review_vrm)
    except PbrMaterialError as exc:
        raise HighFidelityFaceSecondaryPromotionError(str(exc)) from exc
    source_bodyrig = _bodyrig(source_document)
    promoted_bodyrig = _bodyrig(review_document)
    if promoted_bodyrig.get("fidelityComponents") != source_bodyrig.get("fidelityComponents") or promoted_bodyrig.get("faceSecondaryFidelity") != source_bodyrig.get("faceSecondaryFidelity"):
        raise HighFidelityFaceSecondaryPromotionError("review runtime changed fidelity authority before promotion")
    review_meta = promoted_bodyrig.get("faceSecondaryReviewRuntime")
    if not isinstance(review_meta, dict):
        raise HighFidelityFaceSecondaryPromotionError("review VRM lacks embedded face-secondary review metadata")
    if review_meta.get("sourcePackageSha256") != source_package_sha or review_meta.get("bodyrigRevision") != runtime.get("bodyrigRevision"):
        raise HighFidelityFaceSecondaryPromotionError("embedded face-secondary review metadata is stale")
    if review_meta.get("genericSecondaryAnatomy") is not None:
        # v1 runtime keeps generic disclosure in the receipt; embedded metadata uses explicit geometry method fields.
        raise HighFidelityFaceSecondaryPromotionError("unexpected genericSecondaryAnatomy field in embedded v1 runtime metadata")
    if review_meta.get("sourceDerivedIdentitySynthesis") is not False or review_meta.get("generativeIdentitySynthesis") is not False:
        raise HighFidelityFaceSecondaryPromotionError("review VRM crossed identity-synthesis boundary")

    try:
        before = validate_receipt(promoted_bodyrig.get("fidelityComponents", {}))
        nested_before = validate_face_secondary_receipt(promoted_bodyrig.get("faceSecondaryFidelity", {}))
    except (FidelityComponentError, FaceSecondaryFidelityError) as exc:
        raise HighFidelityFaceSecondaryPromotionError(str(exc)) from exc
    nested_after = _completed_face_receipt(nested_before)
    try:
        after = with_face_secondary_receipt(before, face_secondary_receipt=nested_after)
    except FidelityComponentError as exc:
        raise HighFidelityFaceSecondaryPromotionError(str(exc)) from exc
    if after["components"].get("face_secondary") != "complete":
        raise HighFidelityFaceSecondaryPromotionError("top-level face_secondary did not derive from nested completion")
    for component, status in before["components"].items():
        if component != "face_secondary" and after["components"].get(component) != status:
            raise HighFidelityFaceSecondaryPromotionError("face-secondary promotion attempted to change another component")

    del promoted_bodyrig["faceSecondaryReviewRuntime"]
    embedded = {
        "format": EMBEDDED_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "promotionBodyRigRevision": promotion_revision,
        "canonicalBodyId": str(review["canonicalBodyId"]),
        "sourcePackageSha256": source_package_sha,
        "reviewRuntimeReceiptSha256": _sha(review["sourceRuntimeReceiptSha256"], label="review runtime receipt SHA"),
        "reviewVrmSha256": _sha(review["sourceReviewVrmSha256"], label="review VRM SHA"),
        "previewAuthoritySha256": _sha(review["previewAuthoritySha256"], label="preview authority SHA"),
        "humanReviewReceiptSha256": human_review_sha,
        "semanticAnchorAuthority": str(runtime["semanticAnchorAuthority"]),
        "semanticVertexMapAuthority": "licensed-smplx-verified",
        "genericSecondaryAnatomy": True,
        "genericGeometryComponents": ["mouth_interior", "teeth", "eyelashes"],
        "sourceAppearanceComponents": ["eyebrow_appearance", "lip_boundary"],
        "sourceDerivedDentalIdentity": False,
        "sourceDerivedIdentitySynthesis": False,
        "generativeIdentitySynthesis": False,
        "component": "face_secondary",
        "productionActivation": False,
    }
    promoted_bodyrig["faceSecondaryFidelity"] = nested_after
    promoted_bodyrig["fidelityComponents"] = after
    promoted_bodyrig["faceSecondaryPromotion"] = embedded
    promoted_avatar = _write_glb(review_document, review_binary)
    return promoted_avatar, before, after


def write_promotion(
    *,
    preparation_dir: str | Path,
    runtime_dir: str | Path,
    render_dir: str | Path,
    human_review_dir: str | Path,
    source_package_path: str | Path,
    output_dir: str | Path,
    promotion_bodyrig_revision: str,
) -> dict[str, Any]:
    prep_root = Path(preparation_dir).expanduser().resolve()
    runtime_root = Path(runtime_dir).expanduser().resolve()
    render_root = Path(render_dir).expanduser().resolve()
    human_root = Path(human_review_dir).expanduser().resolve()
    source = Path(source_package_path).expanduser().resolve()
    final_root = Path(output_dir).expanduser().resolve()
    promotion_revision = _revision(promotion_bodyrig_revision)
    if final_root.exists():
        raise HighFidelityFaceSecondaryPromotionError("face-secondary promotion output is create-only")
    if not source.is_file():
        raise HighFidelityFaceSecondaryPromotionError("source promoted package is missing")

    review, runtime, review_vrm, source_sha = _authority(prep_root, runtime_root, render_root, human_root, source)
    source_avatar, body_id = _package_avatar(source)
    if body_id != review.get("canonicalBodyId") or body_id != runtime.get("canonicalBodyId"):
        raise HighFidelityFaceSecondaryPromotionError("face-secondary authority targets a different body identity")
    human_review_path = Path(review["reviewPath"]).resolve()
    human_review_sha = _sha256_file(human_review_path)
    promoted_avatar, before, after = _build_promoted_avatar(
        source_avatar=source_avatar,
        review_vrm=review_vrm,
        source_package_sha=source_sha,
        review=review,
        runtime=runtime,
        promotion_revision=promotion_revision,
        human_review_sha=human_review_sha,
    )

    final_root.parent.mkdir(parents=True, exist_ok=True)
    staging = final_root.with_name(f".{final_root.name}.partial-{uuid.uuid4().hex}")
    staging.mkdir()
    package_path = staging / PACKAGE_NAME
    receipt_path = staging / RECEIPT_NAME
    moved = False
    verified = False
    try:
        _rewrite_package(source, package_path, avatar_vrm=promoted_avatar)
        try:
            validated = validate_package(package_path)
            audit = audit_high_fidelity_package(package_path)
        except (MRBodyError, HighFidelityPackageAuditError) as exc:
            raise HighFidelityFaceSecondaryPromotionError(f"promoted package failed strict audit: {exc}") from exc
        if str(validated.manifest["id"]) != body_id:
            raise HighFidelityFaceSecondaryPromotionError("promoted package changed canonical body id")
        if audit["face_secondary_components"] != {component: "complete" for component in REQUIRED_SUBCOMPONENTS}:
            raise HighFidelityFaceSecondaryPromotionError("promoted package did not complete all face-secondary subcomponents")
        if audit["face_secondary_ready"] is not True or audit["components"].get("face_secondary") != "complete":
            raise HighFidelityFaceSecondaryPromotionError("promoted package did not make face_secondary complete")
        for component, status in before["components"].items():
            if component != "face_secondary" and audit["components"].get(component) != status:
                raise HighFidelityFaceSecondaryPromotionError("promoted package changed another fidelity component")
        if audit["production_ready"] is not False:
            raise HighFidelityFaceSecondaryPromotionError("face-secondary promotion crossed production authority boundary")
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "policyRevision": POLICY_REVISION,
            "promotionBodyRigRevision": promotion_revision,
            "canonicalBodyId": body_id,
            "sourcePackageSha256": source_sha,
            "sourceAvatarSha256": _sha256_bytes(source_avatar),
            "reviewRuntimeReceiptSha256": _sha(review["sourceRuntimeReceiptSha256"], label="review runtime receipt SHA"),
            "reviewVrmSha256": _sha(review["sourceReviewVrmSha256"], label="review VRM SHA"),
            "previewAuthoritySha256": _sha(review["previewAuthoritySha256"], label="preview authority SHA"),
            "humanReviewReceiptSha256": human_review_sha,
            "promotedPackageSha256": _sha256_file(package_path),
            "promotedAvatarSha256": _sha256_bytes(promoted_avatar),
            "componentsBefore": dict(before["components"]),
            "componentsAfter": dict(after["components"]),
            "faceSecondaryComponentsAfter": {component: "complete" for component in REQUIRED_SUBCOMPONENTS},
            "semanticVertexMapAuthority": "licensed-smplx-verified",
            "genericSecondaryAnatomy": True,
            "sourceDerivedDentalIdentity": False,
            "sourceDerivedIdentitySynthesis": False,
            "generativeIdentitySynthesis": False,
            "highFidelityReadyAfter": bool(audit["high_fidelity_ready"]),
            "humanReviewRequired": True,
            "productionActivation": False,
        }
        with receipt_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n")
        os.replace(staging, final_root)
        moved = True
        result = read_promotion(
            preparation_dir=prep_root,
            runtime_dir=runtime_root,
            render_dir=render_root,
            human_review_dir=human_root,
            source_package_path=source,
            output_dir=final_root,
        )
        verified = True
        return result
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if moved and not verified and final_root.exists():
            shutil.rmtree(final_root, ignore_errors=True)


def read_promotion(
    *,
    preparation_dir: str | Path,
    runtime_dir: str | Path,
    render_dir: str | Path,
    human_review_dir: str | Path,
    source_package_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    prep_root = Path(preparation_dir).expanduser().resolve()
    runtime_root = Path(runtime_dir).expanduser().resolve()
    render_root = Path(render_dir).expanduser().resolve()
    human_root = Path(human_review_dir).expanduser().resolve()
    source = Path(source_package_path).expanduser().resolve()
    root = Path(output_dir).expanduser().resolve()
    package_path = root / PACKAGE_NAME
    receipt_path = root / RECEIPT_NAME
    if not package_path.is_file() or not receipt_path.is_file():
        raise HighFidelityFaceSecondaryPromotionError("face-secondary promotion package/receipt is missing")
    review, runtime, _review_vrm, source_sha = _authority(prep_root, runtime_root, render_root, human_root, source)
    value = _read_json(receipt_path, label="face-secondary promotion receipt")
    required = {
        "format", "version", "policyRevision", "promotionBodyRigRevision", "canonicalBodyId",
        "sourcePackageSha256", "sourceAvatarSha256", "reviewRuntimeReceiptSha256", "reviewVrmSha256",
        "previewAuthoritySha256", "humanReviewReceiptSha256", "promotedPackageSha256", "promotedAvatarSha256",
        "componentsBefore", "componentsAfter", "faceSecondaryComponentsAfter", "semanticVertexMapAuthority",
        "genericSecondaryAnatomy", "sourceDerivedDentalIdentity", "sourceDerivedIdentitySynthesis",
        "generativeIdentitySynthesis", "highFidelityReadyAfter", "humanReviewRequired", "productionActivation",
    }
    if set(value) != required or value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policyRevision") != POLICY_REVISION:
        raise HighFidelityFaceSecondaryPromotionError("face-secondary promotion receipt fields/format are invalid")
    _revision(value.get("promotionBodyRigRevision"))
    source_avatar, body_id = _package_avatar(source)
    if value.get("canonicalBodyId") != body_id or body_id != review.get("canonicalBodyId"):
        raise HighFidelityFaceSecondaryPromotionError("promotion body identity is stale")
    expected_exact = {
        "sourcePackageSha256": source_sha,
        "sourceAvatarSha256": _sha256_bytes(source_avatar),
        "reviewRuntimeReceiptSha256": review["sourceRuntimeReceiptSha256"],
        "reviewVrmSha256": review["sourceReviewVrmSha256"],
        "previewAuthoritySha256": review["previewAuthoritySha256"],
        "humanReviewReceiptSha256": _sha256_file(Path(review["reviewPath"])),
        "promotedPackageSha256": _sha256_file(package_path),
    }
    for field, expected in expected_exact.items():
        if value.get(field) != expected:
            raise HighFidelityFaceSecondaryPromotionError(f"face-secondary promotion is stale: {field}")
    try:
        audit = audit_high_fidelity_package(package_path)
        with zipfile.ZipFile(package_path, "r") as archive:
            avatar = archive.read("avatar.vrm")
        document, _binary = _read_glb(avatar)
    except (HighFidelityPackageAuditError, OSError, zipfile.BadZipFile, KeyError, PbrMaterialError) as exc:
        raise HighFidelityFaceSecondaryPromotionError(f"promoted package revalidation failed: {exc}") from exc
    if value.get("promotedAvatarSha256") != _sha256_bytes(avatar):
        raise HighFidelityFaceSecondaryPromotionError("promoted avatar bytes changed")
    bodyrig = _bodyrig(document)
    if "faceSecondaryReviewRuntime" in bodyrig:
        raise HighFidelityFaceSecondaryPromotionError("promoted avatar retained review-only face-secondary metadata")
    embedded = bodyrig.get("faceSecondaryPromotion")
    if not isinstance(embedded, dict) or embedded.get("format") != EMBEDDED_FORMAT or embedded.get("version") != VERSION:
        raise HighFidelityFaceSecondaryPromotionError("promoted avatar lacks canonical embedded face-secondary promotion")
    if embedded.get("sourcePackageSha256") != source_sha or embedded.get("humanReviewReceiptSha256") != expected_exact["humanReviewReceiptSha256"]:
        raise HighFidelityFaceSecondaryPromotionError("embedded face-secondary promotion lineage is stale")
    if embedded.get("sourceDerivedDentalIdentity") is not False or embedded.get("genericSecondaryAnatomy") is not True or embedded.get("productionActivation") is not False:
        raise HighFidelityFaceSecondaryPromotionError("embedded face-secondary promotion crossed disclosure/production boundary")
    expected_nested = {component: "complete" for component in REQUIRED_SUBCOMPONENTS}
    if audit["face_secondary_components"] != expected_nested or audit["face_secondary_ready"] is not True or audit["components"].get("face_secondary") != "complete":
        raise HighFidelityFaceSecondaryPromotionError("promoted package face-secondary audit is incomplete")
    if value.get("faceSecondaryComponentsAfter") != expected_nested or value.get("componentsAfter") != audit["components"]:
        raise HighFidelityFaceSecondaryPromotionError("promotion receipt component state differs from strict audit")
    if value.get("semanticVertexMapAuthority") != "licensed-smplx-verified" or audit["semantic_vertex_map_authority"] != "licensed-smplx-verified":
        raise HighFidelityFaceSecondaryPromotionError("promoted semantic authority is invalid")
    if value.get("genericSecondaryAnatomy") is not True or value.get("sourceDerivedDentalIdentity") is not False or value.get("sourceDerivedIdentitySynthesis") is not False or value.get("generativeIdentitySynthesis") is not False:
        raise HighFidelityFaceSecondaryPromotionError("promotion disclosure fields are invalid")
    if value.get("highFidelityReadyAfter") is not bool(audit["high_fidelity_ready"]):
        raise HighFidelityFaceSecondaryPromotionError("promotion high-fidelity readiness differs from strict audit")
    if value.get("humanReviewRequired") is not True or value.get("productionActivation") is not False or audit["production_ready"] is not False:
        raise HighFidelityFaceSecondaryPromotionError("face-secondary promotion crossed final authority boundary")
    return {**value, "promotedPackagePath": str(package_path), "promotionReceiptPath": str(receipt_path)}
