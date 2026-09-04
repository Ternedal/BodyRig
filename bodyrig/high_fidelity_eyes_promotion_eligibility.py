from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .high_fidelity_component_review import (
    HighFidelityComponentReviewError,
    read_review as read_component_review,
    review_path as component_review_path,
)
from .source_iris_review_runtime import SourceIrisReviewRuntimeError, read_reviewed_runtime
from .storage import ui_jobs_dir

FORMAT = "bodyrig-high-fidelity-eyes-promotion-eligibility"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-eyes-promotion-eligibility-v1"
BASE_RUNTIME_RECEIPT = "source-hair-eye-review-runtime.json"
JOB_RE = re.compile(r"^hfpreview-[0-9a-f]{32}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_COMPONENT_OUTCOME = "visual-pass-iris-authority-required"


class HighFidelityEyesPromotionEligibilityError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(clean):
        raise HighFidelityEyesPromotionEligibilityError(f"{label} is not canonical SHA-256")
    return clean


def _revision(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if not REVISION_RE.fullmatch(clean):
        raise HighFidelityEyesPromotionEligibilityError("BodyRig revision is not a canonical lowercase Git SHA")
    return clean


def _job(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if not JOB_RE.fullmatch(clean):
        raise HighFidelityEyesPromotionEligibilityError("high-fidelity preview job id is not canonical")
    return clean


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityEyesPromotionEligibilityError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise HighFidelityEyesPromotionEligibilityError(f"{label} must be a JSON object")
    return value


def eligibility_path(preview_job_id: str, *, review_vrm_sha256: str, iris_review_sha256: str) -> Path:
    job_id = _job(preview_job_id)
    vrm_sha = _sha(review_vrm_sha256, label="review VRM SHA")
    iris_sha = _sha(iris_review_sha256, label="iris review SHA")
    return ui_jobs_dir() / ".high-fidelity-eyes-promotion-eligibility" / f"{job_id}.{vrm_sha}.{iris_sha}.json"


def _authorities(
    preview_job_id: str,
    *,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
) -> tuple[dict[str, Any], Path, dict[str, Any], Path]:
    job_id = _job(preview_job_id)
    try:
        component = read_component_review(job_id)
    except HighFidelityComponentReviewError as exc:
        raise HighFidelityEyesPromotionEligibilityError(f"component visual-review authority failed: {exc}") from exc
    review_vrm_sha = _sha(component.get("review_vrm_sha256"), label="component review VRM SHA")
    component_path = component_review_path(job_id, review_vrm_sha256=review_vrm_sha)
    if not component_path.is_file():
        raise HighFidelityEyesPromotionEligibilityError("component visual-review receipt disappeared after validation")
    if component.get("human_review_complete") is not True or component.get("production_activation") is not False:
        raise HighFidelityEyesPromotionEligibilityError("component visual review crossed its human-review/production boundary")
    outcomes = component.get("review_outcome")
    promotion = component.get("promotion_eligibility")
    if not isinstance(outcomes, Mapping) or outcomes.get("eyes") != EXPECTED_COMPONENT_OUTCOME:
        raise HighFidelityEyesPromotionEligibilityError("component visual review does not identify iris authority as the remaining eyes gate")
    if not isinstance(promotion, Mapping) or promotion.get("eyes") is not False:
        raise HighFidelityEyesPromotionEligibilityError("component visual review already claims eyes promotion eligibility unexpectedly")

    try:
        reviewed = read_reviewed_runtime(
            base_runtime_dir=base_runtime_dir,
            iris_candidate_dir=iris_candidate_dir,
            source_eye_appearance_dir=source_eye_appearance_dir,
            reviewed_runtime_dir=reviewed_runtime_dir,
        )
    except SourceIrisReviewRuntimeError as exc:
        raise HighFidelityEyesPromotionEligibilityError(f"reviewed iris runtime authority failed: {exc}") from exc
    reviewed_receipt_path = Path(str(reviewed.get("reviewReceiptPath") or "")).expanduser().resolve()
    if not reviewed_receipt_path.is_file():
        raise HighFidelityEyesPromotionEligibilityError("reviewed iris runtime receipt disappeared after validation")
    if (
        reviewed.get("runtimeBytesUnchanged") is not True
        or reviewed.get("sourceEyePixelsUnchanged") is not True
        or reviewed.get("embeddedEyeRuntimeStillReviewPending") is not True
        or reviewed.get("irisReviewOverlayApplied") is not True
        or reviewed.get("irisIdentityIsolated") is not True
        or reviewed.get("irisAppearanceStatus") != "source-isolated-review-pass"
        or reviewed.get("eyeComponentAuthority") is not False
        or reviewed.get("eyesPromotionEligible") is not False
        or reviewed.get("productionActivation") is not False
    ):
        raise HighFidelityEyesPromotionEligibilityError("reviewed iris runtime crossed its narrow overlay authority boundary")
    if reviewed.get("baseReviewVrmSha256") != review_vrm_sha or reviewed.get("reviewedVrmSha256") != review_vrm_sha:
        raise HighFidelityEyesPromotionEligibilityError(
            "iris review is not bound to the exact VRM bytes that received component visual review"
        )
    if str(reviewed.get("targetModelFamily") or "") != str(component.get("target_family") or ""):
        raise HighFidelityEyesPromotionEligibilityError("iris runtime target family differs from component visual review")

    base_receipt_path = Path(base_runtime_dir).expanduser().resolve() / BASE_RUNTIME_RECEIPT
    if not base_receipt_path.is_file():
        raise HighFidelityEyesPromotionEligibilityError("base hair+eye runtime receipt is missing")
    if _sha256(base_receipt_path) != _sha(reviewed.get("baseRuntimeReceiptSha256"), label="reviewed runtime base receipt SHA"):
        raise HighFidelityEyesPromotionEligibilityError("reviewed iris runtime no longer binds the supplied base runtime receipt")
    base_receipt = _read_json(base_receipt_path, label="base hair+eye runtime receipt")
    if str(base_receipt.get("bodyId") or "") != str(component.get("canonical_body_id") or ""):
        raise HighFidelityEyesPromotionEligibilityError("base eye runtime canonical body differs from component visual review")
    if _sha(base_receipt.get("packageSha256"), label="base runtime package SHA") != _sha(
        component.get("candidate_package_sha256"), label="component candidate package SHA"
    ):
        raise HighFidelityEyesPromotionEligibilityError("base eye runtime package differs from component visual-review candidate package")
    if str(base_receipt.get("targetModelFamily") or "") != str(component.get("target_family") or ""):
        raise HighFidelityEyesPromotionEligibilityError("base eye runtime target family differs from component visual review")
    if _sha(base_receipt.get("reviewVrmSha256"), label="base runtime review VRM SHA") != review_vrm_sha:
        raise HighFidelityEyesPromotionEligibilityError("base runtime receipt review VRM differs from component visual review")
    return component, component_path, reviewed, reviewed_receipt_path


def write_eligibility(
    preview_job_id: str,
    *,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
    bodyrig_revision: str,
) -> dict[str, Any]:
    revision = _revision(bodyrig_revision)
    component, component_path, reviewed, reviewed_receipt_path = _authorities(
        preview_job_id,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
    )
    iris_review_sha = _sha(reviewed.get("irisReviewSha256"), label="iris review SHA")
    review_vrm_sha = _sha(component.get("review_vrm_sha256"), label="review VRM SHA")
    path = eligibility_path(preview_job_id, review_vrm_sha256=review_vrm_sha, iris_review_sha256=iris_review_sha)
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "bodyrigRevision": revision,
        "previewJobId": str(component["preview_job_id"]),
        "personId": str(component["person_id"]),
        "bodyRevision": str(component["body_revision"]),
        "canonicalBodyId": str(component["canonical_body_id"]),
        "targetModelFamily": str(component["target_family"]),
        "candidatePackageSha256": _sha(component["candidate_package_sha256"], label="candidate package SHA"),
        "componentVisualReviewSha256": _sha256(component_path),
        "componentVisualReviewBodyrigRevision": _revision(component["bodyrig_revision"]),
        "reviewVrmSha256": review_vrm_sha,
        "irisReviewedRuntimeReceiptSha256": _sha256(reviewed_receipt_path),
        "irisReviewedRuntimeBodyrigRevision": _revision(reviewed["bodyrigRevision"]),
        "irisCandidateSha256": _sha(reviewed["irisCandidateSha256"], label="iris candidate SHA"),
        "irisReviewSha256": iris_review_sha,
        "sourceEyeAppearanceReceiptSha256": _sha(reviewed["sourceEyeAppearanceReceiptSha256"], label="source eye appearance receipt SHA"),
        "canonicalEyeBakeSha256": _sha(reviewed["canonicalEyeBakeSha256"], label="canonical eye bake SHA"),
        "componentVisualOutcome": EXPECTED_COMPONENT_OUTCOME,
        "irisAppearanceStatus": "source-isolated-review-pass",
        "sameReviewedRuntimeBytes": True,
        "sourceEyePixelsUnchanged": True,
        "eyesPromotionEligible": True,
        "eyeComponentAuthority": False,
        "packageMutationPerformed": False,
        "eyesPromoted": False,
        "eyelashStatus": "missing",
        "faceSecondaryUnaffected": True,
        "humanReviewRequired": True,
        "productionActivation": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(raw)
    except FileExistsError as exc:
        raise HighFidelityEyesPromotionEligibilityError(f"refusing to overwrite existing eyes promotion eligibility receipt: {path}") from exc
    try:
        verified = read_eligibility(
            preview_job_id,
            base_runtime_dir=base_runtime_dir,
            iris_candidate_dir=iris_candidate_dir,
            source_eye_appearance_dir=source_eye_appearance_dir,
            reviewed_runtime_dir=reviewed_runtime_dir,
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {**verified, "eligibilityPath": str(path)}


def read_eligibility(
    preview_job_id: str,
    *,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
) -> dict[str, Any]:
    component, component_path, reviewed, reviewed_receipt_path = _authorities(
        preview_job_id,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
    )
    review_vrm_sha = _sha(component.get("review_vrm_sha256"), label="review VRM SHA")
    iris_review_sha = _sha(reviewed.get("irisReviewSha256"), label="iris review SHA")
    path = eligibility_path(preview_job_id, review_vrm_sha256=review_vrm_sha, iris_review_sha256=iris_review_sha)
    if not path.is_file():
        raise HighFidelityEyesPromotionEligibilityError(f"eyes promotion eligibility receipt is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityEyesPromotionEligibilityError("eyes promotion eligibility receipt is unreadable") from exc
    required = {
        "format", "version", "policyRevision", "bodyrigRevision", "previewJobId", "personId", "bodyRevision",
        "canonicalBodyId", "targetModelFamily", "candidatePackageSha256", "componentVisualReviewSha256",
        "componentVisualReviewBodyrigRevision", "reviewVrmSha256", "irisReviewedRuntimeReceiptSha256",
        "irisReviewedRuntimeBodyrigRevision", "irisCandidateSha256", "irisReviewSha256",
        "sourceEyeAppearanceReceiptSha256", "canonicalEyeBakeSha256", "componentVisualOutcome",
        "irisAppearanceStatus", "sameReviewedRuntimeBytes", "sourceEyePixelsUnchanged", "eyesPromotionEligible",
        "eyeComponentAuthority", "packageMutationPerformed", "eyesPromoted", "eyelashStatus",
        "faceSecondaryUnaffected", "humanReviewRequired", "productionActivation",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise HighFidelityEyesPromotionEligibilityError("eyes promotion eligibility fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policyRevision") != POLICY_REVISION:
        raise HighFidelityEyesPromotionEligibilityError("eyes promotion eligibility format/version/policy mismatch")
    _revision(value.get("bodyrigRevision"))
    exact = {
        "previewJobId": component["preview_job_id"],
        "personId": component["person_id"],
        "bodyRevision": component["body_revision"],
        "canonicalBodyId": component["canonical_body_id"],
        "targetModelFamily": component["target_family"],
        "candidatePackageSha256": component["candidate_package_sha256"],
        "componentVisualReviewSha256": _sha256(component_path),
        "componentVisualReviewBodyrigRevision": component["bodyrig_revision"],
        "reviewVrmSha256": review_vrm_sha,
        "irisReviewedRuntimeReceiptSha256": _sha256(reviewed_receipt_path),
        "irisReviewedRuntimeBodyrigRevision": reviewed["bodyrigRevision"],
        "irisCandidateSha256": reviewed["irisCandidateSha256"],
        "irisReviewSha256": iris_review_sha,
        "sourceEyeAppearanceReceiptSha256": reviewed["sourceEyeAppearanceReceiptSha256"],
        "canonicalEyeBakeSha256": reviewed["canonicalEyeBakeSha256"],
    }
    for field, expected in exact.items():
        if str(value.get(field) or "") != str(expected or ""):
            raise HighFidelityEyesPromotionEligibilityError(f"eyes promotion eligibility no longer matches exact authority: {field}")
    if (
        value.get("componentVisualOutcome") != EXPECTED_COMPONENT_OUTCOME
        or value.get("irisAppearanceStatus") != "source-isolated-review-pass"
        or value.get("sameReviewedRuntimeBytes") is not True
        or value.get("sourceEyePixelsUnchanged") is not True
        or value.get("eyesPromotionEligible") is not True
        or value.get("eyeComponentAuthority") is not False
        or value.get("packageMutationPerformed") is not False
        or value.get("eyesPromoted") is not False
        or value.get("eyelashStatus") != "missing"
        or value.get("faceSecondaryUnaffected") is not True
        or value.get("humanReviewRequired") is not True
        or value.get("productionActivation") is not False
    ):
        raise HighFidelityEyesPromotionEligibilityError("eyes promotion eligibility crossed its pre-materialization authority boundary")
    return {**value, "eligibilityPath": str(path)}
