from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .high_fidelity_face_secondary_preview import (
    HighFidelityFaceSecondaryPreviewError,
    read_preview,
)
from .high_fidelity_face_secondary_runtime import (
    HighFidelityFaceSecondaryRuntimeError,
    read_runtime,
)

FORMAT = "bodyrig-high-fidelity-face-secondary-human-review"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-face-secondary-human-review-v1"
REVIEW_NAME = "face-secondary-human-review.json"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
COMPONENTS = (
    "eyebrow_appearance",
    "lip_boundary",
    "mouth_interior",
    "teeth",
    "eyelashes",
)
CHECKLIST_FIELDS = (
    "neutral_face_preserved",
    "eyebrow_source_appearance_acceptable",
    "lip_boundary_source_appearance_acceptable",
    "mouth_open_pose_reviewed",
    "mouth_interior_visible_and_plausible",
    "upper_teeth_visible_and_plausible",
    "lower_teeth_visible_and_jaw_bound",
    "teeth_no_obvious_clipping_at_open_pose",
    "eyelashes_visible_and_plausible",
    "eyelashes_no_obvious_eye_surface_clipping",
)


class HighFidelityFaceSecondaryReviewError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(clean):
        raise HighFidelityFaceSecondaryReviewError(f"{label} is not a canonical SHA-256")
    return clean


def _revision(value: Any, *, label: str = "BodyRig revision") -> str:
    clean = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(clean):
        raise HighFidelityFaceSecondaryReviewError(f"{label} is not a canonical Git SHA")
    return clean


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityFaceSecondaryReviewError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise HighFidelityFaceSecondaryReviewError(f"{label} must be a JSON object")
    return value


def _current_authority(preparation_dir: Path, runtime_dir: Path, render_dir: Path) -> dict[str, Any]:
    try:
        preview = read_preview(preparation_dir, runtime_dir, render_dir)
        runtime = read_runtime(runtime_dir)
    except (HighFidelityFaceSecondaryPreviewError, HighFidelityFaceSecondaryRuntimeError) as exc:
        raise HighFidelityFaceSecondaryReviewError(str(exc)) from exc

    expected_candidates = {component: "partial" for component in COMPONENTS}
    if runtime.get("candidateComponents") != expected_candidates:
        raise HighFidelityFaceSecondaryReviewError("face-secondary runtime candidate component set is not canonical review-pending v1")
    if runtime.get("semanticAnchorAuthority") != "licensed-smplx-joint-topology-v1":
        raise HighFidelityFaceSecondaryReviewError("face-secondary runtime lacks licensed SMPL-X semantic anchor authority")
    if runtime.get("genericSecondaryAnatomy") is not True:
        raise HighFidelityFaceSecondaryReviewError("face-secondary review requires explicit generic secondary anatomy disclosure")
    if runtime.get("sourceDerivedIdentitySynthesis") is not False or runtime.get("generativeIdentitySynthesis") is not False:
        raise HighFidelityFaceSecondaryReviewError("face-secondary runtime crossed identity-synthesis boundary")
    if runtime.get("comparisonOnly") is not True or runtime.get("humanReviewRequired") is not True or runtime.get("faceSecondaryComponentAuthority") is not False or runtime.get("packageMutationPerformed") is not False or runtime.get("productionActivation") is not False:
        raise HighFidelityFaceSecondaryReviewError("face-secondary runtime crossed review-only authority boundary")

    preview_path = Path(preview["previewAuthorityPath"]).resolve()
    runtime_receipt = Path(runtime["receiptPath"]).resolve()
    review_vrm = Path(runtime["reviewVrmPath"]).resolve()
    for path, label in ((preview_path, "preview authority"), (runtime_receipt, "runtime receipt"), (review_vrm, "review VRM")):
        if not path.is_file():
            raise HighFidelityFaceSecondaryReviewError(f"face-secondary {label} is missing")

    return {
        "bodyrigRevision": _revision(preview.get("bodyrigRevision")),
        "canonicalBodyId": str(preview.get("canonicalBodyId") or ""),
        "sourcePackageSha256": _sha(preview.get("sourcePackageSha256"), label="source package SHA-256"),
        "sourceRuntimeReceiptSha256": _sha(preview.get("sourceRuntimeReceiptSha256"), label="runtime receipt SHA-256"),
        "sourceReviewVrmSha256": _sha(preview.get("sourceReviewVrmSha256"), label="review VRM SHA-256"),
        "comparisonPackageSha256": _sha(preview.get("comparisonPackageSha256"), label="comparison package SHA-256"),
        "previewAuthoritySha256": _sha256_file(preview_path),
        "comparisonAuthoritySha256": _sha(preview.get("comparisonAuthoritySha256"), label="comparison authority SHA-256"),
        "renderManifestSha256": _sha(preview.get("renderManifestSha256"), label="render manifest SHA-256"),
        "canonicalViewSha256": dict(preview.get("canonicalViewSha256") or {}),
        "diagnosticViewSha256": dict(preview.get("diagnosticViewSha256") or {}),
        "semanticAnchorAuthority": str(runtime["semanticAnchorAuthority"]),
        "genericSecondaryAnatomy": True,
    }


def write_review(
    preparation_dir: str | Path,
    runtime_dir: str | Path,
    render_dir: str | Path,
    output_dir: str | Path,
    *,
    bodyrig_revision: str,
    checklist: Mapping[str, Any],
    quality_note: str,
) -> dict[str, Any]:
    preparation_root = Path(preparation_dir).expanduser().resolve()
    runtime_root = Path(runtime_dir).expanduser().resolve()
    render_root = Path(render_dir).expanduser().resolve()
    root = Path(output_dir).expanduser().resolve()
    if root.exists():
        raise HighFidelityFaceSecondaryReviewError("face-secondary human review output is create-only")

    authority = _current_authority(preparation_root, runtime_root, render_root)
    supplied_revision = _revision(bodyrig_revision)
    if supplied_revision != authority["bodyrigRevision"]:
        raise HighFidelityFaceSecondaryReviewError("face-secondary human review checkout revision differs from preview authority")

    normalized = dict(checklist)
    if set(normalized) != set(CHECKLIST_FIELDS):
        raise HighFidelityFaceSecondaryReviewError("face-secondary human review checklist fields are not canonical")
    for field in CHECKLIST_FIELDS:
        if normalized.get(field) is not True:
            raise HighFidelityFaceSecondaryReviewError(f"face-secondary human review did not explicitly pass {field}")
    note = str(quality_note or "").strip()
    if not note:
        raise HighFidelityFaceSecondaryReviewError("face-secondary human review requires a non-empty quality note")
    if len(note) > 4000:
        raise HighFidelityFaceSecondaryReviewError("face-secondary human review quality note exceeds 4000 characters")

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        **authority,
        "reviewedUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "checklist": {field: True for field in CHECKLIST_FIELDS},
        "qualityNote": note,
        "componentReviewOutcome": {component: "pass" for component in COMPONENTS},
        "teethReviewAuthority": {
            "upperVisibleAndPlausible": True,
            "lowerVisibleAndJawBound": True,
            "openPoseClippingAcceptable": True,
        },
        "humanReviewComplete": True,
        "faceSecondaryPromotionEligible": True,
        "faceSecondaryComponentAuthority": False,
        "packageMutationPerformed": False,
        "productionActivation": False,
    }
    root.mkdir(parents=True)
    path = root / REVIEW_NAME
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except Exception:
        path.unlink(missing_ok=True)
        try:
            root.rmdir()
        except OSError:
            pass
        raise
    return {**receipt, "reviewPath": str(path)}


def read_review(
    preparation_dir: str | Path,
    runtime_dir: str | Path,
    render_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    root = Path(output_dir).expanduser().resolve()
    path = root / REVIEW_NAME
    if not path.is_file():
        raise HighFidelityFaceSecondaryReviewError("face-secondary human review is missing")
    value = _read_json(path, label="face-secondary human review")
    authority = _current_authority(
        Path(preparation_dir).expanduser().resolve(),
        Path(runtime_dir).expanduser().resolve(),
        Path(render_dir).expanduser().resolve(),
    )
    required_fields = {
        "format", "version", "policyRevision", *authority.keys(), "reviewedUtc", "checklist", "qualityNote",
        "componentReviewOutcome", "teethReviewAuthority", "humanReviewComplete", "faceSecondaryPromotionEligible",
        "faceSecondaryComponentAuthority", "packageMutationPerformed", "productionActivation",
    }
    if set(value) != required_fields:
        raise HighFidelityFaceSecondaryReviewError("face-secondary human review fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policyRevision") != POLICY_REVISION:
        raise HighFidelityFaceSecondaryReviewError("face-secondary human review format/version/policy mismatch")
    for field, expected in authority.items():
        if value.get(field) != expected:
            raise HighFidelityFaceSecondaryReviewError(f"face-secondary human review is stale: {field}")
    checklist = value.get("checklist")
    if not isinstance(checklist, dict) or set(checklist) != set(CHECKLIST_FIELDS) or any(checklist.get(field) is not True for field in CHECKLIST_FIELDS):
        raise HighFidelityFaceSecondaryReviewError("face-secondary human review checklist is not fully passed")
    if value.get("componentReviewOutcome") != {component: "pass" for component in COMPONENTS}:
        raise HighFidelityFaceSecondaryReviewError("face-secondary component review outcome is not canonical PASS")
    if value.get("teethReviewAuthority") != {"upperVisibleAndPlausible": True, "lowerVisibleAndJawBound": True, "openPoseClippingAcceptable": True}:
        raise HighFidelityFaceSecondaryReviewError("face-secondary teeth review authority is incomplete")
    if not str(value.get("qualityNote") or "").strip() or not str(value.get("reviewedUtc") or "").strip():
        raise HighFidelityFaceSecondaryReviewError("face-secondary human review lacks review note/time")
    if value.get("humanReviewComplete") is not True or value.get("faceSecondaryPromotionEligible") is not True:
        raise HighFidelityFaceSecondaryReviewError("face-secondary human review is not promotion-eligible")
    if value.get("faceSecondaryComponentAuthority") is not False or value.get("packageMutationPerformed") is not False or value.get("productionActivation") is not False:
        raise HighFidelityFaceSecondaryReviewError("face-secondary human review crossed its authority boundary")
    return {**value, "reviewPath": str(path)}
