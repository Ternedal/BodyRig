from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping

from .hands_feet_nails_authority import CHECKLIST_FIELDS, HandsFeetNailsAuthorityError, validate_render_manifest
from .hands_feet_nails_detail_candidate import (
    HandsFeetNailsDetailCandidateError,
    read_detail_candidate,
)
from .hands_feet_nails_source_capture import (
    HandsFeetNailsSourceCaptureError,
    capture_dir,
    read_source_capture,
)

FORMAT = "bodyrig-high-fidelity-hfn-human-review"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-hfn-human-review-v1"
REVIEW_FILE = "hands-feet-nails-human-review.json"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
REVIEW_RE = re.compile(r"^hfnhuman-[0-9a-f]{32}$")
TOP_FIELDS = {
    "format", "version", "policy_revision", "review_id", "person_id", "body_revision",
    "capture_id", "body_id", "candidate_id", "bodyrig_revision", "candidate_receipt_sha256",
    "candidate_package_sha256", "source_capture_sha256", "render_manifest_sha256",
    "render_region_sha256", "checklist", "quality_note", "state", "source_grounded",
    "operator_supplied", "package_application_authority", "human_review_completed",
    "production_activation",
}


class HighFidelityHfnReviewError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise HighFidelityHfnReviewError(f"required HFN review evidence is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise HighFidelityHfnReviewError(f"{label} is not a canonical SHA-256")
    return text


def _revision(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(text):
        raise HighFidelityHfnReviewError("HFN human-review BodyRig revision is not canonical")
    return text


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _review_id(
    *,
    candidate_package_sha256: str,
    source_capture_sha256: str,
    render_manifest_sha256: str,
    bodyrig_revision: str,
) -> str:
    payload = {
        "candidate_package_sha256": candidate_package_sha256,
        "source_capture_sha256": source_capture_sha256,
        "render_manifest_sha256": render_manifest_sha256,
        "bodyrig_revision": bodyrig_revision,
    }
    return "hfnhuman-" + hashlib.sha256(_canonical_json(payload)).hexdigest()[:32]


def _review_path(output_dir: str | os.PathLike[str]) -> Path:
    return Path(output_dir).expanduser().resolve() / REVIEW_FILE


def _quality_note(value: Any) -> str:
    note = str(value or "").strip()
    if not note or len(note) > 2000 or (note.startswith("<") and note.endswith(">")):
        raise HighFidelityHfnReviewError("HFN human review requires a real bounded quality note")
    return note


def _checklist(value: Any) -> dict[str, bool]:
    if not isinstance(value, Mapping) or set(value) != CHECKLIST_FIELDS:
        raise HighFidelityHfnReviewError("HFN human-review checklist fields are not canonical")
    normalized = {name: value.get(name) is True for name in sorted(CHECKLIST_FIELDS)}
    if not all(normalized.values()):
        raise HighFidelityHfnReviewError("HFN human review requires every canonical M2 checklist item to pass")
    return normalized


def _candidate_and_render(
    *,
    root: Path,
    person_id: str,
    body_revision: str,
    capture_id: str,
    candidate_id: str,
    render_manifest_path: Path,
    bodyrig_revision: str,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    try:
        candidate = read_detail_candidate(
            root,
            person_id,
            body_revision=body_revision,
            capture_id=capture_id,
            candidate_id=candidate_id,
        )
    except HandsFeetNailsDetailCandidateError as exc:
        raise HighFidelityHfnReviewError(str(exc)) from exc
    revision = _revision(bodyrig_revision)
    if candidate["bodyrig_revision"] != revision:
        raise HighFidelityHfnReviewError("HFN candidate was produced by a different BodyRig revision")
    receipt_path = Path(candidate["receipt_path"]).resolve()
    candidate_receipt_sha = _sha256(receipt_path)
    try:
        render = validate_render_manifest(
            render_manifest_path,
            body_id=candidate["body_id"],
            package_sha256=candidate["candidate_package_sha256"],
        )
    except HandsFeetNailsAuthorityError as exc:
        raise HighFidelityHfnReviewError(str(exc)) from exc
    return candidate, candidate_receipt_sha, render


def write_review(
    output_dir: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    person_id: str,
    body_revision: str,
    capture_id: str,
    candidate_id: str,
    render_manifest_path: str | os.PathLike[str],
    bodyrig_revision: str,
    quality_note: str,
    confirm_detail_checklist: bool,
) -> dict[str, Any]:
    if confirm_detail_checklist is not True:
        raise HighFidelityHfnReviewError("HFN human review requires explicit M2 detail-checklist confirmation")
    root_path = Path(root).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise HighFidelityHfnReviewError("refusing to overwrite existing HFN human-review authority")
    render_path = Path(render_manifest_path).expanduser().resolve()
    candidate, candidate_receipt_sha, render = _candidate_and_render(
        root=root_path,
        person_id=person_id,
        body_revision=body_revision,
        capture_id=capture_id,
        candidate_id=candidate_id,
        render_manifest_path=render_path,
        bodyrig_revision=bodyrig_revision,
    )
    try:
        source = read_source_capture(
            root_path,
            candidate["person_id"],
            body_revision=candidate["body_revision"],
            capture_id=candidate["capture_id"],
        )
    except HandsFeetNailsSourceCaptureError as exc:
        raise HighFidelityHfnReviewError(str(exc)) from exc
    source_manifest = capture_dir(
        root_path,
        candidate["person_id"],
        candidate["body_revision"],
        candidate["capture_id"],
    ) / "source-capture.json"
    source_sha = _sha256(source_manifest)
    if source_sha != candidate["source_capture_sha256"]:
        raise HighFidelityHfnReviewError("HFN candidate no longer matches exact source-capture manifest")
    for region, item in source["regions"].items():
        if candidate["regions"][region]["source_image_sha256"] != item["image_sha256"]:
            raise HighFidelityHfnReviewError(f"{region} candidate no longer matches exact source closeup bytes")

    revision = _revision(bodyrig_revision)
    checklist = {name: True for name in sorted(CHECKLIST_FIELDS)}
    note = _quality_note(quality_note)
    review_id = _review_id(
        candidate_package_sha256=candidate["candidate_package_sha256"],
        source_capture_sha256=source_sha,
        render_manifest_sha256=render["manifest_sha256"],
        bodyrig_revision=revision,
    )
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "review_id": review_id,
        "person_id": candidate["person_id"],
        "body_revision": candidate["body_revision"],
        "capture_id": candidate["capture_id"],
        "body_id": candidate["body_id"],
        "candidate_id": candidate["candidate_id"],
        "bodyrig_revision": revision,
        "candidate_receipt_sha256": candidate_receipt_sha,
        "candidate_package_sha256": candidate["candidate_package_sha256"],
        "source_capture_sha256": source_sha,
        "render_manifest_sha256": render["manifest_sha256"],
        "render_region_sha256": dict(render["region_sha256"]),
        "checklist": checklist,
        "quality_note": note,
        "state": "pass",
        "source_grounded": True,
        "operator_supplied": True,
        "package_application_authority": False,
        "human_review_completed": True,
        "production_activation": False,
    }
    validated = validate_review_structure(receipt)
    stage = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    stage.mkdir(parents=True, exist_ok=False)
    try:
        path = stage / REVIEW_FILE
        path.write_text(
            json.dumps(validated, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(stage, output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {**validated, "review_path": str(output / REVIEW_FILE)}


def validate_review_structure(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise HighFidelityHfnReviewError("HFN human-review fields are not canonical")
    if (
        value.get("format"), value.get("version"), value.get("policy_revision"), value.get("state")
    ) != (FORMAT, VERSION, POLICY_REVISION, "pass"):
        raise HighFidelityHfnReviewError("HFN human-review format/version/policy/state mismatch")
    review_id = str(value.get("review_id") or "").lower()
    if not REVIEW_RE.fullmatch(review_id):
        raise HighFidelityHfnReviewError("HFN human-review id is not canonical")
    revision = _revision(value.get("bodyrig_revision"))
    for field in (
        "candidate_receipt_sha256", "candidate_package_sha256", "source_capture_sha256",
        "render_manifest_sha256",
    ):
        _sha(value.get(field), label=field.replace("_", " "))
    hashes = value.get("render_region_sha256")
    if not isinstance(hashes, Mapping) or set(hashes) != {"left_hand", "right_hand", "left_foot", "right_foot"}:
        raise HighFidelityHfnReviewError("HFN human-review render-region hashes are not canonical")
    normalized_hashes = {name: _sha(hashes[name], label=f"{name} render SHA-256") for name in hashes}
    checklist = _checklist(value.get("checklist"))
    note = _quality_note(value.get("quality_note"))
    if (
        value.get("source_grounded") is not True
        or value.get("operator_supplied") is not True
        or value.get("package_application_authority") is not False
        or value.get("human_review_completed") is not True
        or value.get("production_activation") is not False
    ):
        raise HighFidelityHfnReviewError("HFN human review crossed its review-only authority boundary")
    return {
        **dict(value),
        "review_id": review_id,
        "bodyrig_revision": revision,
        "render_region_sha256": normalized_hashes,
        "checklist": checklist,
        "quality_note": note,
    }


def read_review(
    output_dir: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    person_id: str,
    body_revision: str,
    capture_id: str,
    candidate_id: str,
    render_manifest_path: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    path = _review_path(output_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityHfnReviewError("HFN human-review receipt is missing or unreadable") from exc
    receipt = validate_review_structure(raw)
    candidate, candidate_receipt_sha, render = _candidate_and_render(
        root=Path(root).expanduser().resolve(),
        person_id=person_id,
        body_revision=body_revision,
        capture_id=capture_id,
        candidate_id=candidate_id,
        render_manifest_path=Path(render_manifest_path).expanduser().resolve(),
        bodyrig_revision=bodyrig_revision,
    )
    source_manifest = capture_dir(
        Path(root).expanduser().resolve(),
        candidate["person_id"],
        candidate["body_revision"],
        candidate["capture_id"],
    ) / "source-capture.json"
    source_sha = _sha256(source_manifest)
    expected = {
        "person_id": candidate["person_id"],
        "body_revision": candidate["body_revision"],
        "capture_id": candidate["capture_id"],
        "body_id": candidate["body_id"],
        "candidate_id": candidate["candidate_id"],
        "bodyrig_revision": _revision(bodyrig_revision),
        "candidate_receipt_sha256": candidate_receipt_sha,
        "candidate_package_sha256": candidate["candidate_package_sha256"],
        "source_capture_sha256": source_sha,
        "render_manifest_sha256": render["manifest_sha256"],
        "render_region_sha256": dict(render["region_sha256"]),
    }
    for field, expected_value in expected.items():
        if receipt.get(field) != expected_value:
            raise HighFidelityHfnReviewError(f"HFN human review no longer matches exact authority: {field}")
    expected_review_id = _review_id(
        candidate_package_sha256=candidate["candidate_package_sha256"],
        source_capture_sha256=source_sha,
        render_manifest_sha256=render["manifest_sha256"],
        bodyrig_revision=_revision(bodyrig_revision),
    )
    if receipt["review_id"] != expected_review_id:
        raise HighFidelityHfnReviewError("HFN human-review id no longer matches exact evidence")
    return {**receipt, "review_path": str(path)}
