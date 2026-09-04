from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .source_iris_isolation import SourceIrisIsolationError, read_candidate

FORMAT = "bodyrig-source-iris-isolation-review"
VERSION = 1
POLICY_REVISION = "bodyrig-source-iris-isolation-review-v1"
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
CHECKLIST_FIELDS = {
    "source_eye_crops_reviewed",
    "left_iris_boundary_matches_source",
    "right_iris_boundary_matches_source",
    "pupil_not_misidentified_as_iris_boundary",
    "sclera_not_included_as_iris_identity",
    "bilateral_iris_identity_consistent",
}


class SourceIrisIsolationReviewError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceIrisIsolationReviewError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise SourceIrisIsolationReviewError(f"{label} must be a JSON object")
    return value


def review_path(candidate_dir: str | Path, *, candidate_sha256: str) -> Path:
    candidate_root = Path(candidate_dir).expanduser().resolve()
    return candidate_root / f"iris-isolation-review.{candidate_sha256}.json"


def write_review(
    *,
    candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    bodyrig_revision: str,
    checklist: Mapping[str, Any],
    quality_note: str,
) -> dict[str, Any]:
    revision = str(bodyrig_revision or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise SourceIrisIsolationReviewError("BodyRig revision must be a canonical lowercase Git SHA")
    try:
        candidate = read_candidate(candidate_dir, source_eye_appearance_dir=source_eye_appearance_dir)
    except SourceIrisIsolationError as exc:
        raise SourceIrisIsolationReviewError(f"iris isolation candidate authority failed: {exc}") from exc
    normalized = dict(checklist)
    if set(normalized) != CHECKLIST_FIELDS:
        raise SourceIrisIsolationReviewError("iris isolation review checklist fields are not canonical")
    for field in CHECKLIST_FIELDS:
        if normalized.get(field) is not True:
            raise SourceIrisIsolationReviewError(f"iris isolation review did not explicitly pass {field}")
    note = str(quality_note or "").strip()
    if not note:
        raise SourceIrisIsolationReviewError("iris isolation review requires a non-empty quality note")
    if len(note) > 4000:
        raise SourceIrisIsolationReviewError("iris isolation review quality note exceeds 4000 characters")

    candidate_path = Path(str(candidate["candidatePath"])).resolve()
    left_path = Path(str(candidate["leftPath"])).resolve()
    right_path = Path(str(candidate["rightPath"])).resolve()
    candidate_sha = _sha256(candidate_path)
    path = review_path(candidate_dir, candidate_sha256=candidate_sha)
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "bodyrigRevision": revision,
        "candidateSha256": candidate_sha,
        "sourceEyeAppearanceReceiptSha256": candidate["sourceEyeAppearanceReceiptSha256"],
        "leftIrisCandidateSha256": _sha256(left_path),
        "rightIrisCandidateSha256": _sha256(right_path),
        "leftAnnotation": dict(candidate["left"]["annotation"]),
        "rightAnnotation": dict(candidate["right"]["annotation"]),
        "reviewedUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "checklist": {field: True for field in sorted(CHECKLIST_FIELDS)},
        "qualityNote": note,
        "sourceDerived": True,
        "humanGuidedIsolation": True,
        "irisIdentityIsolated": True,
        "irisAppearanceStatus": "source-isolated-review-pass",
        "eyeComponentAuthority": False,
        "eyesPromotionEligible": False,
        "humanReviewComplete": True,
        "productionActivation": False,
    }
    raw = (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SourceIrisIsolationReviewError(f"refusing to overwrite existing iris isolation review: {path}") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    try:
        read_review(candidate_dir=candidate_dir, source_eye_appearance_dir=source_eye_appearance_dir)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {**receipt, "reviewPath": str(path)}


def read_review(*, candidate_dir: str | Path, source_eye_appearance_dir: str | Path) -> dict[str, Any]:
    try:
        candidate = read_candidate(candidate_dir, source_eye_appearance_dir=source_eye_appearance_dir)
    except SourceIrisIsolationError as exc:
        raise SourceIrisIsolationReviewError(f"iris isolation candidate authority failed: {exc}") from exc
    candidate_path = Path(str(candidate["candidatePath"])).resolve()
    left_path = Path(str(candidate["leftPath"])).resolve()
    right_path = Path(str(candidate["rightPath"])).resolve()
    candidate_sha = _sha256(candidate_path)
    path = review_path(candidate_dir, candidate_sha256=candidate_sha)
    if not path.is_file():
        raise SourceIrisIsolationReviewError("iris isolation human review is missing")
    value = _read_json(path, label="iris isolation human review")
    required = {
        "format", "version", "policyRevision", "bodyrigRevision", "candidateSha256",
        "sourceEyeAppearanceReceiptSha256", "leftIrisCandidateSha256", "rightIrisCandidateSha256",
        "leftAnnotation", "rightAnnotation", "reviewedUtc", "checklist", "qualityNote",
        "sourceDerived", "humanGuidedIsolation", "irisIdentityIsolated", "irisAppearanceStatus",
        "eyeComponentAuthority", "eyesPromotionEligible", "humanReviewComplete", "productionActivation",
    }
    if set(value) != required:
        raise SourceIrisIsolationReviewError("iris isolation review fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policyRevision") != POLICY_REVISION:
        raise SourceIrisIsolationReviewError("iris isolation review format/version/policy mismatch")
    revision = str(value.get("bodyrigRevision") or "")
    if not REVISION_RE.fullmatch(revision):
        raise SourceIrisIsolationReviewError("iris isolation review BodyRig revision is invalid")
    exact = {
        "candidateSha256": candidate_sha,
        "sourceEyeAppearanceReceiptSha256": candidate["sourceEyeAppearanceReceiptSha256"],
        "leftIrisCandidateSha256": _sha256(left_path),
        "rightIrisCandidateSha256": _sha256(right_path),
        "leftAnnotation": dict(candidate["left"]["annotation"]),
        "rightAnnotation": dict(candidate["right"]["annotation"]),
    }
    for field, expected in exact.items():
        if value.get(field) != expected:
            raise SourceIrisIsolationReviewError(f"iris isolation review no longer matches exact candidate authority: {field}")
    checklist = value.get("checklist")
    if not isinstance(checklist, dict) or set(checklist) != CHECKLIST_FIELDS or any(checklist.get(field) is not True for field in CHECKLIST_FIELDS):
        raise SourceIrisIsolationReviewError("iris isolation review checklist is not fully passed")
    if not str(value.get("qualityNote") or "").strip():
        raise SourceIrisIsolationReviewError("iris isolation review quality note is empty")
    if (
        value.get("sourceDerived") is not True
        or value.get("humanGuidedIsolation") is not True
        or value.get("irisIdentityIsolated") is not True
        or value.get("irisAppearanceStatus") != "source-isolated-review-pass"
        or value.get("eyeComponentAuthority") is not False
        or value.get("eyesPromotionEligible") is not False
        or value.get("humanReviewComplete") is not True
        or value.get("productionActivation") is not False
    ):
        raise SourceIrisIsolationReviewError("iris isolation review crossed the component/production authority boundary")
    return {**value, "reviewPath": str(path)}
