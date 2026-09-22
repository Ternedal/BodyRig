from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from .fidelity_component_gap import FORMAT as GAP_FORMAT
from .fidelity_component_gap import SEMANTICS as GAP_SEMANTICS
from .hfn_existing_authority import (
    HfnExistingAuthorityError,
    find_reusable_hfn_source_uv_authorities,
)
from .high_fidelity_continuation_status import continuation_paths, inspect_continuation
from .high_fidelity_hfn_continuation import (
    CANDIDATE_GATE as HFN_CANDIDATE_GATE,
    HUMAN_GATE as HFN_HUMAN_GATE,
    RENDER_GATE as HFN_RENDER_GATE,
    HighFidelityHfnContinuationError,
    inspect_hfn_continuation,
)
from .high_fidelity_preview_jobs import manager as preview_manager

FORMAT = "bodyrig-fidelity-component-gap-execution"
VERSION = 1
SEMANTICS = "execute-one-machine-safe-component-gap-action-then-reprobe"
PLAN_FIELDS = {
    "format",
    "version",
    "bodyrig_revision",
    "body_id",
    "package_sha256",
    "state",
    "drawable_components",
    "missing_components",
    "next_actions",
    "strict_machine_scoring_ready",
    "human_visual_authority_required",
    "production_activation",
    "semantics",
}
ACTION_FIELDS = {
    "id",
    "components",
    "operator_input_required",
    "implementation_required",
    "reason",
}
ACTION_AUTHORITY = {
    "retained-source-hair-eye-composition": (False, False),
    "face-secondary-review-composition": (False, False),
    "source-bound-hfn-continuation": (True, False),
    "human-visual-qa": (True, False),
}
FACE_MACHINE_GATES = {"face_secondary_runtime", "face_secondary_preview"}
HFN_MACHINE_GATES = {HFN_CANDIDATE_GATE, HFN_RENDER_GATE}
PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
BODY_REVISION_RE = re.compile(r"^body-r[0-9]{4}$")
HFN_CAPTURE_RE = re.compile(r"^hfncap-[0-9a-f]{32}$")
HFN_CANDIDATE_RE = re.compile(r"^hfncand-[0-9a-f]{32}$")


class FidelityComponentGapExecutionError(RuntimeError):
    pass


def _is_v1(value: Any) -> bool:
    return not isinstance(value, bool) and value == 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha(value: Any, *, field: str, length: int) -> str:
    text = str(value or "").strip().lower()
    if len(text) != length or any(ch not in "0123456789abcdef" for ch in text):
        raise FidelityComponentGapExecutionError(f"{field} is not canonical")
    return text


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FidelityComponentGapExecutionError(f"{label} is missing or symlinked: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FidelityComponentGapExecutionError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise FidelityComponentGapExecutionError(f"{label} must be an object")
    return value


def validate_plan(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != PLAN_FIELDS:
        raise FidelityComponentGapExecutionError("component gap plan fields must match v1 exactly")
    if value.get("format") != GAP_FORMAT or not _is_v1(value.get("version")):
        raise FidelityComponentGapExecutionError("component gap plan format/version mismatch")
    if value.get("semantics") != GAP_SEMANTICS:
        raise FidelityComponentGapExecutionError("component gap plan semantics mismatch")
    if value.get("human_visual_authority_required") is not True or value.get("production_activation") is not False:
        raise FidelityComponentGapExecutionError("component gap plan crossed its authority boundary")
    revision = _canonical_sha(value.get("bodyrig_revision"), field="bodyrig_revision", length=40)
    package_sha = _canonical_sha(value.get("package_sha256"), field="package_sha256", length=64)
    body_id = value.get("body_id")
    if not isinstance(body_id, str) or not body_id.strip() or len(body_id) > 160:
        raise FidelityComponentGapExecutionError("component gap plan body_id is invalid")
    for field in ("drawable_components", "missing_components"):
        items = value.get(field)
        if not isinstance(items, list) or any(not isinstance(item, str) or not item for item in items):
            raise FidelityComponentGapExecutionError(f"component gap plan {field} is invalid")
    ready = value.get("strict_machine_scoring_ready")
    if not isinstance(ready, bool):
        raise FidelityComponentGapExecutionError("component gap plan strict_machine_scoring_ready must be boolean")
    state = value.get("state")
    if state not in {"composition-required", "machine-component-complete-human-review-required"}:
        raise FidelityComponentGapExecutionError("component gap plan state is invalid")
    missing = list(value["missing_components"])
    if ready is (bool(missing)):
        raise FidelityComponentGapExecutionError("component gap plan readiness disagrees with missing components")
    if (state == "composition-required") is (not missing):
        raise FidelityComponentGapExecutionError("component gap plan state disagrees with missing components")

    actions = value.get("next_actions")
    if not isinstance(actions, list) or not actions:
        raise FidelityComponentGapExecutionError("component gap plan next_actions must be non-empty")
    normalized_actions: list[dict[str, Any]] = []
    for raw in actions:
        if not isinstance(raw, Mapping) or set(raw) != ACTION_FIELDS:
            raise FidelityComponentGapExecutionError("component gap action fields must match v1 exactly")
        action_id = raw.get("id")
        if action_id not in ACTION_AUTHORITY:
            raise FidelityComponentGapExecutionError("component gap action id is unsupported")
        operator_required, implementation_required = ACTION_AUTHORITY[action_id]
        if raw.get("operator_input_required") is not operator_required:
            raise FidelityComponentGapExecutionError(f"component gap action {action_id} operator boundary mismatch")
        if raw.get("implementation_required") is not implementation_required:
            raise FidelityComponentGapExecutionError(f"component gap action {action_id} implementation boundary mismatch")
        components = raw.get("components")
        if not isinstance(components, list) or not components or any(not isinstance(item, str) or not item for item in components):
            raise FidelityComponentGapExecutionError(f"component gap action {action_id} components are invalid")
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise FidelityComponentGapExecutionError(f"component gap action {action_id} reason is invalid")
        normalized_actions.append(dict(raw))

    if ready and normalized_actions[0]["id"] != "human-visual-qa":
        raise FidelityComponentGapExecutionError("component-complete gap plan must stop at human visual QA")
    if not ready and normalized_actions[0]["id"] == "human-visual-qa":
        raise FidelityComponentGapExecutionError("incomplete gap plan cannot route directly to human visual QA")
    return {
        **dict(value),
        "bodyrig_revision": revision,
        "body_id": body_id.strip(),
        "package_sha256": package_sha,
        "next_actions": normalized_actions,
    }


def _need_file(value: Any, *, label: str) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise FidelityComponentGapExecutionError(f"{label} is missing or symlinked: {path}")
    return path


def _need_dir(value: Any, *, label: str) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_dir() or path.is_symlink():
        raise FidelityComponentGapExecutionError(f"{label} is missing or symlinked: {path}")
    return path


def _need_absent(value: Any, *, label: str) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    if path.exists():
        raise FidelityComponentGapExecutionError(f"{label} already exists; refusing cross-attempt reuse: {path}")
    if not path.parent.is_dir():
        raise FidelityComponentGapExecutionError(f"{label} parent does not exist: {path.parent}")
    return path


def _pwsh(repo_root: Path, script: str, *args: str) -> list[str]:
    script_path = repo_root / script
    if not script_path.is_file():
        raise FidelityComponentGapExecutionError(f"canonical BodyRig operator is missing: {script_path}")
    return ["pwsh", "-NoProfile", "-File", str(script_path), *args]


def _hair_eye_execution(plan: Mapping[str, Any], context: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
    package = _need_file(context.get("package_path"), label="gap source package")
    if _sha256_file(package) != plan["package_sha256"]:
        raise FidelityComponentGapExecutionError("gap source package bytes differ from the Unity gap-plan package SHA")
    workspace = _need_dir(context.get("identity_workspace"), label="retained identity workspace")
    output = _need_absent(context.get("output_root"), label="retained hair+eye execution output")
    argv = _pwsh(
        repo_root,
        "run-retained-hair-eye-preview.ps1",
        "-PackagePath", str(package),
        "-IdentityWorkspace", str(workspace),
        "-OutputRoot", str(output),
    )
    return {"mode": "machine-executable", "commands": [argv], "operator_input_required": False}


def _face_execution(plan: Mapping[str, Any], context: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
    preview_job_id = str(context.get("preview_job_id") or "").strip()
    preview_lineage_resolution = "explicit"
    try:
        if preview_job_id:
            preview = preview_manager.get(preview_job_id)
        else:
            preview = preview_manager.resolve_succeeded_candidate(
                canonical_body_id=plan["body_id"],
                bodyrig_revision=plan["bodyrig_revision"],
                candidate_package_sha256=plan["package_sha256"],
            )
            preview_job_id = str(preview.get("job_id") or "").strip()
            preview_lineage_resolution = "auto-exact-candidate"
    except Exception as exc:
        raise FidelityComponentGapExecutionError("face-secondary preview lineage is unavailable or invalid") from exc
    if not preview_job_id:
        raise FidelityComponentGapExecutionError("resolved face-secondary preview lineage has no job id")
    if preview.get("status") != "succeeded":
        raise FidelityComponentGapExecutionError("face-secondary execution requires a succeeded high-fidelity preview")
    preview_body_id = str(preview.get("canonical_body_id") or "").strip()
    preview_revision = _canonical_sha(
        preview.get("bodyrig_revision"),
        field="preview bodyrig_revision",
        length=40,
    )
    preview_person_id = str(preview.get("person_id") or "").strip()
    if not preview_person_id:
        raise FidelityComponentGapExecutionError("face-secondary preview lacks canonical person lineage")
    if preview_body_id != plan["body_id"]:
        raise FidelityComponentGapExecutionError("face-secondary preview belongs to a different canonical body than the gap plan")
    if preview_revision != plan["bodyrig_revision"]:
        raise FidelityComponentGapExecutionError("face-secondary preview targets a different BodyRig revision than the gap plan")
    preview_candidate_sha = _canonical_sha(
        preview.get("candidate_package_sha256"),
        field="preview candidate package SHA",
        length=64,
    )
    if preview_candidate_sha != plan["package_sha256"]:
        raise FidelityComponentGapExecutionError(
            "face-secondary preview targets a different candidate package than the Unity gap plan"
        )
    preview_fine_authority_sha = _canonical_sha(
        preview.get("fine_identity_authority_sha256"),
        field="preview fine-identity authority SHA",
        length=64,
    )
    preview_fine_attestation_sha = _canonical_sha(
        preview.get("fine_identity_attestation_sha256"),
        field="preview fine-identity attestation SHA",
        length=64,
    )
    status = inspect_continuation(preview_job_id)
    if status.get("production_activation") is not False or status.get("production_ready") is not False:
        raise FidelityComponentGapExecutionError("high-fidelity continuation crossed the non-production boundary")
    status_fine_authority_sha = _canonical_sha(
        status.get("fine_identity_authority_sha256"),
        field="continuation fine-identity authority SHA",
        length=64,
    )
    status_fine_attestation_sha = _canonical_sha(
        status.get("fine_identity_attestation_sha256"),
        field="continuation fine-identity attestation SHA",
        length=64,
    )
    if (
        status_fine_authority_sha != preview_fine_authority_sha
        or status_fine_attestation_sha != preview_fine_attestation_sha
    ):
        raise FidelityComponentGapExecutionError(
            "face-secondary continuation fine-identity lineage differs from the validated preview"
        )
    current_package = _need_file(status.get("current_package_path"), label="continuation current package")
    current_sha = _canonical_sha(status.get("current_package_sha256"), field="continuation current package SHA", length=64)
    if _sha256_file(current_package) != current_sha:
        raise FidelityComponentGapExecutionError("continuation current package bytes changed after status inspection")
    next_gate = status.get("next_gate")
    if not isinstance(next_gate, Mapping):
        raise FidelityComponentGapExecutionError("canonical continuation has no executable face-secondary gate")
    gate = next_gate.get("gate")
    if gate not in FACE_MACHINE_GATES or next_gate.get("operator_input_required") is not False:
        raise FidelityComponentGapExecutionError(
            f"canonical continuation is not at a machine-safe face-secondary gate: {gate or 'none'}"
        )
    paths = continuation_paths(preview_job_id)
    if gate == "face_secondary_runtime":
        output = Path(paths["face_runtime"]).expanduser().resolve()
        if output.exists():
            raise FidelityComponentGapExecutionError("face-secondary runtime output already exists before runtime gate")
        argv = _pwsh(
            repo_root,
            "build-high-fidelity-face-secondary-review-runtime.ps1",
            "-PackagePath", str(current_package),
            "-OutputDir", str(output),
        )
    else:
        runtime_dir = _need_dir(paths["face_runtime"], label="face-secondary review runtime")
        output = Path(paths["face_preview_root"]).expanduser().resolve()
        if output.exists():
            raise FidelityComponentGapExecutionError("face-secondary preview output already exists before preview gate")
        argv = _pwsh(
            repo_root,
            "run-high-fidelity-face-secondary-windows-preview.ps1",
            "-PackagePath", str(current_package),
            "-RuntimeDir", str(runtime_dir),
            "-OutputDir", str(output),
        )
    return {
        "mode": "machine-executable",
        "commands": [argv],
        "operator_input_required": False,
        "continuation_gate": gate,
        "preview_job_id": preview_job_id,
        "person_id": preview_person_id,
        "canonical_body_id": preview_body_id,
        "preview_bodyrig_revision": preview_revision,
        "preview_candidate_package_sha256": preview_candidate_sha,
        "fine_identity_authority_sha256": preview_fine_authority_sha,
        "fine_identity_attestation_sha256": preview_fine_attestation_sha,
        "preview_lineage_resolution": preview_lineage_resolution,
    }


def _canonical_hfn_id(value: Any, *, pattern: re.Pattern[str], field: str) -> str:
    text = str(value or "").strip().lower()
    if not pattern.fullmatch(text):
        raise FidelityComponentGapExecutionError(f"{field} is not canonical")
    return text


def _hfn_context_path(value: Any, *, label: str) -> Path:
    text = str(value or "").strip()
    if not text:
        raise FidelityComponentGapExecutionError(f"{label} is required")
    raw = Path(text).expanduser()
    if raw.is_symlink():
        raise FidelityComponentGapExecutionError(f"{label} is symlinked: {raw}")
    return raw.resolve()


def _reusable_hfn_detail_execution(
    plan: Mapping[str, Any],
    *,
    hfn_root: Path,
    person_id: str,
    body_revision: str,
    status_package: Path,
    status_sha: str,
    repo_root: Path,
) -> dict[str, Any] | None:
    try:
        matches = find_reusable_hfn_source_uv_authorities(
            hfn_root,
            person_id,
            body_revision=body_revision,
            package_path=status_package,
            package_sha256=status_sha,
        )
    except HfnExistingAuthorityError as exc:
        raise FidelityComponentGapExecutionError(
            f"existing HFN source/UV authority discovery failed closed: {exc}"
        ) from exc
    if len(matches) != 1:
        return None

    authority = matches[0]
    if authority.get("package_sha256") != status_sha or status_sha != plan["package_sha256"]:
        raise FidelityComponentGapExecutionError(
            "reusable HFN source/UV authority targets different package bytes than the Unity gap plan"
        )
    if authority.get("body_id") != plan["body_id"]:
        raise FidelityComponentGapExecutionError(
            "reusable HFN source/UV authority targets a different canonical body than the Unity gap plan"
        )
    capture_id = _canonical_hfn_id(
        authority.get("capture_id"), pattern=HFN_CAPTURE_RE, field="reusable HFN capture_id"
    )
    uv_path = _need_file(authority.get("uv_evidence_path"), label="reusable HFN UV evidence")
    expected_uv_root = (
        hfn_root
        / "hands-feet-nails-uv-domain-evidence"
        / person_id
        / body_revision
        / capture_id
    ).resolve()
    if uv_path.parent != expected_uv_root:
        raise FidelityComponentGapExecutionError(
            "reusable HFN UV evidence escaped the exact Person/body/capture authority path"
        )
    uv_sha = _canonical_sha(
        authority.get("uv_evidence_sha256"), field="reusable HFN UV evidence SHA", length=64
    )
    if _sha256_file(uv_path) != uv_sha:
        raise FidelityComponentGapExecutionError(
            "reusable HFN UV evidence bytes changed after exact authority discovery"
        )
    source_capture_sha = _canonical_sha(
        authority.get("source_capture_sha256"), field="reusable HFN source-capture SHA", length=64
    )
    landmark_sha = _canonical_sha(
        authority.get("landmark_evidence_sha256"), field="reusable HFN landmark-evidence SHA", length=64
    )
    argv = _pwsh(
        repo_root,
        "prepare-hands-feet-nails-detail-candidate.ps1",
        "-Root", str(hfn_root),
        "-PersonId", person_id,
        "-BodyRevision", body_revision,
        "-CaptureId", capture_id,
        "-UvEvidence", str(uv_path),
        "-PackagePath", str(status_package),
    )
    return {
        "mode": "machine-executable",
        "commands": [argv],
        "operator_input_required": False,
        "hfn_gate": HFN_CANDIDATE_GATE,
        "hfn_substep": "detail-candidate",
        "hfn_current_package_sha256": status_sha,
        "hfn_reused_existing_source_uv_authority": True,
        "hfn_capture_id": capture_id,
        "hfn_uv_evidence_path": str(uv_path),
        "hfn_uv_evidence_sha256": uv_sha,
        "hfn_source_capture_sha256": source_capture_sha,
        "hfn_landmark_evidence_sha256": landmark_sha,
        "person_id": person_id,
        "body_revision": body_revision,
    }


def _hfn_execution(plan: Mapping[str, Any], context: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
    required_context = (
        "package_path",
        "hfn_root",
        "person_id",
        "body_revision",
        "hfn_render_dir",
        "hfn_human_review_dir",
    )
    missing_context = [name for name in required_context if not str(context.get(name) or "").strip()]
    if missing_context:
        return {
            "mode": "operator-stop",
            "commands": [],
            "operator_input_required": True,
            "reason": (
                "HFN continuation requires explicit source-bound context before it can distinguish "
                "manual source selection from machine-safe geometry/render gates: " + ", ".join(missing_context)
            ),
        }

    package = _need_file(context.get("package_path"), label="HFN gap source package")
    if _sha256_file(package) != plan["package_sha256"]:
        raise FidelityComponentGapExecutionError("HFN source package bytes differ from the Unity gap-plan package SHA")
    hfn_root = _need_dir(context.get("hfn_root"), label="HFN person library root")
    person_id = _canonical_hfn_id(context.get("person_id"), pattern=PERSON_RE, field="HFN person_id")
    body_revision = _canonical_hfn_id(
        context.get("body_revision"), pattern=BODY_REVISION_RE, field="HFN body_revision"
    )
    render_dir = _hfn_context_path(context.get("hfn_render_dir"), label="HFN render directory")
    human_review_dir = _hfn_context_path(
        context.get("hfn_human_review_dir"), label="HFN human-review directory"
    )

    try:
        status = inspect_hfn_continuation(
            root=hfn_root,
            person_id=person_id,
            body_revision=body_revision,
            bodyrig_revision=plan["bodyrig_revision"],
            source_package_path=package,
            source_package_sha256=plan["package_sha256"],
            render_dir=render_dir,
            human_review_dir=human_review_dir,
        )
    except (HighFidelityHfnContinuationError, OSError) as exc:
        raise FidelityComponentGapExecutionError(f"canonical HFN continuation is invalid: {exc}") from exc

    status_package = _need_file(status.get("package_path"), label="HFN continuation current package")
    status_sha = _canonical_sha(
        status.get("package_sha256"), field="HFN continuation current package SHA", length=64
    )
    if _sha256_file(status_package) != status_sha:
        raise FidelityComponentGapExecutionError("HFN continuation current package bytes changed after inspection")

    actions = status.get("actions")
    if not isinstance(actions, Mapping):
        raise FidelityComponentGapExecutionError("canonical HFN continuation actions are invalid")
    if not actions:
        raise FidelityComponentGapExecutionError(
            "canonical HFN continuation has no pending action; a fresh Unity component probe is required"
        )
    if len(actions) != 1:
        raise FidelityComponentGapExecutionError("canonical HFN continuation exposed multiple pending actions")
    subaction = next(iter(actions.values()))
    if not isinstance(subaction, Mapping):
        raise FidelityComponentGapExecutionError("canonical HFN continuation action is invalid")
    gate = str(subaction.get("gate") or "").strip()
    operator_required = subaction.get("operator_input_required")
    reason = str(subaction.get("reason") or "").strip()
    operator_command = str(subaction.get("command") or "").strip()
    if not gate or not reason or not operator_command or not isinstance(operator_required, bool):
        raise FidelityComponentGapExecutionError("canonical HFN continuation action fields are invalid")

    if operator_required:
        if gate not in {HFN_CANDIDATE_GATE, HFN_HUMAN_GATE}:
            raise FidelityComponentGapExecutionError(f"unexpected operator-required HFN gate: {gate}")
        if gate == HFN_CANDIDATE_GATE:
            reusable = _reusable_hfn_detail_execution(
                plan,
                hfn_root=hfn_root,
                person_id=person_id,
                body_revision=body_revision,
                status_package=status_package,
                status_sha=status_sha,
                repo_root=repo_root,
            )
            if reusable is not None:
                return reusable
        return {
            "mode": "operator-stop",
            "commands": [],
            "operator_input_required": True,
            "reason": reason,
            "operator_command": operator_command,
            "hfn_gate": gate,
            "hfn_current_package_sha256": status_sha,
        }

    if gate not in HFN_MACHINE_GATES:
        raise FidelityComponentGapExecutionError(f"canonical HFN continuation is not at a machine-safe gate: {gate}")

    if gate == HFN_CANDIDATE_GATE:
        candidate = status.get("candidate")
        if not isinstance(candidate, Mapping):
            raise FidelityComponentGapExecutionError("machine-safe HFN geometry gate lacks exact candidate authority")
        capture_id = _canonical_hfn_id(
            candidate.get("capture_id"), pattern=HFN_CAPTURE_RE, field="HFN capture_id"
        )
        candidate_id = _canonical_hfn_id(
            candidate.get("candidate_id"), pattern=HFN_CANDIDATE_RE, field="HFN candidate_id"
        )
        if candidate.get("fingernail_geometry_package_sha256"):
            script = "prepare-hands-feet-nails-toenail-geometry-candidate.ps1"
            substep = "toenail-geometry"
        else:
            script = "prepare-hands-feet-nails-fingernail-geometry-candidate.ps1"
            substep = "fingernail-geometry"
        argv = _pwsh(
            repo_root,
            script,
            "-Root", str(hfn_root),
            "-PersonId", person_id,
            "-BodyRevision", body_revision,
            "-CaptureId", capture_id,
            "-CandidateId", candidate_id,
        )
    else:
        output = _need_absent(render_dir, label="HFN canonical render-review output")
        argv = _pwsh(
            repo_root,
            "prepare-hands-feet-nails-render-review.ps1",
            "-PackagePath", str(status_package),
            "-OutputDir", str(output),
        )
        substep = "render-review"

    return {
        "mode": "machine-executable",
        "commands": [argv],
        "operator_input_required": False,
        "hfn_gate": gate,
        "hfn_substep": substep,
        "hfn_current_package_sha256": status_sha,
        "person_id": person_id,
        "body_revision": body_revision,
    }


def build_execution(plan: Mapping[str, Any], *, context: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
    validated = validate_plan(plan)
    root = repo_root.expanduser().resolve()
    if not root.is_dir():
        raise FidelityComponentGapExecutionError(f"BodyRig repository root is missing: {root}")
    action = validated["next_actions"][0]
    action_id = action["id"]
    if action_id == "retained-source-hair-eye-composition":
        route = _hair_eye_execution(validated, context, root)
    elif action_id == "face-secondary-review-composition":
        route = _face_execution(validated, context, root)
    elif action_id == "source-bound-hfn-continuation":
        route = _hfn_execution(validated, context, root)
    else:
        route = {
            "mode": "operator-stop",
            "commands": [],
            "operator_input_required": True,
            "reason": action["reason"],
        }
    return {
        "format": FORMAT,
        "version": VERSION,
        "bodyrig_revision": validated["bodyrig_revision"],
        "body_id": validated["body_id"],
        "source_gap_package_sha256": validated["package_sha256"],
        "action_id": action_id,
        "components": list(action["components"]),
        **route,
        "reprobe_required_after_execution": route["mode"] == "machine-executable",
        "human_visual_authority_required": True,
        "production_activation": False,
        "semantics": SEMANTICS,
    }


def execute(execution: Mapping[str, Any], *, runner=subprocess.run) -> dict[str, Any]:
    if execution.get("mode") != "machine-executable":
        raise FidelityComponentGapExecutionError("component gap action requires operator/human input and cannot auto-execute")
    if os.name != "nt":
        raise FidelityComponentGapExecutionError("component gap machine execution is Windows-only")
    commands = execution.get("commands")
    if not isinstance(commands, list) or len(commands) != 1 or not isinstance(commands[0], list):
        raise FidelityComponentGapExecutionError("component gap execution must contain exactly one canonical command")
    completed = runner(commands[0], check=False)
    code = int(getattr(completed, "returncode", 1))
    if code != 0:
        raise FidelityComponentGapExecutionError(f"component gap operator failed with exit code {code}")
    return {**dict(execution), "executed": True, "exit_code": code}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute exactly one machine-safe BodyRig component gap action, then require a fresh Unity probe.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = _read_json(Path(args.plan).expanduser().resolve(), label="component gap plan")
        context = _read_json(Path(args.context).expanduser().resolve(), label="component gap execution context")
        result = build_execution(plan, context=context, repo_root=Path(args.repo_root))
        if args.execute and result.get("mode") == "machine-executable":
            result = execute(result)
    except (FidelityComponentGapExecutionError, OSError) as exc:
        print(f"BodyRig fidelity component gap execution: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())