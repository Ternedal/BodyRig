from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .fidelity_component_gap import FORMAT as GAP_FORMAT
from .fidelity_component_gap import SEMANTICS as GAP_SEMANTICS
from .bridges.sith_pbr_material import PbrMaterialError, _read_glb
from .high_fidelity_face_secondary_runtime import APPEARANCE_METHOD
from .high_fidelity_hfn_continuation import (
    CANDIDATE_GATE as HFN_CANDIDATE_GATE,
    HUMAN_GATE as HFN_HUMAN_GATE,
    RENDER_GATE as HFN_RENDER_GATE,
    inspect_hfn_continuation,
)
from .package import MRBodyError, validate_package
from .high_fidelity_continuation_status import continuation_paths, inspect_continuation
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
HFN_MACHINE_SCRIPTS = {
    HFN_CANDIDATE_GATE: (
        ".\\prepare-hands-feet-nails-fingernail-geometry-candidate.ps1",
        ".\\prepare-hands-feet-nails-toenail-geometry-candidate.ps1",
    ),
    HFN_RENDER_GATE: (".\\prepare-hands-feet-nails-render-review.ps1",),
}


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


def _canonical_json_sha(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _appearance_transfer_authority(package: Path) -> tuple[str, str, str]:
    try:
        validated = validate_package(package)
        with zipfile.ZipFile(package, "r") as archive:
            avatar = archive.read("avatar.vrm")
        document, _binary = _read_glb(avatar)
    except (MRBodyError, OSError, zipfile.BadZipFile, KeyError, PbrMaterialError) as exc:
        raise FidelityComponentGapExecutionError("HFN appearance authority package is invalid") from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    appearance = bodyrig.get("appearanceTransfer") if isinstance(bodyrig, dict) else None
    if not isinstance(appearance, dict) or appearance.get("method") != APPEARANCE_METHOD:
        raise FidelityComponentGapExecutionError("canonical appearanceTransfer authority is missing")
    if (
        appearance.get("canonicalDonorAtlas") is not True
        or appearance.get("sourceDerivedPbrApplied") is not True
        or appearance.get("boundedBaseColorRefinementApplied") is not True
        or appearance.get("generativeAppearanceSynthesis") is not False
        or appearance.get("geometryModified") is not False
    ):
        raise FidelityComponentGapExecutionError("canonical appearanceTransfer authority is invalid")
    return _canonical_json_sha(appearance), str(validated.manifest["id"]), _sha256_file(package)


def _explicit_context_path(value: Any, *, label: str) -> Path:
    text = str(value or "").strip()
    if not text:
        raise FidelityComponentGapExecutionError(f"{label} must be supplied explicitly")
    return Path(text).expanduser().resolve()


def _explicit_context_id(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."} or Path(text).name != text:
        raise FidelityComponentGapExecutionError(f"{label} must be supplied explicitly and canonically")
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
    status = inspect_continuation(preview_job_id)
    if status.get("production_activation") is not False or status.get("production_ready") is not False:
        raise FidelityComponentGapExecutionError("high-fidelity continuation crossed the non-production boundary")
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
        "preview_lineage_resolution": preview_lineage_resolution,
    }


def _hfn_execution(plan: Mapping[str, Any], context: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
    package = _need_file(context.get("package_path"), label="HFN gap source package")
    if _sha256_file(package) != plan["package_sha256"]:
        raise FidelityComponentGapExecutionError("HFN source package bytes differ from the Unity gap-plan package SHA")
    appearance_source = _need_file(
        context.get("appearance_source_package_path"),
        label="HFN appearance source package",
    )
    source_appearance_sha, source_body_id, source_package_sha = _appearance_transfer_authority(appearance_source)
    final_appearance_sha, final_body_id, final_package_sha = _appearance_transfer_authority(package)
    if final_package_sha != plan["package_sha256"]:
        raise FidelityComponentGapExecutionError("HFN final package hash changed during appearance authority inspection")
    if source_package_sha == final_package_sha:
        raise FidelityComponentGapExecutionError(
            "HFN appearance preservation requires a distinct pre-face-secondary source package"
        )
    if source_body_id != final_body_id or final_body_id != plan["body_id"]:
        raise FidelityComponentGapExecutionError("HFN appearance source/final package body identity disagrees with the gap plan")
    if source_appearance_sha != final_appearance_sha:
        raise FidelityComponentGapExecutionError(
            "face-secondary comparison package changed canonical appearanceTransfer authority"
        )

    hfn_root = _explicit_context_path(context.get("hfn_root"), label="HFN root")
    person_id = _explicit_context_id(context.get("person_id"), label="HFN PersonId")
    body_revision = _explicit_context_id(context.get("body_revision"), label="HFN body revision")
    render_dir = _explicit_context_path(context.get("render_dir"), label="HFN render directory")
    human_review_dir = _explicit_context_path(context.get("human_review_dir"), label="HFN human-review directory")
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
    gates = status.get("gates")
    actions = status.get("actions")
    if not isinstance(gates, list) or not gates or not isinstance(actions, Mapping):
        raise FidelityComponentGapExecutionError("canonical HFN continuation returned invalid status")
    invalid = next((gate for gate in gates if isinstance(gate, Mapping) and gate.get("state") == "invalid"), None)
    if invalid is not None:
        raise FidelityComponentGapExecutionError(
            f"canonical HFN continuation is invalid: {invalid.get('reason') or 'unknown reason'}"
        )

    pending = next((gate for gate in gates if isinstance(gate, Mapping) and gate.get("state") != "pass"), None)
    if pending is None:
        return {
            "mode": "operator-stop",
            "commands": [],
            "operator_input_required": True,
            "reason": "canonical HFN continuation has no further machine action; human/release authority is not automatic",
            "hfn_gate": "complete",
            "hfn_status_reinspect_required_after_execution": False,
            "appearance_source_package_sha256": source_package_sha,
            "appearance_transfer_sha256": final_appearance_sha,
        }
    gate_id = str(pending.get("id") or "")
    action = actions.get(gate_id)
    if not isinstance(action, Mapping):
        raise FidelityComponentGapExecutionError(f"canonical HFN continuation has no action for required gate: {gate_id}")
    reason = str(action.get("reason") or pending.get("reason") or "").strip()
    if not reason:
        raise FidelityComponentGapExecutionError("canonical HFN continuation action has no reason")
    operator_required = action.get("operator_input_required")
    command = str(action.get("command") or "").strip()
    if operator_required is True:
        return {
            "mode": "operator-stop",
            "commands": [],
            "operator_input_required": True,
            "reason": reason,
            "operator_command": command,
            "hfn_gate": gate_id,
            "hfn_status_reinspect_required_after_execution": False,
            "appearance_source_package_sha256": source_package_sha,
            "appearance_transfer_sha256": final_appearance_sha,
        }
    if operator_required is not False:
        raise FidelityComponentGapExecutionError("canonical HFN continuation operator boundary is invalid")
    allowed = HFN_MACHINE_SCRIPTS.get(gate_id, ())
    if not allowed or not any(command.startswith(prefix + " ") or command == prefix for prefix in allowed):
        raise FidelityComponentGapExecutionError(
            f"canonical HFN continuation is not at an allowed one-step machine gate: {gate_id}"
        )
    if any(token in command for token in ("\r", "\n", ";", "|", "&&", "||")):
        raise FidelityComponentGapExecutionError("canonical HFN machine command contains unsupported command composition")
    return {
        "mode": "machine-executable",
        "commands": [["pwsh", "-NoProfile", "-Command", command]],
        "working_directory": str(repo_root),
        "operator_input_required": False,
        "reason": reason,
        "hfn_gate": gate_id,
        "hfn_status_reinspect_required_after_execution": True,
        "appearance_source_package_sha256": source_package_sha,
        "appearance_transfer_sha256": final_appearance_sha,
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
    runner_kwargs: dict[str, Any] = {"check": False}
    working_directory = execution.get("working_directory")
    if working_directory is not None:
        workdir = os.path.abspath(os.path.expanduser(str(working_directory)))
        if not os.path.isdir(workdir):
            raise FidelityComponentGapExecutionError("component gap execution working directory is missing")
        runner_kwargs["cwd"] = workdir
    completed = runner(commands[0], **runner_kwargs)
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
        if args.execute:
            result = execute(result)
    except (FidelityComponentGapExecutionError, OSError) as exc:
        print(f"BodyRig fidelity component gap execution: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
