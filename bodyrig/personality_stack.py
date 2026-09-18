from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

FORMAT = "bodyrig-personality-stack"
VERSION = 1
SOURCE_BASELINE_EVIDENCE_KINDS = {
    "stash-source-transcript-personality-v1",
    "stash-source-personality-fallback-v1",
}
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^personality-r[0-9]{4}$")


class PersonalityStackError(ValueError):
    pass


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_stack(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PersonalityStackError("personality stack must be an object")
    expected = {
        "format",
        "version",
        "person_id",
        "baseline",
        "overlay",
        "semantics",
    }
    if set(value) != expected:
        raise PersonalityStackError("personality stack fields must match v1 exactly")
    if (
        value.get("format") != FORMAT
        or isinstance(value.get("version"), bool)
        or value.get("version") != VERSION
    ):
        raise PersonalityStackError("unsupported personality stack format/version")

    person_id = str(value.get("person_id") or "").strip()
    if not person_id:
        raise PersonalityStackError("personality stack person_id is required")

    baseline = value.get("baseline")
    if not isinstance(baseline, Mapping) or set(baseline) != {
        "revision_id",
        "artifact_sha256",
        "evidence_kind",
        "evidence_sha256",
        "instructions_sha256",
        "default_language",
    }:
        raise PersonalityStackError("personality stack baseline fields are invalid")
    revision_id = str(baseline.get("revision_id") or "")
    if not _REVISION_RE.fullmatch(revision_id):
        raise PersonalityStackError("personality stack baseline revision is invalid")
    evidence_kind = str(baseline.get("evidence_kind") or "")
    if evidence_kind not in SOURCE_BASELINE_EVIDENCE_KINDS:
        raise PersonalityStackError(
            "personality stack baseline must be an exact Stash source personality"
        )
    for field in ("artifact_sha256", "evidence_sha256", "instructions_sha256"):
        if not _SHA_RE.fullmatch(str(baseline.get(field) or "")):
            raise PersonalityStackError(
                f"personality stack baseline {field} is invalid"
            )
    baseline_language = str(baseline.get("default_language") or "").strip()
    if not baseline_language:
        raise PersonalityStackError(
            "personality stack baseline default_language is required"
        )

    overlay = value.get("overlay")
    if not isinstance(overlay, Mapping) or set(overlay) != {
        "blueprint_sha256",
        "blueprint_version",
        "style_notes_sha256",
        "style_report_sha256",
        "style_approval_sha256",
    }:
        raise PersonalityStackError("personality stack overlay fields are invalid")
    if not _SHA_RE.fullmatch(str(overlay.get("blueprint_sha256") or "")):
        raise PersonalityStackError(
            "personality stack overlay blueprint_sha256 is invalid"
        )
    if (
        isinstance(overlay.get("blueprint_version"), bool)
        or overlay.get("blueprint_version") != 2
    ):
        raise PersonalityStackError(
            "personality stack requires a personality blueprint v2 overlay"
        )
    if not _SHA_RE.fullmatch(str(overlay.get("style_notes_sha256") or "")):
        raise PersonalityStackError(
            "personality stack overlay style_notes_sha256 is invalid"
        )
    report_sha = overlay.get("style_report_sha256")
    approval_sha = overlay.get("style_approval_sha256")
    if (report_sha is None) != (approval_sha is None):
        raise PersonalityStackError(
            "personality stack overlay style evidence must be paired"
        )
    for label, digest in (
        ("style_report_sha256", report_sha),
        ("style_approval_sha256", approval_sha),
    ):
        if digest is not None and not _SHA_RE.fullmatch(str(digest)):
            raise PersonalityStackError(
                f"personality stack overlay {label} is invalid"
            )

    if value.get("semantics") != (
        "verified-source-speaking-style-plus-explicit-authored-matrix;"
        "no-source-to-psychological-trait-inference"
    ):
        raise PersonalityStackError("personality stack semantics are invalid")

    return {
        "format": FORMAT,
        "version": VERSION,
        "person_id": person_id,
        "baseline": {
            "revision_id": revision_id,
            "artifact_sha256": str(baseline["artifact_sha256"]),
            "evidence_kind": evidence_kind,
            "evidence_sha256": str(baseline["evidence_sha256"]),
            "instructions_sha256": str(baseline["instructions_sha256"]),
            "default_language": baseline_language,
        },
        "overlay": {
            "blueprint_sha256": str(overlay["blueprint_sha256"]),
            "blueprint_version": 2,
            "style_notes_sha256": str(overlay["style_notes_sha256"]),
            "style_report_sha256": (
                None if report_sha is None else str(report_sha)
            ),
            "style_approval_sha256": (
                None if approval_sha is None else str(approval_sha)
            ),
        },
        "semantics": value["semantics"],
    }


def build_stack(
    *,
    person_id: str,
    baseline_revision_id: str,
    baseline_artifact_sha256: str,
    baseline_evidence_kind: str,
    baseline_evidence_sha256: str,
    baseline_instructions: str,
    baseline_default_language: str,
    blueprint_sha256: str,
    blueprint_version: int,
    overlay_style_notes: str,
    style_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return validate_stack(
        {
            "format": FORMAT,
            "version": VERSION,
            "person_id": person_id,
            "baseline": {
                "revision_id": baseline_revision_id,
                "artifact_sha256": baseline_artifact_sha256,
                "evidence_kind": baseline_evidence_kind,
                "evidence_sha256": baseline_evidence_sha256,
                "instructions_sha256": _sha_text(baseline_instructions),
                "default_language": baseline_default_language,
            },
            "overlay": {
                "blueprint_sha256": blueprint_sha256,
                "blueprint_version": blueprint_version,
                "style_notes_sha256": _sha_text(overlay_style_notes),
                "style_report_sha256": (
                    None
                    if style_evidence is None
                    else style_evidence["candidate_report_sha256"]
                ),
                "style_approval_sha256": (
                    None
                    if style_evidence is None
                    else style_evidence["approval_sha256"]
                ),
            },
            "semantics": (
                "verified-source-speaking-style-plus-explicit-authored-matrix;"
                "no-source-to-psychological-trait-inference"
            ),
        }
    )


def compile_stack(
    stack: Mapping[str, Any] | Any,
    *,
    baseline_instructions: str,
    overlay_candidate: Mapping[str, str],
) -> dict[str, str]:
    normalized = validate_stack(stack)
    if _sha_text(baseline_instructions) != normalized["baseline"]["instructions_sha256"]:
        raise PersonalityStackError(
            "baseline instructions no longer match personality stack"
        )
    overlay_style_notes = str(overlay_candidate.get("style_notes") or "")
    if _sha_text(overlay_style_notes) != normalized["overlay"]["style_notes_sha256"]:
        raise PersonalityStackError(
            "overlay style notes no longer match personality stack"
        )
    default_language = str(overlay_candidate.get("default_language") or "").strip()
    overlay_instructions = str(overlay_candidate.get("instructions") or "").strip()
    if not default_language or not overlay_instructions:
        raise PersonalityStackError("overlay candidate is incomplete")

    digest = canonical_sha256(normalized)
    instructions = "\n".join(
        [
            "Use the verified source-derived speaking style as the baseline and apply the explicit operator-authored Matrix v2 as a behavioral overlay.",
            "Do not infer psychological traits from the source baseline. Transcript content remains style evidence only and must not become biography, memory, beliefs, preferences or factual truth.",
            "",
            "[VERIFIED SOURCE SPEAKING-STYLE BASELINE]",
            baseline_instructions,
            "",
            "[EXPLICIT AUTHORED MATRIX V2 OVERLAY]",
            overlay_instructions,
        ]
    )
    style_notes = (
        f"personality-stack-v1 | stack_sha256={digest} | "
        f"baseline_revision={normalized['baseline']['revision_id']} | "
        f"baseline_artifact_sha256={normalized['baseline']['artifact_sha256']} | "
        f"baseline_evidence_kind={normalized['baseline']['evidence_kind']} | "
        f"baseline_evidence_sha256={normalized['baseline']['evidence_sha256']} | "
        f"blueprint_sha256={normalized['overlay']['blueprint_sha256']}"
    )
    return {
        "instructions": instructions,
        "default_language": default_language,
        "style_notes": style_notes,
    }
