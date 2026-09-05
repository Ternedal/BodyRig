from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .high_fidelity_package_audit import HighFidelityPackageAuditError, audit_high_fidelity_package

FORMAT = "bodyrig-high-fidelity-human-review"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-human-review-v1"
CHECKLIST_FIELDS = {
    "source_identity_match_acceptable",
    "anatomy_geometry_acceptable",
    "skin_appearance_acceptable",
    "hair_geometry_appearance_acceptable",
    "eye_geometry_appearance_acceptable",
    "face_secondary_acceptable",
    "full_body_multiview_reviewed",
    "face_closeup_reviewed",
}
TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "body_id",
    "package_sha256",
    "component_state_sha256",
    "reviewed_utc",
    "checklist",
    "quality_note",
    "human_review_complete",
    "production_activation",
}
_PLACEHOLDER_NOTE = re.compile(r"^<[^>]+>$")


class HighFidelityHumanReviewError(RuntimeError):
    pass


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _quality_note(value: Any) -> str:
    note = str(value or "").strip()
    if not note:
        raise HighFidelityHumanReviewError("high-fidelity human review requires a non-empty quality note")
    if _PLACEHOLDER_NOTE.fullmatch(note):
        raise HighFidelityHumanReviewError(
            "high-fidelity human review quality note is still a generated placeholder; record the operator's actual review"
        )
    return note


def _component_state(audit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "components": dict(audit.get("components") or {}),
        "high_fidelity_ready": bool(audit.get("high_fidelity_ready")),
        "top_level_blockers": list(audit.get("top_level_blockers") or []),
        "face_secondary_components": dict(audit.get("face_secondary_components") or {}),
        "face_secondary_ready": bool(audit.get("face_secondary_ready")),
        "face_secondary_blockers": list(audit.get("face_secondary_blockers") or []),
        "semantic_vertex_map_authority": str(audit.get("semantic_vertex_map_authority") or "unavailable"),
        "human_review_required": bool(audit.get("human_review_required", True)),
    }


def component_state_sha256(audit: Mapping[str, Any]) -> str:
    return _sha256_bytes(_canonical_json(_component_state(audit)))


def _strict_ready_audit(package: Path) -> dict[str, Any]:
    try:
        audit = audit_high_fidelity_package(package)
    except (OSError, HighFidelityPackageAuditError) as exc:
        raise HighFidelityHumanReviewError(f"high-fidelity package audit failed: {exc}") from exc
    if audit.get("high_fidelity_ready") is not True:
        blockers = list(audit.get("top_level_blockers") or [])
        detail = ", ".join(str(item) for item in blockers) or "unknown component blocker"
        raise HighFidelityHumanReviewError(
            f"high-fidelity human review cannot be recorded before all component gates are complete: {detail}"
        )
    if audit.get("face_secondary_ready") is not True:
        raise HighFidelityHumanReviewError("high-fidelity human review requires complete face-secondary component authority")
    if list(audit.get("top_level_blockers") or []):
        raise HighFidelityHumanReviewError("high-fidelity package reports blockers despite high_fidelity_ready=true")
    if list(audit.get("face_secondary_blockers") or []):
        raise HighFidelityHumanReviewError("high-fidelity package reports face-secondary blockers despite ready=true")
    return audit


def review_path(package_path: str | Path, *, package_sha256: str | None = None) -> Path:
    package = Path(package_path).expanduser().resolve()
    sha = str(package_sha256 or "").strip().lower() or _sha256_file(package)
    return package.with_name(f"{package.stem}.{sha}.high-fidelity-human-review.json")


def write_review(
    package_path: str | Path,
    *,
    checklist: Mapping[str, Any],
    quality_note: str,
) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    if not package.is_file():
        raise HighFidelityHumanReviewError(f"body package is missing: {package}")
    audit = _strict_ready_audit(package)
    actual_sha = _sha256_file(package)
    audited_sha = str(audit.get("package_sha256") or "").strip().lower()
    if audited_sha != actual_sha:
        raise HighFidelityHumanReviewError("high-fidelity audit package SHA no longer matches package bytes")
    body_id = str(audit.get("canonical_body_id") or "").strip()
    if not body_id:
        raise HighFidelityHumanReviewError("high-fidelity audit has no canonical body id")

    normalized = dict(checklist)
    if set(normalized) != CHECKLIST_FIELDS:
        raise HighFidelityHumanReviewError("high-fidelity human review checklist fields are not canonical")
    for field in CHECKLIST_FIELDS:
        if normalized.get(field) is not True:
            raise HighFidelityHumanReviewError(f"high-fidelity human review did not explicitly pass {field}")
    note = _quality_note(quality_note)

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "body_id": body_id,
        "package_sha256": actual_sha,
        "component_state_sha256": component_state_sha256(audit),
        "reviewed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "checklist": {field: True for field in sorted(CHECKLIST_FIELDS)},
        "quality_note": note,
        "human_review_complete": True,
        "production_activation": False,
    }
    path = review_path(package, package_sha256=actual_sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise HighFidelityHumanReviewError(f"refusing to overwrite existing high-fidelity human review: {path}") from exc
    return receipt


def read_review(package_path: str | Path) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    if not package.is_file():
        raise HighFidelityHumanReviewError(f"body package is missing: {package}")
    audit = _strict_ready_audit(package)
    actual_sha = _sha256_file(package)
    path = review_path(package, package_sha256=actual_sha)
    if not path.is_file():
        raise HighFidelityHumanReviewError(f"high-fidelity human review is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityHumanReviewError(f"high-fidelity human review is unreadable: {path}") from exc
    if not isinstance(value, dict) or set(value) != TOP_FIELDS:
        raise HighFidelityHumanReviewError("high-fidelity human review fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise HighFidelityHumanReviewError("high-fidelity human review format/version/policy mismatch")
    if str(value.get("body_id") or "") != str(audit.get("canonical_body_id") or ""):
        raise HighFidelityHumanReviewError("high-fidelity human review body id no longer matches package authority")
    if str(value.get("package_sha256") or "").lower() != actual_sha:
        raise HighFidelityHumanReviewError("high-fidelity human review package SHA no longer matches package bytes")
    if str(audit.get("package_sha256") or "").lower() != actual_sha:
        raise HighFidelityHumanReviewError("high-fidelity audit package SHA no longer matches package bytes")
    if str(value.get("component_state_sha256") or "").lower() != component_state_sha256(audit):
        raise HighFidelityHumanReviewError("high-fidelity human review no longer matches current component-state authority")
    checklist = value.get("checklist")
    if not isinstance(checklist, dict) or set(checklist) != CHECKLIST_FIELDS:
        raise HighFidelityHumanReviewError("high-fidelity human review checklist is not canonical")
    for field in CHECKLIST_FIELDS:
        if checklist.get(field) is not True:
            raise HighFidelityHumanReviewError(f"high-fidelity human review did not explicitly pass {field}")
    _quality_note(value.get("quality_note"))
    if value.get("human_review_complete") is not True:
        raise HighFidelityHumanReviewError("high-fidelity human review is not complete")
    if value.get("production_activation") is not False:
        raise HighFidelityHumanReviewError("high-fidelity human review must remain independently non-activating")
    return value


def review_status(package_path: str | Path) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    if not package.is_file():
        return {"state": "unavailable", "passed": False, "reason": f"Body package is missing: {package}"}
    try:
        audit = audit_high_fidelity_package(package)
    except (OSError, HighFidelityPackageAuditError) as exc:
        return {"state": "unavailable", "passed": False, "reason": f"High-fidelity package audit failed: {exc}"}
    actual_sha = _sha256_file(package)
    audited_sha = str(audit.get("package_sha256") or "").strip().lower()
    if audited_sha != actual_sha:
        raise HighFidelityHumanReviewError("high-fidelity audit package SHA no longer matches package bytes")
    if audit.get("high_fidelity_ready") is not True:
        return {
            "state": "blocked",
            "passed": False,
            "reason": "High-fidelity component gates must be complete before human fidelity review.",
        }
    path = review_path(package, package_sha256=actual_sha)
    if not path.is_file():
        return {
            "state": "required",
            "passed": False,
            "reason": "Explicit high-fidelity human review is required for this exact package.",
        }
    receipt = read_review(package)
    return {
        "state": "pass",
        "passed": True,
        "reason": None,
        "reviewed_utc": receipt["reviewed_utc"],
        "quality_note": receipt["quality_note"],
        "policy_revision": receipt["policy_revision"],
    }
