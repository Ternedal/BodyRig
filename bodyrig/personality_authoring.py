from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from .package import MRBodyError, validate_package
from .person_profiles import PersonProfileError, add_personality_revision, load_profile
from .person_source_alignment import PersonSourceAlignmentError, write_binding as write_source_binding
from .personality_audition_suite import build_audition_suite
from .personality_blueprint import (
    PersonalityBlueprintError,
    blueprint_sha256,
    build_blueprint,
    compile_blueprint,
    validate_blueprint,
)
from .personality_traits import (
    PersonalityTraitProfileError,
    compile_trait_profile,
    trait_profile_sha256,
    validate_trait_profile,
)
from .personality_source import (
    SourcePersonalityError,
    preview_source_personality_exemplars,
)
from .personality_exemplar_approval import (
    PersonalityExemplarApprovalError,
    canonical_sha256 as exemplar_evidence_sha256,
    validate_approval,
    validate_candidate_report,
    verify_approval,
)


class PersonalityAuthoringError(ValueError):
    pass


TRAIT_PROFILE_SHA_RE = re.compile(
    r"(?:^| \| )trait_profile_sha256=([0-9a-f]{64})(?: \||$)"
)


def _find_body_revision(profile: Mapping[str, Any], revision_id: str) -> dict[str, Any]:
    for item in profile.get("body_revisions", []):
        if item.get("revision_id") == revision_id:
            return dict(item)
    raise PersonalityAuthoringError(f"body revision {revision_id!r} is not registered on this person")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise PersonalityAuthoringError("registered body package could not be hashed") from exc
    return digest.hexdigest()


def _validated_bodyprint(profile: Mapping[str, Any], revision_id: str) -> dict[str, Any]:
    item = _find_body_revision(profile, revision_id)
    package = Path(str(item["package_path"])).expanduser().resolve()
    if not package.is_file():
        raise PersonalityAuthoringError("registered body package is missing")
    if _sha256_file(package) != item["package_sha256"]:
        raise PersonalityAuthoringError("registered body package bytes no longer match the body revision")
    try:
        validated = validate_package(package)
    except (MRBodyError, OSError) as exc:
        raise PersonalityAuthoringError(f"registered body package is invalid: {exc}") from exc
    if validated.manifest["id"] != item["body_id"]:
        raise PersonalityAuthoringError("registered body identity no longer matches its .mrbody package")
    return dict(validated.bodyprint)


def _resolve_style_evidence(
    report: Mapping[str, Any] | None,
    approval: Mapping[str, Any] | None,
) -> tuple[list[str], dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    if (report is None) != (approval is None):
        raise PersonalityAuthoringError("style candidate report and approval receipt must be supplied together")
    if report is None or approval is None:
        return [], None, None, None
    try:
        normalized_report = validate_candidate_report(report)
        normalized_approval = validate_approval(approval)
        verified = verify_approval(normalized_report, normalized_approval)
    except PersonalityExemplarApprovalError as exc:
        raise PersonalityAuthoringError(f"style approval evidence is invalid: {exc}") from exc
    report_sha = exemplar_evidence_sha256(normalized_report)
    approval_sha = exemplar_evidence_sha256(verified)
    return (
        list(verified["approved_exemplars"]),
        {
            "candidate_report_sha256": report_sha,
            "approval_sha256": approval_sha,
            "approved_count": len(verified["approved_exemplars"]),
        },
        normalized_report,
        verified,
    )


def _build_guided(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    default_language: str,
    communication: Mapping[str, Any],
    authored_notes: str,
    style_exemplars: Sequence[str] | None,
    body_revision: str | None,
    style_report: Mapping[str, Any] | None,
    style_approval: Mapping[str, Any] | None,
    style_source: Mapping[str, Any] | None,
    trait_profile: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    try:
        profile = load_profile(root, person_id)
    except PersonProfileError as exc:
        raise PersonalityAuthoringError(str(exc)) from exc

    approved, style_evidence, normalized_report, normalized_approval = _resolve_style_evidence(
        style_report, style_approval
    )
    if style_source is not None:
        if style_evidence is None or normalized_report is None:
            raise PersonalityAuthoringError(
                "style source binding requires verified report and approval evidence"
            )
        if not isinstance(style_source, Mapping) or set(style_source) != {
            "kind",
            "body_revision",
            "source_manifest_sha256",
        }:
            raise PersonalityAuthoringError(
                "style source binding fields are invalid"
            )
        if style_source.get("kind") != "stash-source-transcript":
            raise PersonalityAuthoringError(
                "style source binding kind is invalid"
            )
        source_body_revision = str(
            style_source.get("body_revision") or ""
        )
        if not body_revision or source_body_revision != body_revision:
            raise PersonalityAuthoringError(
                "Stash transcript style evidence is bound to a different body revision"
            )
        source_manifest_sha = str(
            style_source.get("source_manifest_sha256") or ""
        )
        if (
            len(source_manifest_sha) != 64
            or any(ch not in "0123456789abcdef" for ch in source_manifest_sha)
        ):
            raise PersonalityAuthoringError(
                "style source manifest SHA-256 is invalid"
            )
        try:
            current_source = preview_source_personality_exemplars(
                root,
                person_id,
                body_revision=body_revision,
            )
        except SourcePersonalityError as exc:
            raise PersonalityAuthoringError(
                f"Stash transcript source binding is invalid: {exc}"
            ) from exc
        current_report = current_source.get("candidate_report")
        if not isinstance(current_report, Mapping):
            raise PersonalityAuthoringError(
                "bound Stash source no longer has transcript candidates"
            )
        if current_source.get("source_manifest_sha256") != source_manifest_sha:
            raise PersonalityAuthoringError(
                "Stash transcript source manifest changed"
            )
        if (
            exemplar_evidence_sha256(normalized_report)
            != exemplar_evidence_sha256(current_report)
        ):
            raise PersonalityAuthoringError(
                "Stash transcript candidate report changed"
            )
        style_evidence = {
            **style_evidence,
            "source_kind": "stash-source-transcript",
            "source_body_revision": body_revision,
            "source_manifest_sha256": source_manifest_sha,
        }

    combined_examples = [*list(style_exemplars or []), *approved]
    if len(combined_examples) > 12:
        raise PersonalityAuthoringError("combined direct and transcript-approved style exemplars exceed the 12-example limit")

    bodyprint = None
    if body_revision:
        bodyprint = _validated_bodyprint(profile, body_revision)
    try:
        blueprint = build_blueprint(
            default_language=default_language,
            communication=communication,
            authored_notes=authored_notes,
            style_exemplars=combined_examples,
            bodyprint=bodyprint,
            body_revision=body_revision,
        )
        candidate = compile_blueprint(blueprint)
    except PersonalityBlueprintError as exc:
        raise PersonalityAuthoringError(str(exc)) from exc

    normalized_traits = None
    trait_compilation = None
    if trait_profile is not None:
        try:
            normalized_traits = validate_trait_profile(trait_profile)
            trait_compilation = compile_trait_profile(normalized_traits)
        except PersonalityTraitProfileError as exc:
            raise PersonalityAuthoringError(str(exc)) from exc
        candidate["instructions"] += (
            "\n\n" + trait_compilation["instructions"]
        )
        candidate["style_notes"] += (
            " | " + trait_compilation["style_notes"]
        )

    if style_evidence is not None:
        candidate["style_notes"] += (
            f" | style_report_sha256={style_evidence['candidate_report_sha256']}"
            f" | style_approval_sha256={style_evidence['approval_sha256']}"
        )
        if style_evidence.get("source_kind") == "stash-source-transcript":
            candidate["style_notes"] += (
                f" | style_source=stash-source-transcript"
                f" | style_source_body_revision={style_evidence['source_body_revision']}"
                f" | style_source_manifest_sha256={style_evidence['source_manifest_sha256']}"
            )
    result = {
        "blueprint": blueprint,
        "blueprint_sha256": blueprint_sha256(blueprint),
        "candidate": candidate,
        "audition_suite": build_audition_suite(candidate["default_language"]),
        "style_evidence": style_evidence,
        "trait_profile": normalized_traits,
        "trait_profile_sha256": (
            trait_compilation["trait_profile_sha256"]
            if trait_compilation is not None
            else None
        ),
        "trait_summary": (
            {
                "active_trait_count":
                    trait_compilation["active_trait_count"],
                "salient_inner":
                    trait_compilation["salient_inner"],
                "salient_outer":
                    trait_compilation["salient_outer"],
            }
            if trait_compilation is not None
            else None
        ),
    }
    return result, normalized_report, normalized_approval


def build_guided_personality(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    default_language: str,
    communication: Mapping[str, Any],
    authored_notes: str = "",
    style_exemplars: Sequence[str] | None = None,
    body_revision: str | None = None,
    style_report: Mapping[str, Any] | None = None,
    style_approval: Mapping[str, Any] | None = None,
    style_source: Mapping[str, Any] | None = None,
    trait_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result, _report, _approval = _build_guided(
        root,
        person_id,
        default_language=default_language,
        communication=communication,
        authored_notes=authored_notes,
        style_exemplars=style_exemplars,
        body_revision=body_revision,
        style_report=style_report,
        style_approval=style_approval,
        style_source=style_source,
        trait_profile=trait_profile,
    )
    return result


def _persist_json(path: Path, value: Mapping[str, Any], *, label: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PersonalityAuthoringError(f"existing {label} evidence is unreadable") from exc
        if existing != encoded:
            raise PersonalityAuthoringError(f"{label} digest path contains different bytes")
        return path

    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path)
        except FileExistsError:
            existing = path.read_text(encoding="utf-8")
            if existing != encoded:
                raise PersonalityAuthoringError(f"{label} evidence raced with different bytes")
        except OSError as exc:
            raise PersonalityAuthoringError(f"could not commit {label} evidence create-only") from exc
    finally:
        temp.unlink(missing_ok=True)
    return path


def persist_blueprint_evidence(
    root: str | os.PathLike[str],
    person_id: str,
    blueprint: Mapping[str, Any],
) -> Path:
    root_path = Path(root).expanduser().resolve()
    try:
        load_profile(root_path, person_id)
        normalized = validate_blueprint(blueprint)
    except (PersonProfileError, PersonalityBlueprintError) as exc:
        raise PersonalityAuthoringError(str(exc)) from exc
    digest = blueprint_sha256(normalized)
    path = root_path / "personality-blueprints" / person_id / f"{digest}.json"
    return _persist_json(path, normalized, label="personality blueprint")


def load_personality_trait_profile(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    revision_id: str,
) -> dict[str, Any] | None:
    root_path = Path(root).expanduser().resolve()
    try:
        profile = load_profile(root_path, person_id)
    except PersonProfileError as exc:
        raise PersonalityAuthoringError(str(exc)) from exc

    revision = next(
        (
            item
            for item in profile.get("personality_revisions", [])
            if item.get("revision_id") == revision_id
        ),
        None,
    )
    if revision is None:
        raise PersonalityAuthoringError(
            f"personality revision {revision_id!r} is not registered on this person"
        )

    style_notes = str(revision.get("style_notes") or "")
    match = TRAIT_PROFILE_SHA_RE.search(style_notes)
    if match is None:
        return None
    digest = match.group(1)
    path = (
        root_path
        / "personality-traits"
        / person_id
        / f"{digest}.json"
    )
    if not path.is_file():
        raise PersonalityAuthoringError(
            "bound personality trait evidence is missing"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        normalized = validate_trait_profile(value)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        PersonalityTraitProfileError,
    ) as exc:
        raise PersonalityAuthoringError(
            f"bound personality trait evidence is invalid: {exc}"
        ) from exc
    if trait_profile_sha256(normalized) != digest:
        raise PersonalityAuthoringError(
            "bound personality trait evidence SHA-256 mismatch"
        )
    return {
        "revision_id": revision_id,
        "trait_profile_sha256": digest,
        "trait_profile": normalized,
    }


def persist_trait_profile_evidence(
    root: str | os.PathLike[str],
    person_id: str,
    trait_profile: Mapping[str, Any],
) -> Path:
    root_path = Path(root).expanduser().resolve()
    try:
        load_profile(root_path, person_id)
        normalized = validate_trait_profile(trait_profile)
    except (
        PersonProfileError,
        PersonalityTraitProfileError,
    ) as exc:
        raise PersonalityAuthoringError(str(exc)) from exc
    digest = trait_profile_sha256(normalized)
    path = (
        root_path
        / "personality-traits"
        / person_id
        / f"{digest}.json"
    )
    return _persist_json(
        path,
        normalized,
        label="personality trait profile",
    )


def persist_style_evidence(
    root: str | os.PathLike[str],
    person_id: str,
    report: Mapping[str, Any],
    approval: Mapping[str, Any],
) -> dict[str, Path]:
    root_path = Path(root).expanduser().resolve()
    try:
        load_profile(root_path, person_id)
        normalized_report = validate_candidate_report(report)
        verified_approval = verify_approval(normalized_report, approval)
    except (PersonProfileError, PersonalityExemplarApprovalError) as exc:
        raise PersonalityAuthoringError(str(exc)) from exc
    report_sha = exemplar_evidence_sha256(normalized_report)
    approval_sha = exemplar_evidence_sha256(verified_approval)
    base = root_path / "personality-style-evidence" / person_id
    return {
        "report": _persist_json(base / "reports" / f"{report_sha}.json", normalized_report, label="style report"),
        "approval": _persist_json(base / "approvals" / f"{approval_sha}.json", verified_approval, label="style approval"),
    }


def save_guided_personality(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    default_language: str,
    communication: Mapping[str, Any],
    authored_notes: str = "",
    style_exemplars: Sequence[str] | None = None,
    body_revision: str | None = None,
    style_report: Mapping[str, Any] | None = None,
    style_approval: Mapping[str, Any] | None = None,
    style_source: Mapping[str, Any] | None = None,
    trait_profile: Mapping[str, Any] | None = None,
    feedback: str = "",
) -> dict[str, Any]:
    result, normalized_report, normalized_approval = _build_guided(
        root,
        person_id,
        default_language=default_language,
        communication=communication,
        authored_notes=authored_notes,
        style_exemplars=style_exemplars,
        body_revision=body_revision,
        style_report=style_report,
        style_approval=style_approval,
        style_source=style_source,
        trait_profile=trait_profile,
    )
    style_paths = None
    if normalized_report is not None and normalized_approval is not None:
        style_paths = persist_style_evidence(root, person_id, normalized_report, normalized_approval)
    trait_path = None
    if result["trait_profile"] is not None:
        trait_path = persist_trait_profile_evidence(
            root,
            person_id,
            result["trait_profile"],
        )
    blueprint_path = persist_blueprint_evidence(root, person_id, result["blueprint"])
    candidate = result["candidate"]
    try:
        profile = add_personality_revision(
            root,
            person_id,
            instructions=candidate["instructions"],
            default_language=candidate["default_language"],
            style_notes=candidate["style_notes"],
            feedback=feedback,
        )
    except PersonProfileError as exc:
        raise PersonalityAuthoringError(str(exc)) from exc

    saved_revision = profile["personality_revisions"][-1]["revision_id"]
    source_binding = None
    if body_revision is not None and profile.get("source") is not None:
        try:
            source_binding = write_source_binding(
                root,
                profile,
                kind="personality",
                revision_id=saved_revision,
                evidence_kind="personality-blueprint-v1",
                evidence_sha256=result["blueprint_sha256"],
                evidence_ref=str(blueprint_path),
            )
        except PersonSourceAlignmentError as exc:
            raise PersonalityAuthoringError(f"could not bind guided personality to source: {exc}") from exc

    return {
        **result,
        "evidence_path": str(blueprint_path),
        "trait_evidence_path": (
            str(trait_path) if trait_path is not None else None
        ),
        "style_evidence_paths": {key: str(path) for key, path in style_paths.items()} if style_paths else None,
        "source_binding": source_binding,
        "profile": profile,
        "saved_personality_revision": saved_revision,
    }