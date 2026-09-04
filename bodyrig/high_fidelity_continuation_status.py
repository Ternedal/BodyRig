from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from .high_fidelity_anatomy_promotion import promotion_status as anatomy_promotion_status
from .high_fidelity_component_review import review_status as component_review_status
from .high_fidelity_eye_promotion import HighFidelityEyePromotionError, read_promotion as read_eye_promotion
from .high_fidelity_eye_runtime_fingerprint import HighFidelityEyeRuntimeFingerprintError, read_fingerprint
from .high_fidelity_eye_runtime_rebuild import HighFidelityEyeRuntimeRebuildError, read_rebuild
from .high_fidelity_eyes_promotion_eligibility import (
    HighFidelityEyesPromotionEligibilityError,
    read_eligibility,
)
from .high_fidelity_face_secondary_preview import HighFidelityFaceSecondaryPreviewError, read_preview
from .high_fidelity_face_secondary_promotion import (
    HighFidelityFaceSecondaryPromotionError,
    read_promotion as read_face_promotion,
)
from .high_fidelity_face_secondary_review import (
    HighFidelityFaceSecondaryReviewError,
    read_review as read_face_review,
)
from .high_fidelity_face_secondary_runtime import HighFidelityFaceSecondaryRuntimeError, read_runtime as read_face_runtime
from .high_fidelity_hair_deformation_review import review_status as hair_deformation_review_status
from .high_fidelity_hair_promotion import (
    HighFidelityHairPromotionError,
    promotion_status as hair_promotion_status,
    read_promotion as read_hair_promotion,
)
from .high_fidelity_package_audit import HighFidelityPackageAuditError, audit_high_fidelity_package
from .high_fidelity_preview_jobs import HighFidelityPreviewError, manager as preview_manager
from .source_iris_isolation import SourceIrisIsolationError, read_candidate as read_iris_candidate
from .source_iris_isolation_review import SourceIrisIsolationReviewError, read_review as read_iris_review
from .source_iris_review_runtime import SourceIrisReviewRuntimeError, read_reviewed_runtime
from .storage import ui_jobs_dir

FORMAT = "bodyrig-high-fidelity-continuation-status"
VERSION = 1
JOB_RE = re.compile(r"^hfpreview-[0-9a-f]{32}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

GATE_ORDER = (
    "preview",
    "component_review",
    "anatomy_promotion",
    "hair_deformation_review",
    "hair_promotion",
    "iris_candidate",
    "iris_review",
    "iris_reviewed_runtime",
    "eyes_eligibility",
    "eye_fingerprint",
    "eye_only_rebuild",
    "eyes_promotion",
    "face_secondary_runtime",
    "face_secondary_preview",
    "face_secondary_review",
    "face_secondary_promotion",
)

GATE_LABELS = {
    "preview": "High-fidelity 6-view preview",
    "component_review": "Component visual review",
    "anatomy_promotion": "Body anatomy promotion",
    "hair_deformation_review": "Hair deformation review",
    "hair_promotion": "Hair promotion",
    "iris_candidate": "Source iris isolation candidate",
    "iris_review": "Source iris isolation human review",
    "iris_reviewed_runtime": "Iris-reviewed runtime sidecar",
    "eyes_eligibility": "Eyes promotion eligibility",
    "eye_fingerprint": "Semantic eye runtime fingerprint",
    "eye_only_rebuild": "Hair-free eye-only runtime rebuild",
    "eyes_promotion": "Eyes package promotion",
    "face_secondary_runtime": "Face-secondary review runtime",
    "face_secondary_preview": "Face-secondary Windows review preview",
    "face_secondary_review": "Face-secondary human review",
    "face_secondary_promotion": "Face-secondary package promotion",
}


class HighFidelityContinuationStatusError(RuntimeError):
    pass


def _job(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if not JOB_RE.fullmatch(clean):
        raise HighFidelityContinuationStatusError("high-fidelity preview job id is not canonical")
    return clean


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _preview_root(job_id: str) -> Path:
    return ui_jobs_dir() / ".high-fidelity-previews" / job_id


def continuation_paths(preview_job_id: str) -> dict[str, Path]:
    job_id = _job(preview_job_id)
    root = _preview_root(job_id)
    continuation = root / "continuation"
    face = continuation / "face-secondary"
    face_preview = face / "windows-preview"
    return {
        "preview_root": root,
        "component_root": root / "components",
        "eye_geometry": root / "components" / "eyes",
        "source_eye_appearance": root / "components" / "eye-appearance",
        "base_runtime": root / "components" / "runtime",
        "continuation_root": continuation,
        "iris_candidate": continuation / "iris-candidate",
        "iris_reviewed_runtime": continuation / "iris-reviewed-runtime",
        "eye_only_runtime": continuation / "eye-only-runtime",
        "face_runtime": face / "runtime",
        "face_preview_root": face_preview,
        "face_preparation": face_preview / "preparation",
        "face_render": face_preview / "render",
        "face_review": face / "human-review",
        "face_promotion": face / "promotion",
    }


def _gate(name: str, state: str, *, reason: str = "", evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    if state not in {"pass", "required", "blocked", "invalid"}:
        state = "blocked"
    return {
        "id": name,
        "label": GATE_LABELS[name],
        "state": state,
        "passed": state == "pass",
        "reason": reason,
        "evidence": evidence or {},
    }


def _quote(value: Any) -> str:
    return '"' + str(value).replace('"', '`"') + '"'


def _next_action(
    job_id: str,
    gate: str,
    paths: dict[str, Path],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = dict(context or {})
    common = {"gate": gate, "operator_input_required": False}
    if gate == "preview":
        return {**common, "command": None, "operator_input_required": True, "reason": "Start the high-fidelity preview from Person Studio after selecting the exact body build and target family."}
    if gate == "component_review":
        return {**common, "command": f'.\\record-high-fidelity-component-review.ps1 -PreviewJobId {_quote(job_id)} <EXPLICIT_REVIEW_FLAGS>', "operator_input_required": True}
    if gate == "anatomy_promotion":
        return {**common, "command": f'.\\promote-high-fidelity-anatomy.ps1 -PreviewJobId {_quote(job_id)}'}
    if gate == "hair_deformation_review":
        return {**common, "command": f'.\\record-high-fidelity-hair-deformation-review.ps1 -PreviewJobId {_quote(job_id)} <EXPLICIT_PHYSICAL_REVIEW_FLAGS>', "operator_input_required": True}
    if gate == "hair_promotion":
        return {**common, "command": f'.\\promote-high-fidelity-hair.ps1 -PreviewJobId {_quote(job_id)}'}
    if gate == "iris_candidate":
        return {
            **common,
            "command": ".\\prepare-source-iris-isolation.ps1 "
            f"-SourceEyeAppearanceDir {_quote(paths['source_eye_appearance'])} -OutputDir {_quote(paths['iris_candidate'])} "
            "-LeftCx <LEFT_CX> -LeftCy <LEFT_CY> -LeftRadius <LEFT_RADIUS> "
            "-RightCx <RIGHT_CX> -RightCy <RIGHT_CY> -RightRadius <RIGHT_RADIUS>",
            "operator_input_required": True,
        }
    if gate == "iris_review":
        return {
            **common,
            "command": ".\\record-source-iris-isolation-review.ps1 "
            f"-CandidateDir {_quote(paths['iris_candidate'])} -SourceEyeAppearanceDir {_quote(paths['source_eye_appearance'])} "
            "-ConfirmIrisIsolationChecklist -QualityNote <QUALITY_NOTE>",
            "operator_input_required": True,
        }
    if gate == "iris_reviewed_runtime":
        return {
            **common,
            "command": ".\\build-source-iris-reviewed-runtime.ps1 "
            f"-BaseRuntimeDir {_quote(paths['base_runtime'])} -IrisCandidateDir {_quote(paths['iris_candidate'])} "
            f"-SourceEyeAppearanceDir {_quote(paths['source_eye_appearance'])} -OutputDir {_quote(paths['iris_reviewed_runtime'])}",
        }
    if gate in {"eyes_eligibility", "eye_fingerprint"}:
        script = "record-high-fidelity-eyes-promotion-eligibility.ps1" if gate == "eyes_eligibility" else "record-high-fidelity-eye-runtime-fingerprint.ps1"
        return {
            **common,
            "command": f'.\\{script} '
            f"-PreviewJobId {_quote(job_id)} -BaseRuntimeDir {_quote(paths['base_runtime'])} "
            f"-IrisCandidateDir {_quote(paths['iris_candidate'])} -SourceEyeAppearanceDir {_quote(paths['source_eye_appearance'])} "
            f"-ReviewedRuntimeDir {_quote(paths['iris_reviewed_runtime'])}",
        }
    if gate == "eye_only_rebuild":
        required = ("candidate_package", "candidate_workspace")
        if any(not ctx.get(name) for name in required):
            return {**common, "command": None, "reason": "Exact candidate package/workspace authority is unavailable; continuation remains fail-closed."}
        return {
            **common,
            "command": ".\\build-source-eye-only-review-runtime.ps1 "
            f"-PreviewJobId {_quote(job_id)} -PackagePath {_quote(ctx['candidate_package'])} "
            f"-BaseRuntimeDir {_quote(paths['base_runtime'])} -IrisCandidateDir {_quote(paths['iris_candidate'])} "
            f"-EyeGeometryDir {_quote(paths['eye_geometry'])} -EyeAppearanceDir {_quote(paths['source_eye_appearance'])} "
            f"-ReviewedRuntimeDir {_quote(paths['iris_reviewed_runtime'])} -CandidateWorkspace {_quote(ctx['candidate_workspace'])} "
            f"-OutputDir {_quote(paths['eye_only_runtime'])}",
        }
    if gate == "eyes_promotion":
        required = ("candidate_package", "hair_package")
        if any(not ctx.get(name) for name in required):
            return {**common, "command": None, "reason": "Exact candidate/hair-promoted package authority is unavailable; continuation remains fail-closed."}
        return {
            **common,
            "command": ".\\promote-high-fidelity-eyes.ps1 "
            f"-PreviewJobId {_quote(job_id)} -CandidatePackage {_quote(ctx['candidate_package'])} -TargetPackage {_quote(ctx['hair_package'])} "
            f"-BaseRuntimeDir {_quote(paths['base_runtime'])} -IrisCandidateDir {_quote(paths['iris_candidate'])} "
            f"-SourceEyeAppearanceDir {_quote(paths['source_eye_appearance'])} -ReviewedRuntimeDir {_quote(paths['iris_reviewed_runtime'])} "
            f"-EyeRuntimeDir {_quote(paths['eye_only_runtime'])}",
        }
    if gate == "face_secondary_runtime":
        if not ctx.get("eyes_package"):
            return {**common, "command": None, "reason": "Exact eyes-promoted package authority is unavailable; continuation remains fail-closed."}
        return {**common, "command": ".\\build-high-fidelity-face-secondary-review-runtime.ps1 " f"-PackagePath {_quote(ctx['eyes_package'])} -OutputDir {_quote(paths['face_runtime'])}"}
    if gate == "face_secondary_preview":
        if not ctx.get("eyes_package"):
            return {**common, "command": None, "reason": "Exact eyes-promoted package authority is unavailable; continuation remains fail-closed."}
        return {**common, "command": ".\\run-high-fidelity-face-secondary-windows-preview.ps1 " f"-PackagePath {_quote(ctx['eyes_package'])} -RuntimeDir {_quote(paths['face_runtime'])} -OutputDir {_quote(paths['face_preview_root'])}"}
    if gate == "face_secondary_review":
        return {
            **common,
            "command": ".\\record-high-fidelity-face-secondary-review.ps1 "
            f"-PreparationDir {_quote(paths['face_preparation'])} -RuntimeDir {_quote(paths['face_runtime'])} "
            f"-RenderDir {_quote(paths['face_render'])} -OutputDir {_quote(paths['face_review'])} "
            "-QualityNote <QUALITY_NOTE> -NeutralFacePreserved -EyebrowSourceAppearanceAcceptable "
            "-LipBoundarySourceAppearanceAcceptable -MouthOpenPoseReviewed -MouthInteriorVisibleAndPlausible "
            "-UpperTeethVisibleAndPlausible -LowerTeethVisibleAndJawBound -TeethNoObviousClippingAtOpenPose "
            "-EyelashesVisibleAndPlausible -EyelashesNoObviousEyeSurfaceClipping",
            "operator_input_required": True,
        }
    if gate == "face_secondary_promotion":
        if not ctx.get("eyes_package"):
            return {**common, "command": None, "reason": "Exact eyes-promoted source package authority is unavailable; continuation remains fail-closed."}
        return {
            **common,
            "command": ".\\promote-high-fidelity-face-secondary.ps1 "
            f"-PreparationDir {_quote(paths['face_preparation'])} -RuntimeDir {_quote(paths['face_runtime'])} "
            f"-RenderDir {_quote(paths['face_render'])} -HumanReviewDir {_quote(paths['face_review'])} "
            f"-SourcePackage {_quote(ctx['eyes_package'])} -OutputDir {_quote(paths['face_promotion'])}",
        }
    return {**common, "command": None}


def _candidate_package(preview: Mapping[str, Any], paths: Mapping[str, Path]) -> Path:
    expected = str(preview.get("candidate_package_sha256") or "").lower()
    if not SHA_RE.fullmatch(expected):
        raise HighFidelityContinuationStatusError("succeeded preview lacks canonical candidate package SHA")
    anatomy = paths["preview_root"] / "anatomy"
    matches = [path for path in anatomy.rglob("*.mrbody") if path.is_file() and _sha256(path) == expected]
    if len(matches) != 1:
        raise HighFidelityContinuationStatusError(f"expected exactly one persisted anatomy candidate package for SHA {expected}; found {len(matches)}")
    return matches[0].resolve()


def _candidate_workspace(paths: Mapping[str, Path]) -> Path:
    receipt = paths["component_root"] / "subject-component-discovery.json"
    try:
        value = json.loads(receipt.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityContinuationStatusError("validated component-discovery receipt is unavailable for operator continuation") from exc
    candidate = Path(str(value.get("candidate_workspace") or "")).expanduser().resolve()
    root = paths["preview_root"].resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HighFidelityContinuationStatusError("component-discovery candidate workspace escaped the persisted preview root") from exc
    if not candidate.is_dir():
        raise HighFidelityContinuationStatusError("component-discovery candidate workspace is missing")
    return candidate


def _simple_state(value: Mapping[str, Any]) -> str:
    raw = str(value.get("state") or "blocked")
    if value.get("passed") is True or raw == "pass":
        return "pass"
    return raw if raw in {"required", "blocked", "invalid"} else "blocked"


def _missing_or_invalid(exc: Exception, path: Path | None = None) -> str:
    if path is not None and not path.exists():
        return "required"
    return "required" if "missing" in str(exc).lower() or "has not been" in str(exc).lower() else "invalid"


def inspect_continuation(preview_job_id: str) -> dict[str, Any]:
    job_id = _job(preview_job_id)
    paths = continuation_paths(job_id)
    gates: list[dict[str, Any]] = []
    context: dict[str, Any] = {}
    current_package: Path | None = None
    current_sha: str | None = None
    components: dict[str, str] = {}

    try:
        preview = preview_manager.get(job_id)
    except HighFidelityPreviewError as exc:
        gates.append(_gate("preview", "blocked", reason=str(exc)))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)
    if preview.get("status") != "succeeded":
        state = "required" if preview.get("status") in {"failed", "interrupted"} else "blocked"
        gates.append(_gate("preview", state, reason=f"preview status is {preview.get('status') or 'unknown'}"))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)
    gates.append(_gate("preview", "pass", evidence={"candidate_package_sha256": preview.get("candidate_package_sha256")}))

    try:
        candidate = _candidate_package(preview, paths)
    except HighFidelityContinuationStatusError as exc:
        gates.append(_gate("component_review", "invalid", reason=str(exc)))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)
    current_package = candidate
    current_sha = _sha256(candidate)
    context["candidate_package"] = str(candidate)

    simple: tuple[tuple[str, Callable[[str], dict[str, Any]]], ...] = (
        ("component_review", component_review_status),
        ("anatomy_promotion", anatomy_promotion_status),
        ("hair_deformation_review", hair_deformation_review_status),
        ("hair_promotion", hair_promotion_status),
    )
    for name, fn in simple:
        value = fn(job_id)
        state = _simple_state(value)
        gates.append(_gate(name, state, reason=str(value.get("reason") or ""), evidence={k: v for k, v in value.items() if k != "reason"}))
        if state != "pass":
            return _result(job_id, gates, paths, current_package, current_sha, components, context)
        if name == "hair_promotion":
            try:
                promoted = read_hair_promotion(job_id)
            except HighFidelityHairPromotionError as exc:
                gates[-1] = _gate("hair_promotion", "invalid", reason=str(exc))
                return _result(job_id, gates, paths, current_package, current_sha, components, context)
            hair_package = Path(str(promoted.get("package_path") or "")).expanduser().resolve()
            expected = str(value.get("promoted_package_sha256") or "")
            if not hair_package.is_file() or _sha256(hair_package) != expected:
                gates[-1] = _gate("hair_promotion", "invalid", reason="hair promotion status does not bind its exact promoted package bytes")
                return _result(job_id, gates, paths, current_package, current_sha, components, context)
            current_package = hair_package
            current_sha = expected
            context["hair_package"] = str(hair_package)
            components = dict(promoted.get("components_after") or {})

    try:
        context["candidate_workspace"] = str(_candidate_workspace(paths))
    except HighFidelityContinuationStatusError:
        # This is needed only once the eye-only rebuild command becomes current.
        pass

    source_eye = paths["source_eye_appearance"]
    base_runtime = paths["base_runtime"]
    iris_candidate = paths["iris_candidate"]
    iris_runtime = paths["iris_reviewed_runtime"]

    if not iris_candidate.exists():
        gates.append(_gate("iris_candidate", "required", reason="canonical iris candidate has not been created"))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)
    try:
        iris = read_iris_candidate(iris_candidate, source_eye_appearance_dir=source_eye)
        gates.append(_gate("iris_candidate", "pass", evidence={"candidate_sha256": _sha256(Path(iris["candidatePath"]))}))
    except SourceIrisIsolationError as exc:
        gates.append(_gate("iris_candidate", "invalid", reason=str(exc)))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)

    try:
        iris_review = read_iris_review(candidate_dir=iris_candidate, source_eye_appearance_dir=source_eye)
        gates.append(_gate("iris_review", "pass", evidence={"review_sha256": _sha256(Path(iris_review["reviewPath"]))}))
    except SourceIrisIsolationReviewError as exc:
        gates.append(_gate("iris_review", _missing_or_invalid(exc), reason=str(exc)))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)

    if not iris_runtime.exists():
        gates.append(_gate("iris_reviewed_runtime", "required", reason="canonical iris-reviewed runtime has not been built"))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)
    try:
        reviewed = read_reviewed_runtime(
            base_runtime_dir=base_runtime,
            iris_candidate_dir=iris_candidate,
            source_eye_appearance_dir=source_eye,
            reviewed_runtime_dir=iris_runtime,
        )
        gates.append(_gate("iris_reviewed_runtime", "pass", evidence={"reviewed_vrm_sha256": reviewed.get("reviewedVrmSha256")}))
    except SourceIrisReviewRuntimeError as exc:
        gates.append(_gate("iris_reviewed_runtime", "invalid", reason=str(exc)))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)

    try:
        eligibility = read_eligibility(
            job_id,
            base_runtime_dir=base_runtime,
            iris_candidate_dir=iris_candidate,
            source_eye_appearance_dir=source_eye,
            reviewed_runtime_dir=iris_runtime,
        )
        gates.append(_gate("eyes_eligibility", "pass", evidence={"eligibility_path": eligibility.get("eligibilityPath")}))
    except HighFidelityEyesPromotionEligibilityError as exc:
        gates.append(_gate("eyes_eligibility", _missing_or_invalid(exc), reason=str(exc)))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)

    try:
        fingerprint = read_fingerprint(
            job_id,
            base_runtime_dir=base_runtime,
            iris_candidate_dir=iris_candidate,
            source_eye_appearance_dir=source_eye,
            reviewed_runtime_dir=iris_runtime,
        )
        gates.append(_gate("eye_fingerprint", "pass", evidence={"fingerprint_sha256": fingerprint.get("fingerprintSha256")}))
    except HighFidelityEyeRuntimeFingerprintError as exc:
        gates.append(_gate("eye_fingerprint", _missing_or_invalid(exc), reason=str(exc)))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)

    bridge = _repo_root() / "bodyrig" / "bridges" / "sith_eye_review_runtime.py"
    bridge_sha = _sha256(bridge)
    eye_runtime = paths["eye_only_runtime"]
    try:
        rebuild = read_rebuild(
            job_id,
            package_path=candidate,
            base_runtime_dir=base_runtime,
            iris_candidate_dir=iris_candidate,
            source_eye_appearance_dir=source_eye,
            reviewed_runtime_dir=iris_runtime,
            staging_dir=eye_runtime,
            bridge_script_sha256=bridge_sha,
        )
        gates.append(_gate("eye_only_rebuild", "pass", evidence={"rebuilt_vrm_sha256": rebuild.get("rebuiltReviewVrmSha256")}))
    except HighFidelityEyeRuntimeRebuildError as exc:
        gates.append(_gate("eye_only_rebuild", _missing_or_invalid(exc, eye_runtime), reason=str(exc)))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)

    hair_package = Path(str(context.get("hair_package") or "")).expanduser().resolve()
    if not hair_package.is_file():
        gates.append(_gate("eyes_promotion", "invalid", reason="hair-promoted destination package is unavailable"))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)
    try:
        eyes = read_eye_promotion(
            job_id,
            candidate_package_path=candidate,
            target_package_path=hair_package,
            base_runtime_dir=base_runtime,
            iris_candidate_dir=iris_candidate,
            source_eye_appearance_dir=source_eye,
            reviewed_runtime_dir=iris_runtime,
            eye_runtime_dir=eye_runtime,
            bridge_script_sha256=bridge_sha,
        )
        eye_package = Path(str(eyes.get("package_path") or "")).expanduser().resolve()
        promoted_sha = str(eyes.get("promotedPackageSha256") or "")
        if not eye_package.is_file() or _sha256(eye_package) != promoted_sha:
            raise HighFidelityEyePromotionError("eye promotion no longer binds exact promoted package bytes")
        current_package = eye_package
        current_sha = promoted_sha
        context["eyes_package"] = str(eye_package)
        components = dict(eyes.get("componentsAfter") or {})
        gates.append(_gate("eyes_promotion", "pass", evidence={"promoted_package_sha256": promoted_sha}))
    except HighFidelityEyePromotionError as exc:
        gates.append(_gate("eyes_promotion", _missing_or_invalid(exc), reason=str(exc)))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)

    try:
        face_runtime = read_face_runtime(paths["face_runtime"])
        if face_runtime.get("sourcePackageSha256") != current_sha:
            raise HighFidelityFaceSecondaryRuntimeError("face-secondary runtime targets different eyes-promoted package bytes")
        gates.append(_gate("face_secondary_runtime", "pass", evidence={"review_vrm_sha256": face_runtime.get("reviewVrmSha256")}))
    except HighFidelityFaceSecondaryRuntimeError as exc:
        gates.append(_gate("face_secondary_runtime", _missing_or_invalid(exc, paths["face_runtime"]), reason=str(exc)))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)

    try:
        preview_value = read_preview(paths["face_preparation"], paths["face_runtime"], paths["face_render"])
        gates.append(_gate("face_secondary_preview", "pass", evidence={"preview_authority_path": preview_value.get("previewAuthorityPath")}))
    except HighFidelityFaceSecondaryPreviewError as exc:
        gates.append(_gate("face_secondary_preview", _missing_or_invalid(exc, paths["face_preview_root"]), reason=str(exc)))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)

    try:
        face_review = read_face_review(paths["face_preparation"], paths["face_runtime"], paths["face_render"], paths["face_review"])
        gates.append(_gate("face_secondary_review", "pass", evidence={"review_path": face_review.get("reviewPath")}))
    except HighFidelityFaceSecondaryReviewError as exc:
        gates.append(_gate("face_secondary_review", _missing_or_invalid(exc, paths["face_review"]), reason=str(exc)))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)

    try:
        face = read_face_promotion(
            preparation_dir=paths["face_preparation"],
            runtime_dir=paths["face_runtime"],
            render_dir=paths["face_render"],
            human_review_dir=paths["face_review"],
            source_package_path=current_package,
            output_dir=paths["face_promotion"],
        )
        final_package = Path(str(face.get("promotedPackagePath") or "")).expanduser().resolve()
        promoted_sha = str(face.get("promotedPackageSha256") or "")
        if not final_package.is_file() or _sha256(final_package) != promoted_sha:
            raise HighFidelityFaceSecondaryPromotionError("face-secondary promotion no longer binds exact promoted package bytes")
        current_package = final_package
        current_sha = promoted_sha
        components = dict(face.get("componentsAfter") or {})
        gates.append(_gate("face_secondary_promotion", "pass", evidence={"promoted_package_sha256": promoted_sha}))
    except HighFidelityFaceSecondaryPromotionError as exc:
        gates.append(_gate("face_secondary_promotion", _missing_or_invalid(exc, paths["face_promotion"]), reason=str(exc)))
        return _result(job_id, gates, paths, current_package, current_sha, components, context)

    return _result(job_id, gates, paths, current_package, current_sha, components, context)


def _result(
    job_id: str,
    gates: list[dict[str, Any]],
    paths: dict[str, Path],
    package_path: Path | None,
    package_sha: str | None,
    components: dict[str, str],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    passed = {item["id"] for item in gates if item["state"] == "pass"}
    next_gate = next((name for name in GATE_ORDER if name not in passed), None)
    high_fidelity_complete = False
    audit: dict[str, Any] | None = None
    if next_gate is None and package_path is not None and package_path.is_file():
        try:
            audit = audit_high_fidelity_package(package_path)
        except HighFidelityPackageAuditError as exc:
            gates[-1] = _gate("face_secondary_promotion", "invalid", reason=f"final package audit failed: {exc}")
            next_gate = "face_secondary_promotion"
        else:
            components = dict(audit["components"])
            high_fidelity_complete = bool(
                audit["high_fidelity_ready"]
                and components
                and all(value == "complete" for value in components.values())
            )
            if not high_fidelity_complete:
                gates[-1] = _gate("face_secondary_promotion", "invalid", reason="all continuation gates passed but final package is not high-fidelity component complete")
                next_gate = "face_secondary_promotion"
    state = "complete" if high_fidelity_complete else (
        "blocked" if gates and gates[-1]["state"] in {"blocked", "invalid"} else "incomplete"
    )
    return {
        "format": FORMAT,
        "version": VERSION,
        "preview_job_id": job_id,
        "state": state,
        "gates": gates,
        "next_gate": None if high_fidelity_complete else (_next_action(job_id, next_gate, paths, context) if next_gate else None),
        "current_package_path": str(package_path) if package_path is not None else None,
        "current_package_sha256": package_sha,
        "components": components,
        "high_fidelity_complete": high_fidelity_complete,
        "high_fidelity_human_review_required": high_fidelity_complete,
        "physical_windows_acceptance_required": True,
        "quest_acceptance_required": True,
        "final_release_required": True,
        "production_ready": False,
        "production_activation": False,
        "final_audit": audit,
    }
