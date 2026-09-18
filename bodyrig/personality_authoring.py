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
from .person_source_alignment import (
    PersonSourceAlignmentError,
    component_artifact_sha256,
    read_binding as read_source_binding,
    write_binding as write_source_binding,
)
from .personality_audition_suite import build_audition_suite
from .personality_blueprint import (
    PersonalityBlueprintError,
    blueprint_sha256,
    build_blueprint,
    compile_blueprint,
    validate_blueprint,
)
from .personality_stack import (
    PersonalityStackError,
    build_stack,
    canonical_sha256 as personality_stack_sha256,
    compile_stack,
    validate_stack,
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


BLUEPRINT_STYLE_SHA_RE = re.compile(
    r"^blueprint_sha256=([0-9a-f]{64})(?: \||$)"
)
STYLE_EVIDENCE_SUFFIX_RE = re.compile(
    r" \| style_report_sha256=([0-9a-f]{64}) \| style_approval_sha256=([0-9a-f]{64})$"
)
STACK_STYLE_SHA_RE = re.compile(
    r"^personality-stack-v1 \| stack_sha256=([0-9a-f]{64}) \|"
)


def _find_personality_revision(
    profile: Mapping[str, Any],
    revision_id: str,
) -> dict[str, Any]:
    for item in profile.get("personality_revisions", []):
        if item.get("revision_id") == revision_id:
            return dict(item)
    raise PersonalityAuthoringError(
        f"personality revision {revision_id!r} is not registered on this person"
    )


def _verified_source_baseline(
    root: str | os.PathLike[str],
    profile: Mapping[str, Any],
    revision_id: str,
) -> dict[str, Any]:
    revision = _find_personality_revision(profile, revision_id)
    try:
        binding = read_source_binding(
            root,
            profile,
            kind="personality",
            revision_id=revision_id,
        )
        artifact_sha = component_artifact_sha256(
            profile,
            "personality",
            revision_id,
        )
    except PersonSourceAlignmentError as exc:
        raise PersonalityAuthoringError(
            f"source personality baseline is invalid: {exc}"
        ) from exc

    evidence = binding["evidence"]
    evidence_kind = str(evidence.get("kind") or "")
    if evidence_kind not in {
        "stash-source-transcript-personality-v1",
        "stash-source-personality-fallback-v1",
    }:
        raise PersonalityAuthoringError(
            "baseline must be an exact source-derived Stash personality revision"
        )
    return {
        "revision": revision,
        "binding": binding,
        "artifact_sha256": artifact_sha,
    }


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
    inner_ring: Mapping[str, Any] | None,
    outer_ring: Mapping[str, Any] | None,
    style_report: Mapping[str, Any] | None,
    style_approval: Mapping[str, Any] | None,
    baseline_revision: str | None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    try:
        profile = load_profile(root, person_id)
    except PersonProfileError as exc:
        raise PersonalityAuthoringError(str(exc)) from exc

    approved, style_evidence, normalized_report, normalized_approval = _resolve_style_evidence(
        style_report, style_approval
    )
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
            inner_ring=inner_ring,
            outer_ring=outer_ring,
        )
        candidate = compile_blueprint(blueprint)
    except PersonalityBlueprintError as exc:
        raise PersonalityAuthoringError(str(exc)) from exc

    if style_evidence is not None:
        candidate["style_notes"] += (
            f" | style_report_sha256={style_evidence['candidate_report_sha256']}"
            f" | style_approval_sha256={style_evidence['approval_sha256']}"
        )

    personality_stack = None
    source_baseline = None
    if baseline_revision is not None:
        if blueprint["version"] != 2:
            raise PersonalityAuthoringError(
                "source baseline stacking requires a personality blueprint v2 overlay"
            )
        source_baseline = _verified_source_baseline(
            root,
            profile,
            baseline_revision,
        )
        baseline = source_baseline["revision"]
        binding = source_baseline["binding"]
        try:
            personality_stack = build_stack(
                person_id=person_id,
                baseline_revision_id=baseline_revision,
                baseline_artifact_sha256=source_baseline["artifact_sha256"],
                baseline_evidence_kind=binding["evidence"]["kind"],
                baseline_evidence_sha256=binding["evidence"]["sha256"],
                baseline_instructions=baseline["instructions"],
                baseline_default_language=baseline["default_language"],
                blueprint_sha256=blueprint_sha256(blueprint),
                blueprint_version=blueprint["version"],
                overlay_style_notes=candidate["style_notes"],
                style_evidence=style_evidence,
            )
            candidate = compile_stack(
                personality_stack,
                baseline_instructions=baseline["instructions"],
                overlay_candidate=candidate,
            )
        except PersonalityStackError as exc:
            raise PersonalityAuthoringError(str(exc)) from exc

    result = {
        "blueprint": blueprint,
        "blueprint_sha256": blueprint_sha256(blueprint),
        "candidate": candidate,
        "audition_suite": build_audition_suite(candidate["default_language"]),
        "style_evidence": style_evidence,
        "personality_stack": personality_stack,
        "personality_stack_sha256": (
            None
            if personality_stack is None
            else personality_stack_sha256(personality_stack)
        ),
        "source_baseline_revision": baseline_revision,
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
    inner_ring: Mapping[str, Any] | None = None,
    outer_ring: Mapping[str, Any] | None = None,
    style_report: Mapping[str, Any] | None = None,
    style_approval: Mapping[str, Any] | None = None,
    baseline_revision: str | None = None,
) -> dict[str, Any]:
    result, _report, _approval = _build_guided(
        root,
        person_id,
        default_language=default_language,
        communication=communication,
        authored_notes=authored_notes,
        style_exemplars=style_exemplars,
        body_revision=body_revision,
        inner_ring=inner_ring,
        outer_ring=outer_ring,
        style_report=style_report,
        style_approval=style_approval,
        baseline_revision=baseline_revision,
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


def persist_personality_stack_evidence(
    root: str | os.PathLike[str],
    person_id: str,
    stack: Mapping[str, Any],
) -> Path:
    root_path = Path(root).expanduser().resolve()
    try:
        load_profile(root_path, person_id)
        normalized = validate_stack(stack)
    except (PersonProfileError, PersonalityStackError) as exc:
        raise PersonalityAuthoringError(str(exc)) from exc
    if normalized["person_id"] != person_id:
        raise PersonalityAuthoringError(
            "personality stack person_id does not match target person"
        )
    digest = personality_stack_sha256(normalized)
    path = root_path / "personality-stacks" / person_id / f"{digest}.json"
    return _persist_json(path, normalized, label="personality stack")


def _read_json_evidence(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonalityAuthoringError(f"{label} evidence is unreadable") from exc
    if not isinstance(value, dict):
        raise PersonalityAuthoringError(f"{label} evidence must be an object")
    return value


def _load_style_evidence_by_sha(
    root_path: Path,
    person_id: str,
    report_sha: str,
    approval_sha: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base = root_path / "personality-style-evidence" / person_id
    report_raw = _read_json_evidence(
        base / "reports" / f"{report_sha}.json",
        label="style report",
    )
    approval_raw = _read_json_evidence(
        base / "approvals" / f"{approval_sha}.json",
        label="style approval",
    )
    try:
        normalized_report = validate_candidate_report(report_raw)
        verified_approval = verify_approval(
            normalized_report,
            validate_approval(approval_raw),
        )
    except PersonalityExemplarApprovalError as exc:
        raise PersonalityAuthoringError(
            f"saved style evidence is invalid: {exc}"
        ) from exc
    if exemplar_evidence_sha256(normalized_report) != report_sha:
        raise PersonalityAuthoringError("saved style report SHA-256 mismatch")
    if exemplar_evidence_sha256(verified_approval) != approval_sha:
        raise PersonalityAuthoringError("saved style approval SHA-256 mismatch")
    return normalized_report, verified_approval


def _load_stacked_guided_revision(
    root_path: Path,
    person_id: str,
    profile: Mapping[str, Any],
    revision: Mapping[str, Any],
    stack_digest: str,
) -> dict[str, Any]:
    stack_path = (
        root_path
        / "personality-stacks"
        / person_id
        / f"{stack_digest}.json"
    )
    stack_raw = _read_json_evidence(stack_path, label="personality stack")
    try:
        stack = validate_stack(stack_raw)
    except PersonalityStackError as exc:
        raise PersonalityAuthoringError(
            f"personality stack evidence is invalid: {exc}"
        ) from exc
    if personality_stack_sha256(stack) != stack_digest:
        raise PersonalityAuthoringError(
            "personality stack evidence SHA-256 mismatch"
        )
    if stack["person_id"] != person_id:
        raise PersonalityAuthoringError(
            "personality stack person does not match revision"
        )

    baseline_revision = stack["baseline"]["revision_id"]
    baseline = _verified_source_baseline(
        root_path,
        profile,
        baseline_revision,
    )
    baseline_item = baseline["revision"]
    baseline_binding = baseline["binding"]
    expected_baseline = {
        "revision_id": baseline_revision,
        "artifact_sha256": baseline["artifact_sha256"],
        "evidence_kind": baseline_binding["evidence"]["kind"],
        "evidence_sha256": baseline_binding["evidence"]["sha256"],
        "instructions_sha256": hashlib.sha256(
            baseline_item["instructions"].encode("utf-8")
        ).hexdigest(),
        "default_language": baseline_item["default_language"],
    }
    if stack["baseline"] != expected_baseline:
        raise PersonalityAuthoringError(
            "source baseline no longer matches personality stack evidence"
        )

    blueprint_digest = stack["overlay"]["blueprint_sha256"]
    blueprint_raw = _read_json_evidence(
        root_path
        / "personality-blueprints"
        / person_id
        / f"{blueprint_digest}.json",
        label="personality blueprint",
    )
    try:
        blueprint = validate_blueprint(blueprint_raw)
    except PersonalityBlueprintError as exc:
        raise PersonalityAuthoringError(
            f"personality blueprint evidence is invalid: {exc}"
        ) from exc
    if (
        blueprint["version"] != 2
        or blueprint_sha256(blueprint) != blueprint_digest
    ):
        raise PersonalityAuthoringError(
            "stacked personality blueprint evidence mismatch"
        )

    overlay_candidate = compile_blueprint(blueprint)
    style_report = None
    style_approval = None
    direct_examples = list(blueprint["style_exemplars"])
    report_sha = stack["overlay"]["style_report_sha256"]
    approval_sha = stack["overlay"]["style_approval_sha256"]
    if report_sha is not None and approval_sha is not None:
        style_report, style_approval = _load_style_evidence_by_sha(
            root_path,
            person_id,
            report_sha,
            approval_sha,
        )
        overlay_candidate["style_notes"] += (
            f" | style_report_sha256={report_sha}"
            f" | style_approval_sha256={approval_sha}"
        )
        approved = list(style_approval["approved_exemplars"])
        if (
            len(approved) > len(direct_examples)
            or direct_examples[len(direct_examples) - len(approved):] != approved
        ):
            raise PersonalityAuthoringError(
                "approved style exemplars no longer match stacked blueprint"
            )
        direct_examples = (
            direct_examples[:-len(approved)]
            if approved
            else direct_examples
        )

    try:
        candidate = compile_stack(
            stack,
            baseline_instructions=baseline_item["instructions"],
            overlay_candidate=overlay_candidate,
        )
    except PersonalityStackError as exc:
        raise PersonalityAuthoringError(str(exc)) from exc

    if (
        revision.get("instructions") != candidate["instructions"]
        or revision.get("default_language") != candidate["default_language"]
        or revision.get("style_notes") != candidate["style_notes"]
    ):
        raise PersonalityAuthoringError(
            "saved stacked personality no longer matches immutable evidence"
        )

    return {
        "person_id": person_id,
        "revision_id": revision["revision_id"],
        "blueprint_sha256": blueprint_digest,
        "blueprint": blueprint,
        "direct_style_exemplars": direct_examples,
        "style_report": style_report,
        "style_approval": style_approval,
        "personality_stack": stack,
        "personality_stack_sha256": stack_digest,
        "source_baseline_revision": baseline_revision,
    }


def load_guided_personality_revision(
    root: str | os.PathLike[str],
    person_id: str,
    revision_id: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    try:
        profile = load_profile(root_path, person_id)
    except PersonProfileError as exc:
        raise PersonalityAuthoringError(str(exc)) from exc

    revision = next(
        (
            dict(item)
            for item in profile.get("personality_revisions", [])
            if item.get("revision_id") == revision_id
        ),
        None,
    )
    if revision is None:
        raise PersonalityAuthoringError("personality revision is not registered on this person")

    saved_style = str(revision.get("style_notes") or "")
    stack_match = STACK_STYLE_SHA_RE.match(saved_style)
    if stack_match is not None:
        return _load_stacked_guided_revision(
            root_path,
            person_id,
            profile,
            revision,
            stack_match.group(1),
        )
    match = BLUEPRINT_STYLE_SHA_RE.match(saved_style)
    if match is None:
        raise PersonalityAuthoringError(
            "personality revision is not backed by guided blueprint evidence"
        )
    digest = match.group(1)
    blueprint_path = (
        root_path
        / "personality-blueprints"
        / person_id
        / f"{digest}.json"
    )
    blueprint_raw = _read_json_evidence(
        blueprint_path,
        label="personality blueprint",
    )
    try:
        blueprint = validate_blueprint(blueprint_raw)
    except PersonalityBlueprintError as exc:
        raise PersonalityAuthoringError(
            f"personality blueprint evidence is invalid: {exc}"
        ) from exc
    if blueprint_sha256(blueprint) != digest:
        raise PersonalityAuthoringError(
            "personality blueprint evidence SHA-256 mismatch"
        )

    compiled = compile_blueprint(blueprint)
    if revision.get("instructions") != compiled["instructions"]:
        raise PersonalityAuthoringError(
            "saved personality instructions no longer match blueprint evidence"
        )
    if revision.get("default_language") != compiled["default_language"]:
        raise PersonalityAuthoringError(
            "saved personality language no longer matches blueprint evidence"
        )

    direct_examples = list(blueprint["style_exemplars"])
    style_report = None
    style_approval = None
    if saved_style != compiled["style_notes"]:
        if not saved_style.startswith(compiled["style_notes"]):
            raise PersonalityAuthoringError(
                "saved personality style notes no longer match blueprint evidence"
            )
        suffix = saved_style[len(compiled["style_notes"]):]
        suffix_match = STYLE_EVIDENCE_SUFFIX_RE.fullmatch(suffix)
        if suffix_match is None:
            raise PersonalityAuthoringError(
                "saved personality style evidence suffix is invalid"
            )
        report_sha, approval_sha = suffix_match.groups()
        normalized_report, verified_approval = _load_style_evidence_by_sha(
            root_path,
            person_id,
            report_sha,
            approval_sha,
        )
        approved = list(verified_approval["approved_exemplars"])
        if (
            len(approved) > len(direct_examples)
            or direct_examples[len(direct_examples) - len(approved):] != approved
        ):
            raise PersonalityAuthoringError(
                "approved style exemplars no longer match blueprint evidence"
            )
        direct_examples = (
            direct_examples[:-len(approved)]
            if approved
            else direct_examples
        )
        style_report = normalized_report
        style_approval = verified_approval

    return {
        "person_id": person_id,
        "revision_id": revision_id,
        "blueprint_sha256": digest,
        "blueprint": blueprint,
        "direct_style_exemplars": direct_examples,
        "style_report": style_report,
        "style_approval": style_approval,
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
    inner_ring: Mapping[str, Any] | None = None,
    outer_ring: Mapping[str, Any] | None = None,
    style_report: Mapping[str, Any] | None = None,
    style_approval: Mapping[str, Any] | None = None,
    baseline_revision: str | None = None,
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
        inner_ring=inner_ring,
        outer_ring=outer_ring,
        style_report=style_report,
        style_approval=style_approval,
        baseline_revision=baseline_revision,
    )
    style_paths = None
    if normalized_report is not None and normalized_approval is not None:
        style_paths = persist_style_evidence(root, person_id, normalized_report, normalized_approval)
    blueprint_path = persist_blueprint_evidence(root, person_id, result["blueprint"])
    stack_path = None
    if result["personality_stack"] is not None:
        stack_path = persist_personality_stack_evidence(
            root,
            person_id,
            result["personality_stack"],
        )
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
    if result["personality_stack"] is not None:
        baseline = _verified_source_baseline(
            root,
            profile,
            str(result["source_baseline_revision"]),
        )
        try:
            source_binding = write_source_binding(
                root,
                profile,
                kind="personality",
                revision_id=saved_revision,
                evidence_kind="personality-stack-v1",
                evidence_sha256=result["personality_stack_sha256"],
                evidence_ref=str(stack_path),
                source_files=list(
                    baseline["binding"]["evidence"].get("source_files") or []
                ),
            )
        except PersonSourceAlignmentError as exc:
            raise PersonalityAuthoringError(
                f"could not bind stacked personality to source: {exc}"
            ) from exc
    elif body_revision is not None and profile.get("source") is not None:
        try:
            source_binding = write_source_binding(
                root,
                profile,
                kind="personality",
                revision_id=saved_revision,
                evidence_kind=f"personality-blueprint-v{result['blueprint']['version']}",
                evidence_sha256=result["blueprint_sha256"],
                evidence_ref=str(blueprint_path),
            )
        except PersonSourceAlignmentError as exc:
            raise PersonalityAuthoringError(f"could not bind guided personality to source: {exc}") from exc

    return {
        **result,
        "evidence_path": str(blueprint_path),
        "personality_stack_path": (
            None if stack_path is None else str(stack_path)
        ),
        "style_evidence_paths": {key: str(path) for key, path in style_paths.items()} if style_paths else None,
        "source_binding": source_binding,
        "profile": profile,
        "saved_personality_revision": saved_revision,
    }