from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

CANDIDATE_FORMAT = "bodyrig-personality-exemplar-candidates"
CANDIDATE_VERSION = 1
APPROVAL_FORMAT = "bodyrig-personality-exemplar-approval"
APPROVAL_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_EXEMPLARS = 12

CANDIDATE_FIELDS = {
    "format",
    "version",
    "source_count",
    "source_sha256",
    "candidate_count",
    "candidates",
    "suggested_exemplars",
    "operator_review_required",
    "speaker_identity_authority",
    "personality_authority",
    "content_semantics",
}
APPROVAL_FIELDS = {
    "format",
    "version",
    "candidate_report_sha256",
    "selected_candidate_indexes",
    "approved_exemplars",
    "operator_review",
    "personality_authority",
    "content_semantics",
}
REVIEW_FIELDS = {"speaker_identity_confirmed", "style_use_approved"}


class PersonalityExemplarApprovalError(ValueError):
    pass


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PersonalityExemplarApprovalError("exemplar evidence is not canonicalizable") from exc


def canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _utterance(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise PersonalityExemplarApprovalError(f"{field} must be text")
    text = value.strip()
    if not 3 <= len(text) <= 1000:
        raise PersonalityExemplarApprovalError(f"{field} must contain 3..1000 characters")
    return text


def validate_candidate_report(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != CANDIDATE_FIELDS:
        raise PersonalityExemplarApprovalError("candidate report fields must match v1 exactly")
    if value.get("format") != CANDIDATE_FORMAT or value.get("version") != CANDIDATE_VERSION:
        raise PersonalityExemplarApprovalError("unsupported candidate report format/version")

    source_count = value.get("source_count")
    if isinstance(source_count, bool) or not isinstance(source_count, int) or not 1 <= source_count <= 20:
        raise PersonalityExemplarApprovalError("candidate report source_count must be 1..20")
    source_hashes = value.get("source_sha256")
    if not isinstance(source_hashes, list) or len(source_hashes) != source_count or len(set(source_hashes)) != len(source_hashes):
        raise PersonalityExemplarApprovalError("candidate report source_sha256 must be a distinct hash per source")
    if any(not isinstance(item, str) or SHA256_RE.fullmatch(item) is None for item in source_hashes):
        raise PersonalityExemplarApprovalError("candidate report source_sha256 contains an invalid hash")

    candidates = value.get("candidates")
    candidate_count = value.get("candidate_count")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 200:
        raise PersonalityExemplarApprovalError("candidate report candidates must contain 1..200 items")
    clean_candidates = [_utterance(item, field="candidate") for item in candidates]
    if len({item.casefold() for item in clean_candidates}) != len(clean_candidates):
        raise PersonalityExemplarApprovalError("candidate report candidates must be unique")
    if isinstance(candidate_count, bool) or not isinstance(candidate_count, int) or candidate_count != len(clean_candidates):
        raise PersonalityExemplarApprovalError("candidate_count does not match candidates")

    suggested = value.get("suggested_exemplars")
    if not isinstance(suggested, list) or not 1 <= len(suggested) <= MAX_EXEMPLARS:
        raise PersonalityExemplarApprovalError("suggested_exemplars must contain 1..12 items")
    clean_suggested = [_utterance(item, field="suggested exemplar") for item in suggested]
    candidate_keys = {item.casefold() for item in clean_candidates}
    if len({item.casefold() for item in clean_suggested}) != len(clean_suggested):
        raise PersonalityExemplarApprovalError("suggested_exemplars must be unique")
    if any(item.casefold() not in candidate_keys for item in clean_suggested):
        raise PersonalityExemplarApprovalError("suggested_exemplars must come from candidates")

    if value.get("operator_review_required") is not True:
        raise PersonalityExemplarApprovalError("candidate report must require operator review")
    if value.get("speaker_identity_authority") is not False:
        raise PersonalityExemplarApprovalError("candidate report must not claim speaker identity authority")
    if value.get("personality_authority") is not False:
        raise PersonalityExemplarApprovalError("candidate report must not claim personality authority")
    if value.get("content_semantics") != "style-only-not-biography-or-memory":
        raise PersonalityExemplarApprovalError("candidate report content semantics are invalid")

    return {
        "format": CANDIDATE_FORMAT,
        "version": CANDIDATE_VERSION,
        "source_count": source_count,
        "source_sha256": list(source_hashes),
        "candidate_count": candidate_count,
        "candidates": clean_candidates,
        "suggested_exemplars": clean_suggested,
        "operator_review_required": True,
        "speaker_identity_authority": False,
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def build_approval(
    report: Mapping[str, Any] | Any,
    *,
    selected_candidate_indexes: Sequence[int],
    speaker_identity_confirmed: bool,
    style_use_approved: bool,
) -> dict[str, Any]:
    validated = validate_candidate_report(report)
    if speaker_identity_confirmed is not True:
        raise PersonalityExemplarApprovalError("speaker identity must be explicitly confirmed")
    if style_use_approved is not True:
        raise PersonalityExemplarApprovalError("style use must be explicitly approved")
    indexes = list(selected_candidate_indexes)
    if not 1 <= len(indexes) <= MAX_EXEMPLARS:
        raise PersonalityExemplarApprovalError("select 1..12 candidate indexes")
    if any(isinstance(index, bool) or not isinstance(index, int) for index in indexes):
        raise PersonalityExemplarApprovalError("selected candidate indexes must be integers")
    if len(set(indexes)) != len(indexes):
        raise PersonalityExemplarApprovalError("selected candidate indexes must be unique")
    if any(index < 0 or index >= validated["candidate_count"] for index in indexes):
        raise PersonalityExemplarApprovalError("selected candidate index is out of range")

    return {
        "format": APPROVAL_FORMAT,
        "version": APPROVAL_VERSION,
        "candidate_report_sha256": canonical_sha256(validated),
        "selected_candidate_indexes": indexes,
        "approved_exemplars": [validated["candidates"][index] for index in indexes],
        "operator_review": {
            "speaker_identity_confirmed": True,
            "style_use_approved": True,
        },
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def validate_approval(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != APPROVAL_FIELDS:
        raise PersonalityExemplarApprovalError("approval fields must match v1 exactly")
    if value.get("format") != APPROVAL_FORMAT or value.get("version") != APPROVAL_VERSION:
        raise PersonalityExemplarApprovalError("unsupported approval format/version")
    report_sha = value.get("candidate_report_sha256")
    if not isinstance(report_sha, str) or SHA256_RE.fullmatch(report_sha) is None:
        raise PersonalityExemplarApprovalError("candidate_report_sha256 is invalid")

    indexes = value.get("selected_candidate_indexes")
    exemplars = value.get("approved_exemplars")
    if not isinstance(indexes, list) or not isinstance(exemplars, list) or len(indexes) != len(exemplars) or not 1 <= len(indexes) <= MAX_EXEMPLARS:
        raise PersonalityExemplarApprovalError("approval selection must contain matching 1..12 indexes and exemplars")
    if any(isinstance(index, bool) or not isinstance(index, int) or index < 0 for index in indexes):
        raise PersonalityExemplarApprovalError("approval indexes are invalid")
    if len(set(indexes)) != len(indexes):
        raise PersonalityExemplarApprovalError("approval indexes must be unique")
    clean_exemplars = [_utterance(item, field="approved exemplar") for item in exemplars]
    if len({item.casefold() for item in clean_exemplars}) != len(clean_exemplars):
        raise PersonalityExemplarApprovalError("approved exemplars must be unique")

    review = value.get("operator_review")
    if not isinstance(review, Mapping) or set(review) != REVIEW_FIELDS:
        raise PersonalityExemplarApprovalError("operator_review fields must match v1 exactly")
    if review.get("speaker_identity_confirmed") is not True or review.get("style_use_approved") is not True:
        raise PersonalityExemplarApprovalError("approval requires explicit speaker and style confirmation")
    if value.get("personality_authority") is not False:
        raise PersonalityExemplarApprovalError("approval must not claim personality authority")
    if value.get("content_semantics") != "style-only-not-biography-or-memory":
        raise PersonalityExemplarApprovalError("approval content semantics are invalid")

    return {
        "format": APPROVAL_FORMAT,
        "version": APPROVAL_VERSION,
        "candidate_report_sha256": report_sha,
        "selected_candidate_indexes": list(indexes),
        "approved_exemplars": clean_exemplars,
        "operator_review": {
            "speaker_identity_confirmed": True,
            "style_use_approved": True,
        },
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def verify_approval(
    report: Mapping[str, Any] | Any,
    approval: Mapping[str, Any] | Any,
) -> dict[str, Any]:
    validated_report = validate_candidate_report(report)
    validated_approval = validate_approval(approval)
    actual_report_sha = canonical_sha256(validated_report)
    if validated_approval["candidate_report_sha256"] != actual_report_sha:
        raise PersonalityExemplarApprovalError(
            "approval receipt does not match the exact candidate report"
        )
    indexes = validated_approval["selected_candidate_indexes"]
    if any(index >= validated_report["candidate_count"] for index in indexes):
        raise PersonalityExemplarApprovalError(
            "approval references a candidate index outside the bound report"
        )
    expected = [validated_report["candidates"][index] for index in indexes]
    if validated_approval["approved_exemplars"] != expected:
        raise PersonalityExemplarApprovalError(
            "approved exemplars no longer match their bound candidate indexes"
        )
    return validated_approval


def _strict_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonalityExemplarApprovalError(f"invalid JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise PersonalityExemplarApprovalError("evidence must be a JSON object")
    return value


def load_candidate_report(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise PersonalityExemplarApprovalError(f"candidate report not found: {resolved}")
    return validate_candidate_report(_strict_json(resolved))


def load_approval(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise PersonalityExemplarApprovalError(f"approval receipt not found: {resolved}")
    return validate_approval(_strict_json(resolved))


def load_verified_approval(report_path: str | Path, approval_path: str | Path) -> dict[str, Any]:
    return verify_approval(load_candidate_report(report_path), load_approval(approval_path))


def write_create_only(path: str | Path, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, target)
        except FileExistsError as exc:
            raise PersonalityExemplarApprovalError(f"approval output already exists: {target}") from exc
        except OSError as exc:
            raise PersonalityExemplarApprovalError("could not commit approval output create-only") from exc
    finally:
        temp.unlink(missing_ok=True)
    return target
