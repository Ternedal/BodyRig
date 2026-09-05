from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .bridges.avatar_fidelity_components import (
    FidelityComponentError,
    validate_receipt,
    with_component_status,
)
from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .high_fidelity_anatomy_promotion import (
    HighFidelityAnatomyPromotionError,
    read_promotion as read_anatomy_promotion,
)
from .high_fidelity_hair_deformation_review import (
    HighFidelityHairDeformationReviewError,
    read_review as read_hair_review,
    review_path as hair_review_path,
)
from .high_fidelity_package_audit import (
    HighFidelityPackageAuditError,
    audit_high_fidelity_package,
)
from .high_fidelity_preview_jobs import ROOT_DIRNAME
from .package import MRBodyError, validate_package
from .storage import ui_jobs_dir

FORMAT = "bodyrig-high-fidelity-hair-promotion"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-hair-promotion-v1"
EMBEDDED_FORMAT = "bodyrig-hair-promotion"
PROMOTION_ROOT = ".high-fidelity-hair-promotions"
JOB_RE = re.compile(r"^hfpreview-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")

TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "preview_job_id",
    "canonical_body_id",
    "source_bodyrig_revision",
    "promotion_bodyrig_revision",
    "target_family",
    "source_candidate_package_sha256",
    "anatomy_promoted_package_sha256",
    "anatomy_promotion_receipt_sha256",
    "hair_deformation_review_sha256",
    "combined_bridge_result_sha256",
    "expected_hair_review_bridge_sha256",
    "rebuilt_hair_bridge_result_sha256",
    "rebuilt_hair_bridge_canonical_sha256",
    "rebuilt_hair_runtime_receipt_sha256",
    "rebuilt_hair_binding_sha256",
    "rebuilt_hair_review_vrm_sha256",
    "promoted_package_sha256",
    "promoted_avatar_sha256",
    "components_before",
    "components_after",
    "promotion_component",
    "production_activation",
}


class HighFidelityHairPromotionError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(value: Any, *, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(clean):
        raise HighFidelityHairPromotionError(f"{label} is not a canonical SHA-256")
    return clean


def _revision(value: Any, *, label: str = "BodyRig revision") -> str:
    clean = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(clean):
        raise HighFidelityHairPromotionError(f"{label} is not a canonical Git SHA")
    return clean


def _job_id(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if not JOB_RE.fullmatch(clean):
        raise HighFidelityHairPromotionError("high-fidelity preview job id is not canonical")
    return clean


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HighFidelityHairPromotionError(f"{label} is unreadable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise HighFidelityHairPromotionError(f"{label} must be a JSON object")
    return value


def _canonical_json_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _sha256_bytes(raw)


def _preview_root(preview_job_id: str) -> Path:
    return (ui_jobs_dir() / ROOT_DIRNAME / _job_id(preview_job_id)).resolve()


def _inside(root: Path, path: Path, *, label: str) -> Path:
    path = path.expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HighFidelityHairPromotionError(f"{label} escaped persisted preview authority") from exc
    return path


def _need_file(root: Path, path: Path, *, label: str) -> Path:
    path = _inside(root, path, label=label)
    if not path.is_file():
        raise HighFidelityHairPromotionError(f"{label} is missing: {path}")
    return path


def _need_dir(root: Path, path: Path, *, label: str) -> Path:
    path = _inside(root, path, label=label)
    if not path.is_dir():
        raise HighFidelityHairPromotionError(f"{label} is missing: {path}")
    return path


def _preview_inputs(preview_job_id: str) -> dict[str, Any]:
    job_id = _job_id(preview_job_id)
    root = _preview_root(job_id)
    job_path = _need_file(root, root / "job.json", label="High-fidelity preview job")
    job = _read_json(job_path, label="High-fidelity preview job")
    if (
        job.get("format") != "bodyrig-high-fidelity-preview-job"
        or job.get("version") != 1
        or job.get("job_id") != job_id
        or job.get("status") != "succeeded"
    ):
        raise HighFidelityHairPromotionError("hair promotion requires a succeeded canonical high-fidelity preview")
    source_revision = _revision(job.get("bodyrig_revision"), label="preview BodyRig revision")
    target_family = str(job.get("target_family") or "").strip().lower()
    if target_family not in {"female", "male", "neutral"}:
        raise HighFidelityHairPromotionError("preview target family is invalid")
    canonical_body_id = str(job.get("canonical_body_id") or "").strip()
    if not canonical_body_id:
        raise HighFidelityHairPromotionError("preview canonical body id is missing")

    anatomy_root = _need_dir(
        root,
        Path(str(job.get("anatomy_run_root") or "")),
        label="Anatomy run root",
    )
    anatomy_summary_path = _need_file(
        root,
        anatomy_root / "subject-anatomy-physical-gate.json",
        label="Anatomy gate summary",
    )
    anatomy_summary = _read_json(anatomy_summary_path, label="Anatomy gate summary")
    candidate_package = _need_file(
        root,
        Path(str(anatomy_summary.get("package") or "")),
        label="Anatomy candidate package",
    )
    candidate_sha = _sha256_file(candidate_package)
    if (
        anatomy_summary.get("format") != "bodyrig-subject-anatomy-physical-gate"
        or anatomy_summary.get("version") != 1
        or str(anatomy_summary.get("bodyrig_revision") or "").lower() != source_revision
        or anatomy_summary.get("canonical_body_id") != canonical_body_id
        or anatomy_summary.get("target_model_family") != target_family
        or anatomy_summary.get("candidate_gross_anatomy_pass") is not True
        or anatomy_summary.get("comparison_only") is not True
        or anatomy_summary.get("production_activation") is not False
        or str(anatomy_summary.get("package_sha256") or "") != candidate_sha
    ):
        raise HighFidelityHairPromotionError("anatomy candidate no longer matches the succeeded preview authority")

    candidate_workspace = _need_dir(
        root,
        candidate_package.parent / "candidate-workspace",
        label="Anatomy candidate workspace",
    )
    component_root = _need_dir(
        root,
        Path(str(job.get("component_root") or "")),
        label="Component discovery root",
    )
    component_receipt_path = _need_file(
        root,
        component_root / "subject-component-discovery.json",
        label="Component discovery receipt",
    )
    component = _read_json(component_receipt_path, label="Component discovery receipt")
    hair = component.get("hair")
    runtime = component.get("runtime")
    if not isinstance(hair, Mapping) or not isinstance(runtime, Mapping):
        raise HighFidelityHairPromotionError("component discovery lacks canonical hair/runtime authority")
    if (
        component.get("format") != "bodyrig-subject-component-discovery"
        or component.get("version") != 1
        or str(component.get("bodyrig_revision") or "").lower() != source_revision
        or component.get("candidate_package_sha256") != candidate_sha
        or component.get("comparison_only") is not True
        or component.get("production_activation") is not False
    ):
        raise HighFidelityHairPromotionError("component discovery no longer binds the exact preview candidate")

    hair_candidate_dir = _need_dir(root, component_root / "hair", label="Source hair candidate directory")
    hair_evidence = _need_file(
        root,
        Path(str(hair.get("evidence") or "")),
        label="Source hair candidate evidence",
    )
    if hair_evidence.parent != hair_candidate_dir or hair.get("evidence_sha256") != _sha256_file(hair_evidence):
        raise HighFidelityHairPromotionError("source hair candidate evidence no longer matches component discovery")

    runtime_dir = _need_dir(root, component_root / "runtime", label="Combined hair+eye runtime directory")
    combined_bridge_path = _need_file(
        root,
        runtime_dir / "source-hair-eye-review-bridge.json",
        label="Combined hair+eye bridge result",
    )
    combined_runtime_receipt_path = _need_file(
        root,
        runtime_dir / "source-hair-eye-review-runtime.json",
        label="Combined hair+eye runtime receipt",
    )
    combined_bridge = _read_json(combined_bridge_path, label="Combined hair+eye bridge result")
    combined_runtime = _read_json(combined_runtime_receipt_path, label="Combined hair+eye runtime receipt")
    expected_hair_bridge_sha = _sha(
        combined_bridge.get("hairReviewBridgeSha256"),
        label="combined bridge hairReviewBridgeSha256",
    )
    combined_review_sha = _sha(
        combined_bridge.get("reviewVrmSha256"),
        label="combined review VRM SHA-256",
    )
    if (
        combined_bridge.get("format") != "bodyrig-source-hair-eye-review-bridge"
        or combined_bridge.get("version") != 1
        or combined_bridge.get("sourceHairRuntimeApplied") is not True
        or combined_bridge.get("sourceEyeSurfaceApplied") is not True
        or combined_bridge.get("irisIdentityIsolated") is not False
        or combined_bridge.get("irisAppearanceStatus") != "review-pending"
        or combined_bridge.get("hairComponentAuthority") is not False
        or combined_bridge.get("eyeComponentAuthority") is not False
        or combined_bridge.get("productionActivation") is not False
    ):
        raise HighFidelityHairPromotionError("combined hair+eye bridge is not canonical review-only authority")
    if (
        combined_runtime.get("format") != "bodyrig-source-hair-eye-review-runtime"
        or combined_runtime.get("version") != 1
        or combined_runtime.get("packageSha256") != candidate_sha
        or combined_runtime.get("reviewVrmSha256") != combined_review_sha
        or combined_runtime.get("bridgeResultSha256") != _sha256_file(combined_bridge_path)
        or combined_runtime.get("sourceHairRuntimeApplied") is not True
        or combined_runtime.get("sourceEyeSurfaceApplied") is not True
        or combined_runtime.get("irisIdentityIsolated") is not False
        or combined_runtime.get("irisAppearanceStatus") != "review-pending"
        or combined_runtime.get("hairComponentAuthority") is not False
        or combined_runtime.get("eyeComponentAuthority") is not False
        or combined_runtime.get("productionActivation") is not False
    ):
        raise HighFidelityHairPromotionError("combined runtime receipt no longer binds the reviewed bridge")

    return {
        "job": job,
        "root": root,
        "source_bodyrig_revision": source_revision,
        "target_family": target_family,
        "canonical_body_id": canonical_body_id,
        "candidate_package": candidate_package,
        "candidate_package_sha256": candidate_sha,
        "candidate_workspace": candidate_workspace,
        "component_root": component_root,
        "hair_candidate_dir": hair_candidate_dir,
        "combined_bridge_path": combined_bridge_path,
        "combined_bridge_result_sha256": _sha256_file(combined_bridge_path),
        "expected_hair_review_bridge_sha256": expected_hair_bridge_sha,
        "combined_review_vrm_sha256": combined_review_sha,
    }


def _hair_review_authority(preview_job_id: str) -> tuple[dict[str, Any], Path, str]:
    try:
        review = read_hair_review(preview_job_id)
    except HighFidelityHairDeformationReviewError as exc:
        raise HighFidelityHairPromotionError(f"hair deformation review authority failed: {exc}") from exc
    if (
        review.get("hair_promotion_eligible") is not True
        or review.get("human_review_complete") is not True
        or review.get("production_activation") is not False
    ):
        raise HighFidelityHairPromotionError("hair deformation review does not authorize promotion eligibility")
    path = hair_review_path(
        str(review["preview_job_id"]),
        hair_probe_sha256=str(review["hair_deformation_probe_sha256"]),
    )
    if not path.is_file():
        raise HighFidelityHairPromotionError("hair deformation review receipt is missing")
    return review, path, _sha256_file(path)


def _anatomy_authority(preview_job_id: str) -> tuple[dict[str, Any], Path, Path, str]:
    try:
        promotion = read_anatomy_promotion(preview_job_id)
    except HighFidelityAnatomyPromotionError as exc:
        raise HighFidelityHairPromotionError(f"body anatomy must be promoted first: {exc}") from exc
    package = Path(str(promotion.get("package_path") or "")).expanduser().resolve()
    receipt = Path(str(promotion.get("receipt_path") or "")).expanduser().resolve()
    if not package.is_file() or not receipt.is_file():
        raise HighFidelityHairPromotionError("anatomy promotion package/receipt is missing")
    return promotion, package, receipt, _sha256_file(receipt)


def prepare_promotion_inputs(preview_job_id: str) -> dict[str, Any]:
    preview = _preview_inputs(preview_job_id)
    hair_review, _hair_review_file, hair_review_sha = _hair_review_authority(preview_job_id)
    anatomy, anatomy_package, anatomy_receipt, anatomy_receipt_sha = _anatomy_authority(preview_job_id)
    if (
        hair_review.get("candidate_package_sha256") != preview["candidate_package_sha256"]
        or hair_review.get("canonical_body_id") != preview["canonical_body_id"]
        or hair_review.get("bodyrig_revision") != preview["source_bodyrig_revision"]
    ):
        raise HighFidelityHairPromotionError("hair deformation review belongs to different preview candidate authority")
    if (
        anatomy.get("source_package_sha256") != preview["candidate_package_sha256"]
        or anatomy.get("canonical_body_id") != preview["canonical_body_id"]
        or anatomy.get("bodyrig_revision") != preview["source_bodyrig_revision"]
    ):
        raise HighFidelityHairPromotionError("anatomy promotion belongs to different preview candidate authority")
    return {
        "preview_job_id": _job_id(preview_job_id),
        "canonical_body_id": preview["canonical_body_id"],
        "source_bodyrig_revision": preview["source_bodyrig_revision"],
        "target_family": preview["target_family"],
        "source_candidate_package": str(preview["candidate_package"]),
        "source_candidate_package_sha256": preview["candidate_package_sha256"],
        "hair_candidate_dir": str(preview["hair_candidate_dir"]),
        "candidate_workspace": str(preview["candidate_workspace"]),
        "combined_bridge_result_sha256": preview["combined_bridge_result_sha256"],
        "expected_hair_review_bridge_sha256": preview["expected_hair_review_bridge_sha256"],
        "hair_deformation_review_sha256": hair_review_sha,
        "anatomy_promoted_package": str(anatomy_package),
        "anatomy_promoted_package_sha256": anatomy["promoted_package_sha256"],
        "anatomy_promotion_receipt": str(anatomy_receipt),
        "anatomy_promotion_receipt_sha256": anatomy_receipt_sha,
        "production_activation": False,
    }


def _extract_avatar(package: Path) -> bytes:
    try:
        with zipfile.ZipFile(package, "r") as archive:
            return archive.read("avatar.vrm")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HighFidelityHairPromotionError(f"could not read package avatar.vrm: {package}") from exc


def _assert_no_eye_runtime(document: Mapping[str, Any]) -> None:
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, Mapping) else None
    if not isinstance(bodyrig, Mapping):
        raise HighFidelityHairPromotionError("hair-only VRM lacks BodyRig metadata")
    if "eyeReviewRuntime" in bodyrig:
        raise HighFidelityHairPromotionError("hair promotion input contains review-only eye runtime authority")
    for node in document.get("nodes", []) if isinstance(document.get("nodes"), list) else []:
        if isinstance(node, Mapping) and str(node.get("name") or "").startswith("BodyRigSourceEyeReview"):
            raise HighFidelityHairPromotionError("hair promotion input contains review-only eye geometry")
    blocked_materials = {"BodyRigSourceEyeSurface", "BodyRigCorneaReview"}
    for material in document.get("materials", []) if isinstance(document.get("materials"), list) else []:
        if isinstance(material, Mapping) and str(material.get("name") or "") in blocked_materials:
            raise HighFidelityHairPromotionError("hair promotion input contains review-only eye/cornea material")


def _validated_rebuilt_hair_runtime(
    runtime_dir: str | Path,
    *,
    preview: Mapping[str, Any],
    promotion_bodyrig_revision: str,
) -> dict[str, Any]:
    root = Path(runtime_dir).expanduser().resolve()
    if not root.is_dir():
        raise HighFidelityHairPromotionError(f"rebuilt hair runtime directory is missing: {root}")
    bridge_path = root / "source-hair-review-bridge.json"
    vrm_path = root / "source-hair-review.vrm"
    runtime_receipt_path = root / "source-hair-review-runtime.json"
    binding_path = root / "source-hair-body-binding.json"
    for path, label in (
        (bridge_path, "rebuilt hair bridge result"),
        (vrm_path, "rebuilt hair-only review VRM"),
        (runtime_receipt_path, "rebuilt hair runtime receipt"),
        (binding_path, "rebuilt hair/body binding"),
    ):
        if not path.is_file():
            raise HighFidelityHairPromotionError(f"{label} is missing: {path}")

    bridge = _read_json(bridge_path, label="Rebuilt hair bridge result")
    runtime = _read_json(runtime_receipt_path, label="Rebuilt hair runtime receipt")
    canonical_bridge_sha = _canonical_json_sha256(bridge)
    if canonical_bridge_sha != preview["expected_hair_review_bridge_sha256"]:
        raise HighFidelityHairPromotionError(
            "rebuilt hair-only bridge does not match the exact hair stage reviewed inside the combined preview"
        )
    vrm_bytes = vrm_path.read_bytes()
    vrm_sha = _sha256_bytes(vrm_bytes)
    bridge_file_sha = _sha256_file(bridge_path)
    binding_sha = _sha256_file(binding_path)

    if (
        bridge.get("format") != "bodyrig-source-hair-review-bridge"
        or bridge.get("version") != 1
        or bridge.get("reviewVrmSha256") != vrm_sha
        or bridge.get("sourceHairBodyBindingSha256") != binding_sha
        or bridge.get("comparisonOnly") is not True
        or bridge.get("humanReviewRequired") is not True
        or bridge.get("hairComponentAuthority") is not False
        or bridge.get("productionActivation") is not False
    ):
        raise HighFidelityHairPromotionError("rebuilt hair bridge crossed or lost the review-only authority boundary")
    if (
        runtime.get("format") != "bodyrig-source-hair-review-runtime"
        or runtime.get("version") != 1
        or runtime.get("bodyrigRevision") != promotion_bodyrig_revision
        or runtime.get("bodyId") != preview["canonical_body_id"]
        or runtime.get("packageSha256") != preview["candidate_package_sha256"]
        or runtime.get("reviewVrmSha256") != vrm_sha
        or runtime.get("bridgeResultSha256") != bridge_file_sha
        or runtime.get("sourceHairBodyBindingSha256") != binding_sha
        or runtime.get("comparisonOnly") is not True
        or runtime.get("humanReviewRequired") is not True
        or runtime.get("hairComponentAuthority") is not False
        or runtime.get("productionActivation") is not False
    ):
        raise HighFidelityHairPromotionError("rebuilt hair runtime receipt is stale or crossed the review-only boundary")

    candidate_avatar = _extract_avatar(Path(preview["candidate_package"]))
    if runtime.get("baseAvatarVrmSha256") != _sha256_bytes(candidate_avatar):
        raise HighFidelityHairPromotionError("rebuilt hair runtime is not based on the exact reviewed anatomy candidate avatar")

    try:
        document, _binary = _read_glb(vrm_bytes)
    except PbrMaterialError as exc:
        raise HighFidelityHairPromotionError(f"rebuilt hair-only VRM is invalid: {exc}") from exc
    _assert_no_eye_runtime(document)
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    hair_runtime = bodyrig.get("hairReviewRuntime") if isinstance(bodyrig, dict) else None
    if not isinstance(hair_runtime, Mapping):
        raise HighFidelityHairPromotionError("rebuilt hair-only VRM lost source-hair runtime metadata")
    if (
        hair_runtime.get("comparisonOnly") is not True
        or hair_runtime.get("humanReviewRequired") is not True
        or hair_runtime.get("productionActivation") is not False
    ):
        raise HighFidelityHairPromotionError("rebuilt hair-only VRM metadata crossed the review-only boundary")

    return {
        "root": root,
        "bridge_path": bridge_path,
        "vrm_path": vrm_path,
        "runtime_receipt_path": runtime_receipt_path,
        "binding_path": binding_path,
        "bridge": bridge,
        "runtime": runtime,
        "vrm_bytes": vrm_bytes,
        "bridge_result_sha256": bridge_file_sha,
        "bridge_canonical_sha256": canonical_bridge_sha,
        "runtime_receipt_sha256": _sha256_file(runtime_receipt_path),
        "binding_sha256": binding_sha,
        "review_vrm_sha256": vrm_sha,
    }


def _promoted_hair_avatar(
    hair_only_vrm: bytes,
    anatomy_promoted_avatar: bytes,
    *,
    preview_job_id: str,
    source_bodyrig_revision: str,
    promotion_bodyrig_revision: str,
    target_family: str,
    source_candidate_package_sha256: str,
    anatomy_promoted_package_sha256: str,
    anatomy_promotion_receipt_sha256: str,
    hair_deformation_review_sha256: str,
    combined_bridge_result_sha256: str,
    rebuilt_hair_bridge_canonical_sha256: str,
    rebuilt_hair_runtime_receipt_sha256: str,
    rebuilt_hair_review_vrm_sha256: str,
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    try:
        hair_document, hair_binary = _read_glb(hair_only_vrm)
        anatomy_document, _anatomy_binary = _read_glb(anatomy_promoted_avatar)
    except PbrMaterialError as exc:
        raise HighFidelityHairPromotionError(str(exc)) from exc

    _assert_no_eye_runtime(hair_document)
    hair_extras = hair_document.get("extras")
    hair_bodyrig = hair_extras.get("bodyrig") if isinstance(hair_extras, dict) else None
    anatomy_extras = anatomy_document.get("extras")
    anatomy_bodyrig = anatomy_extras.get("bodyrig") if isinstance(anatomy_extras, dict) else None
    if not isinstance(hair_bodyrig, dict) or not isinstance(anatomy_bodyrig, dict):
        raise HighFidelityHairPromotionError("hair/anatomy avatars lack BodyRig metadata")
    if "hairPromotion" in hair_bodyrig:
        raise HighFidelityHairPromotionError("hair-only VRM already carries hair promotion metadata")
    if "bodyAnatomyPromotion" not in anatomy_bodyrig:
        raise HighFidelityHairPromotionError("anatomy-promoted avatar lacks embedded anatomy authority")
    if "hairReviewRuntime" not in hair_bodyrig:
        raise HighFidelityHairPromotionError("hair-only VRM lacks source-hair runtime metadata")

    try:
        before = validate_receipt(anatomy_bodyrig.get("fidelityComponents", {}))
    except FidelityComponentError as exc:
        raise HighFidelityHairPromotionError(str(exc)) from exc
    if before["components"].get("body_anatomy") != "complete":
        raise HighFidelityHairPromotionError("hair promotion requires body_anatomy=complete first")
    if before["components"].get("hair") == "complete":
        raise HighFidelityHairPromotionError("hair is already complete in anatomy-promoted package")
    try:
        after = with_component_status(before, component="hair", status="complete")
    except FidelityComponentError as exc:
        raise HighFidelityHairPromotionError(str(exc)) from exc
    for component, status in before["components"].items():
        if component != "hair" and after["components"].get(component) != status:
            raise HighFidelityHairPromotionError("hair promotion attempted to change another fidelity component")

    embedded = {
        "format": EMBEDDED_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "previewJobId": _job_id(preview_job_id),
        "sourceBodyRigRevision": _revision(source_bodyrig_revision, label="source BodyRig revision"),
        "promotionBodyRigRevision": _revision(promotion_bodyrig_revision, label="promotion BodyRig revision"),
        "targetFamily": target_family,
        "sourceCandidatePackageSha256": _sha(source_candidate_package_sha256, label="source candidate package SHA-256"),
        "anatomyPromotedPackageSha256": _sha(anatomy_promoted_package_sha256, label="anatomy-promoted package SHA-256"),
        "anatomyPromotionReceiptSha256": _sha(anatomy_promotion_receipt_sha256, label="anatomy promotion receipt SHA-256"),
        "hairDeformationReviewSha256": _sha(hair_deformation_review_sha256, label="hair deformation review SHA-256"),
        "combinedBridgeResultSha256": _sha(combined_bridge_result_sha256, label="combined bridge result SHA-256"),
        "rebuiltHairBridgeSha256": _sha(
            rebuilt_hair_bridge_canonical_sha256,
            label="rebuilt canonical hair bridge SHA-256",
        ),
        "rebuiltHairRuntimeReceiptSha256": _sha(
            rebuilt_hair_runtime_receipt_sha256,
            label="rebuilt hair runtime receipt SHA-256",
        ),
        "rebuiltHairReviewVrmSha256": _sha(
            rebuilt_hair_review_vrm_sha256,
            label="rebuilt hair review VRM SHA-256",
        ),
        "component": "hair",
        "eyesImported": False,
        "productionActivation": False,
    }
    hair_bodyrig["fidelityComponents"] = after
    hair_bodyrig["bodyAnatomyPromotion"] = dict(anatomy_bodyrig["bodyAnatomyPromotion"])
    hair_bodyrig["hairPromotion"] = embedded
    return _write_glb(hair_document, hair_binary), before, after


def _rewrite_package(source: Path, destination: Path, *, avatar_vrm: bytes) -> None:
    try:
        with zipfile.ZipFile(source, "r") as archive:
            order = [info.filename for info in archive.infolist()]
            payload = {name: archive.read(name) for name in order}
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HighFidelityHairPromotionError("could not read anatomy-promoted source package") from exc
    if "avatar.vrm" not in payload or "checksums.json" not in payload:
        raise HighFidelityHairPromotionError("anatomy-promoted package lacks canonical avatar/checksum files")
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
        raise HighFidelityHairPromotionError(f"refusing to overwrite promoted package: {destination}") from exc
    except OSError as exc:
        raise HighFidelityHairPromotionError("could not write promoted hair package") from exc


def _promotion_dir(prepared: Mapping[str, Any]) -> Path:
    stem = ".".join(
        (
            str(prepared["source_candidate_package_sha256"]),
            str(prepared["anatomy_promoted_package_sha256"]),
            str(prepared["hair_deformation_review_sha256"]),
            str(prepared["expected_hair_review_bridge_sha256"]),
            "hair",
        )
    )
    return ui_jobs_dir() / PROMOTION_ROOT / str(prepared["preview_job_id"]) / stem


def _evidence_paths(root: Path) -> dict[str, Path]:
    return {
        "package": root / "promoted.mrbody",
        "receipt": root / "promotion.json",
        "hair_vrm": root / "source-hair-review.vrm",
        "hair_bridge": root / "source-hair-review-bridge.json",
        "hair_runtime": root / "source-hair-review-runtime.json",
        "hair_binding": root / "source-hair-body-binding.json",
    }


def write_promotion(
    preview_job_id: str,
    *,
    promotion_bodyrig_revision: str,
    hair_runtime_dir: str | Path,
) -> dict[str, Any]:
    promotion_revision = _revision(promotion_bodyrig_revision, label="promotion BodyRig revision")
    prepared = prepare_promotion_inputs(preview_job_id)
    preview = _preview_inputs(preview_job_id)
    _hair_review, _hair_review_file, hair_review_sha = _hair_review_authority(preview_job_id)
    _anatomy, anatomy_package, _anatomy_receipt, anatomy_receipt_sha = _anatomy_authority(preview_job_id)
    rebuilt = _validated_rebuilt_hair_runtime(
        hair_runtime_dir,
        preview=preview,
        promotion_bodyrig_revision=promotion_revision,
    )
    if rebuilt["bridge_canonical_sha256"] != prepared["expected_hair_review_bridge_sha256"]:
        raise HighFidelityHairPromotionError("rebuilt hair bridge canonical hash changed after preparation")

    final_root = _promotion_dir(prepared)
    if final_root.exists():
        raise HighFidelityHairPromotionError(f"refusing to overwrite existing hair promotion authority: {final_root}")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    staging = final_root.with_name(f".{final_root.name}.partial-{uuid.uuid4().hex}")
    staging.mkdir()
    paths = _evidence_paths(staging)
    committed = False
    try:
        shutil.copyfile(rebuilt["vrm_path"], paths["hair_vrm"])
        shutil.copyfile(rebuilt["bridge_path"], paths["hair_bridge"])
        shutil.copyfile(rebuilt["runtime_receipt_path"], paths["hair_runtime"])
        shutil.copyfile(rebuilt["binding_path"], paths["hair_binding"])

        anatomy_avatar = _extract_avatar(anatomy_package)
        promoted_avatar, before, after = _promoted_hair_avatar(
            rebuilt["vrm_bytes"],
            anatomy_avatar,
            preview_job_id=str(prepared["preview_job_id"]),
            source_bodyrig_revision=str(prepared["source_bodyrig_revision"]),
            promotion_bodyrig_revision=promotion_revision,
            target_family=str(prepared["target_family"]),
            source_candidate_package_sha256=str(prepared["source_candidate_package_sha256"]),
            anatomy_promoted_package_sha256=str(prepared["anatomy_promoted_package_sha256"]),
            anatomy_promotion_receipt_sha256=anatomy_receipt_sha,
            hair_deformation_review_sha256=hair_review_sha,
            combined_bridge_result_sha256=str(prepared["combined_bridge_result_sha256"]),
            rebuilt_hair_bridge_canonical_sha256=rebuilt["bridge_canonical_sha256"],
            rebuilt_hair_runtime_receipt_sha256=rebuilt["runtime_receipt_sha256"],
            rebuilt_hair_review_vrm_sha256=rebuilt["review_vrm_sha256"],
        )
        _rewrite_package(anatomy_package, paths["package"], avatar_vrm=promoted_avatar)
        try:
            validated = validate_package(paths["package"])
            audit = audit_high_fidelity_package(paths["package"])
        except (MRBodyError, HighFidelityPackageAuditError) as exc:
            raise HighFidelityHairPromotionError(f"promoted hair package failed strict audit: {exc}") from exc
        if validated.manifest["id"] != prepared["canonical_body_id"]:
            raise HighFidelityHairPromotionError("promoted hair package changed canonical body id")
        if audit["components"].get("body_anatomy") != "complete" or audit["components"].get("hair") != "complete":
            raise HighFidelityHairPromotionError("promoted package did not preserve anatomy complete + make hair complete")
        for component, status in before["components"].items():
            if component != "hair" and audit["components"].get(component) != status:
                raise HighFidelityHairPromotionError("promoted hair package changed another fidelity component")
        if audit["production_ready"] is not False:
            raise HighFidelityHairPromotionError("hair promotion crossed production authority boundary")

        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "policy_revision": POLICY_REVISION,
            "preview_job_id": str(prepared["preview_job_id"]),
            "canonical_body_id": str(prepared["canonical_body_id"]),
            "source_bodyrig_revision": str(prepared["source_bodyrig_revision"]),
            "promotion_bodyrig_revision": promotion_revision,
            "target_family": str(prepared["target_family"]),
            "source_candidate_package_sha256": str(prepared["source_candidate_package_sha256"]),
            "anatomy_promoted_package_sha256": str(prepared["anatomy_promoted_package_sha256"]),
            "anatomy_promotion_receipt_sha256": anatomy_receipt_sha,
            "hair_deformation_review_sha256": hair_review_sha,
            "combined_bridge_result_sha256": str(prepared["combined_bridge_result_sha256"]),
            "expected_hair_review_bridge_sha256": str(prepared["expected_hair_review_bridge_sha256"]),
            "rebuilt_hair_bridge_result_sha256": _sha256_file(paths["hair_bridge"]),
            "rebuilt_hair_bridge_canonical_sha256": _canonical_json_sha256(
                _read_json(paths["hair_bridge"], label="Persisted hair bridge evidence")
            ),
            "rebuilt_hair_runtime_receipt_sha256": _sha256_file(paths["hair_runtime"]),
            "rebuilt_hair_binding_sha256": _sha256_file(paths["hair_binding"]),
            "rebuilt_hair_review_vrm_sha256": _sha256_file(paths["hair_vrm"]),
            "promoted_package_sha256": _sha256_file(paths["package"]),
            "promoted_avatar_sha256": _sha256_bytes(promoted_avatar),
            "components_before": dict(before["components"]),
            "components_after": dict(after["components"]),
            "promotion_component": "hair",
            "production_activation": False,
        }
        paths["receipt"].write_text(
            json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        staging.rename(final_root)
        committed = True
        verified = read_promotion(preview_job_id)
        return verified
    except Exception:
        if committed:
            shutil.rmtree(final_root, ignore_errors=True)
        else:
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _embedded_hair_promotion(package: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    avatar = _extract_avatar(package)
    try:
        document, _ = _read_glb(avatar)
    except PbrMaterialError as exc:
        raise HighFidelityHairPromotionError("promoted avatar is invalid") from exc
    _assert_no_eye_runtime(document)
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise HighFidelityHairPromotionError("promoted avatar lacks BodyRig metadata")
    embedded = bodyrig.get("hairPromotion")
    if not isinstance(embedded, dict):
        raise HighFidelityHairPromotionError("promoted avatar lacks embedded hair promotion authority")
    return embedded, bodyrig


def _embedded_anatomy_promotion(package: Path) -> dict[str, Any]:
    avatar = _extract_avatar(package)
    try:
        document, _ = _read_glb(avatar)
    except PbrMaterialError as exc:
        raise HighFidelityHairPromotionError("anatomy-promoted avatar is invalid") from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    value = bodyrig.get("bodyAnatomyPromotion") if isinstance(bodyrig, dict) else None
    if not isinstance(value, dict):
        raise HighFidelityHairPromotionError("anatomy-promoted avatar lost embedded anatomy authority")
    return dict(value)


def read_promotion(preview_job_id: str) -> dict[str, Any]:
    prepared = prepare_promotion_inputs(preview_job_id)
    final_root = _promotion_dir(prepared)
    paths = _evidence_paths(final_root)
    if not final_root.is_dir() or any(not path.is_file() for path in paths.values()):
        raise HighFidelityHairPromotionError("hair promotion package/receipt/evidence is missing")
    value = _read_json(paths["receipt"], label="Hair promotion receipt")
    if set(value) != TOP_FIELDS:
        raise HighFidelityHairPromotionError("hair promotion receipt fields are not canonical")
    if (
        value.get("format") != FORMAT
        or value.get("version") != VERSION
        or value.get("policy_revision") != POLICY_REVISION
        or value.get("production_activation") is not False
        or value.get("promotion_component") != "hair"
    ):
        raise HighFidelityHairPromotionError("hair promotion format/version/policy/authority boundary mismatch")

    expected_scalars = {
        "preview_job_id": prepared["preview_job_id"],
        "canonical_body_id": prepared["canonical_body_id"],
        "source_bodyrig_revision": prepared["source_bodyrig_revision"],
        "target_family": prepared["target_family"],
        "source_candidate_package_sha256": prepared["source_candidate_package_sha256"],
        "anatomy_promoted_package_sha256": prepared["anatomy_promoted_package_sha256"],
        "anatomy_promotion_receipt_sha256": prepared["anatomy_promotion_receipt_sha256"],
        "hair_deformation_review_sha256": prepared["hair_deformation_review_sha256"],
        "combined_bridge_result_sha256": prepared["combined_bridge_result_sha256"],
        "expected_hair_review_bridge_sha256": prepared["expected_hair_review_bridge_sha256"],
        "rebuilt_hair_bridge_result_sha256": _sha256_file(paths["hair_bridge"]),
        "rebuilt_hair_bridge_canonical_sha256": _canonical_json_sha256(
            _read_json(paths["hair_bridge"], label="Persisted rebuilt hair bridge")
        ),
        "rebuilt_hair_runtime_receipt_sha256": _sha256_file(paths["hair_runtime"]),
        "rebuilt_hair_binding_sha256": _sha256_file(paths["hair_binding"]),
        "rebuilt_hair_review_vrm_sha256": _sha256_file(paths["hair_vrm"]),
        "promoted_package_sha256": _sha256_file(paths["package"]),
    }
    for field, expected in expected_scalars.items():
        if value.get(field) != expected:
            raise HighFidelityHairPromotionError(f"hair promotion no longer matches exact authority: {field}")
    _revision(value.get("promotion_bodyrig_revision"), label="promotion BodyRig revision")
    if value["rebuilt_hair_bridge_canonical_sha256"] != value["expected_hair_review_bridge_sha256"]:
        raise HighFidelityHairPromotionError("persisted hair bridge no longer matches reviewed combined bridge provenance")

    runtime = _read_json(paths["hair_runtime"], label="Persisted rebuilt hair runtime")
    if (
        runtime.get("format") != "bodyrig-source-hair-review-runtime"
        or runtime.get("version") != 1
        or runtime.get("bodyrigRevision") != value["promotion_bodyrig_revision"]
        or runtime.get("bodyId") != value["canonical_body_id"]
        or runtime.get("packageSha256") != value["source_candidate_package_sha256"]
        or runtime.get("reviewVrmSha256") != value["rebuilt_hair_review_vrm_sha256"]
        or runtime.get("bridgeResultSha256") != value["rebuilt_hair_bridge_result_sha256"]
        or runtime.get("sourceHairBodyBindingSha256") != value["rebuilt_hair_binding_sha256"]
        or runtime.get("comparisonOnly") is not True
        or runtime.get("hairComponentAuthority") is not False
        or runtime.get("productionActivation") is not False
    ):
        raise HighFidelityHairPromotionError("persisted rebuilt hair runtime evidence no longer validates")

    try:
        hair_document, _ = _read_glb(paths["hair_vrm"].read_bytes())
    except PbrMaterialError as exc:
        raise HighFidelityHairPromotionError("persisted hair-only VRM is invalid") from exc
    _assert_no_eye_runtime(hair_document)

    try:
        validated = validate_package(paths["package"])
        promoted_audit = audit_high_fidelity_package(paths["package"])
    except (MRBodyError, HighFidelityPackageAuditError) as exc:
        raise HighFidelityHairPromotionError(f"hair promotion package audit failed: {exc}") from exc
    if validated.manifest["id"] != value["canonical_body_id"]:
        raise HighFidelityHairPromotionError("promoted package body id changed")
    if promoted_audit["components"].get("body_anatomy") != "complete":
        raise HighFidelityHairPromotionError("promoted package lost body anatomy authority")
    if promoted_audit["components"].get("hair") != "complete":
        raise HighFidelityHairPromotionError("promoted package hair is not complete")
    if promoted_audit["production_ready"] is not False:
        raise HighFidelityHairPromotionError("promoted package crossed production authority boundary")
    if value.get("components_after") != dict(promoted_audit["components"]):
        raise HighFidelityHairPromotionError("hair promotion component-state receipt is stale")

    _anatomy, anatomy_package, _anatomy_receipt, _ = _anatomy_authority(preview_job_id)
    try:
        anatomy_audit = audit_high_fidelity_package(anatomy_package)
    except HighFidelityPackageAuditError as exc:
        raise HighFidelityHairPromotionError(f"anatomy promotion no longer audits: {exc}") from exc
    if value.get("components_before") != dict(anatomy_audit["components"]):
        raise HighFidelityHairPromotionError("hair promotion no longer matches exact anatomy-promoted component state")
    for component, status in anatomy_audit["components"].items():
        expected = "complete" if component == "hair" else status
        if promoted_audit["components"].get(component) != expected:
            raise HighFidelityHairPromotionError("hair promotion changed component authority beyond hair")

    embedded, promoted_bodyrig = _embedded_hair_promotion(paths["package"])
    if promoted_bodyrig.get("bodyAnatomyPromotion") != _embedded_anatomy_promotion(anatomy_package):
        raise HighFidelityHairPromotionError("promoted hair package did not preserve exact embedded anatomy authority")
    expected_embedded = {
        "format": EMBEDDED_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "previewJobId": value["preview_job_id"],
        "sourceBodyRigRevision": value["source_bodyrig_revision"],
        "promotionBodyRigRevision": value["promotion_bodyrig_revision"],
        "targetFamily": value["target_family"],
        "sourceCandidatePackageSha256": value["source_candidate_package_sha256"],
        "anatomyPromotedPackageSha256": value["anatomy_promoted_package_sha256"],
        "anatomyPromotionReceiptSha256": value["anatomy_promotion_receipt_sha256"],
        "hairDeformationReviewSha256": value["hair_deformation_review_sha256"],
        "combinedBridgeResultSha256": value["combined_bridge_result_sha256"],
        "rebuiltHairBridgeSha256": value["rebuilt_hair_bridge_canonical_sha256"],
        "rebuiltHairRuntimeReceiptSha256": value["rebuilt_hair_runtime_receipt_sha256"],
        "rebuiltHairReviewVrmSha256": value["rebuilt_hair_review_vrm_sha256"],
        "component": "hair",
        "eyesImported": False,
        "productionActivation": False,
    }
    if embedded != expected_embedded:
        raise HighFidelityHairPromotionError("embedded hair promotion authority is stale or tampered")
    if value.get("promoted_avatar_sha256") != _sha256_bytes(_extract_avatar(paths["package"])):
        raise HighFidelityHairPromotionError("promoted avatar hash no longer matches receipt")

    return {
        **value,
        "promotion_root": str(final_root),
        "package_path": str(paths["package"]),
        "receipt_path": str(paths["receipt"]),
        "hair_review_vrm_path": str(paths["hair_vrm"]),
        "hair_bridge_path": str(paths["hair_bridge"]),
        "hair_runtime_receipt_path": str(paths["hair_runtime"]),
        "hair_binding_path": str(paths["hair_binding"]),
    }


def promotion_status(preview_job_id: str) -> dict[str, Any]:
    try:
        prepared = prepare_promotion_inputs(preview_job_id)
    except HighFidelityHairPromotionError as exc:
        return {
            "state": "blocked",
            "passed": False,
            "reason": str(exc),
            "hair_complete": False,
            "production_activation": False,
        }
    final_root = _promotion_dir(prepared)
    if not final_root.exists():
        return {
            "state": "required",
            "passed": False,
            "reason": (
                "Body anatomy is promoted and exact hair deformation review is PASS; "
                "hair-only runtime must now be reconstructed and hash-matched before materialization."
            ),
            "hair_complete": False,
            "expected_hair_review_bridge_sha256": prepared["expected_hair_review_bridge_sha256"],
            "production_activation": False,
        }
    try:
        value = read_promotion(preview_job_id)
    except HighFidelityHairPromotionError as exc:
        return {
            "state": "invalid",
            "passed": False,
            "reason": str(exc),
            "hair_complete": False,
            "production_activation": False,
        }
    return {
        "state": "pass",
        "passed": True,
        "hair_complete": True,
        "promoted_package_sha256": value["promoted_package_sha256"],
        "components_after": value["components_after"],
        "eyes_imported": False,
        "production_activation": False,
    }
