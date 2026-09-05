from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .acceptance_status import (
    AcceptanceStatusError,
    QUALITY_REVIEW_BOOLEAN_FIELDS,
    QUALITY_REVIEW_FIELDS,
    inspect_acceptance_dir,
)
from .high_fidelity_human_review import HighFidelityHumanReviewError, review_status as fidelity_human_review_status
from .high_fidelity_package_audit import HighFidelityPackageAuditError, audit_high_fidelity_package
from .reference_acceptance_policy import apply_reference_policy
from .storage import body_library

FORMAT = "bodyrig-person-release-status"
VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE_OPERATOR_FILES = (
    "run-reference-windows-renderer-probe.ps1",
    "record-reference-renderer-acceptance.ps1",
    "run-reference-quest-renderer-probe.ps1",
    "complete-reference-acceptance.ps1",
    "reference-renderer/renderer-contract.json",
    "reference-renderer/build-reference-renderer.ps1",
    "reference-renderer/ProjectSettings/ProjectVersion.txt",
    "reference-renderer/Packages/manifest.json",
)


class PersonReleaseStatusError(RuntimeError):
    pass


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PersonReleaseStatusError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonReleaseStatusError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PersonReleaseStatusError(f"{label} must be a JSON object: {path}")
    return value


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256.fullmatch(text):
        raise PersonReleaseStatusError(f"{label} is not a canonical SHA-256")
    return text


def _registered_fidelity_status(*, body_id: str, expected_sha: str) -> dict[str, Any]:
    package = body_library() / f"{body_id}.mrbody"
    unavailable = {
        "state": "unavailable",
        "high_fidelity_ready": False,
        "components": {},
        "blockers": [],
        "face_secondary": {
            "ready": False,
            "components": {},
            "blockers": [],
            "semantic_vertex_map_authority": "unavailable",
        },
        "human_review_required": True,
        "human_review": {
            "state": "unavailable",
            "passed": False,
            "reason": "High-fidelity package authority is unavailable.",
        },
        "production_ready": False,
        "reason": None,
    }
    if not package.is_file():
        return {
            **unavailable,
            "reason": "Canonical installed body package is unavailable for high-fidelity audit.",
        }
    try:
        audit = audit_high_fidelity_package(package)
    except (OSError, HighFidelityPackageAuditError) as exc:
        return {
            **unavailable,
            "reason": f"High-fidelity package evidence is unavailable or invalid: {exc}",
        }

    audited_body_id = str(audit.get("canonical_body_id") or "")
    if audited_body_id != body_id:
        raise PersonReleaseStatusError("high-fidelity package body id no longer matches the registered revision")
    audited_sha = _sha(audit.get("package_sha256"), "high-fidelity package SHA-256")
    if audited_sha != expected_sha:
        raise PersonReleaseStatusError("high-fidelity package SHA no longer matches the registered body revision")

    try:
        human_review = fidelity_human_review_status(package)
    except HighFidelityHumanReviewError as exc:
        raise PersonReleaseStatusError(f"high-fidelity human review authority is invalid: {exc}") from exc

    ready = bool(audit.get("high_fidelity_ready"))
    components = dict(audit.get("components") or {})
    blockers = list(audit.get("top_level_blockers") or [])
    face_ready = bool(audit.get("face_secondary_ready"))
    face_components = dict(audit.get("face_secondary_components") or {})
    face_blockers = list(audit.get("face_secondary_blockers") or [])
    review_passed = human_review.get("passed") is True
    return {
        "state": "ready" if ready else "blocked",
        "high_fidelity_ready": ready,
        "components": components,
        "blockers": blockers,
        "face_secondary": {
            "ready": face_ready,
            "components": face_components,
            "blockers": face_blockers,
            "semantic_vertex_map_authority": str(audit.get("semantic_vertex_map_authority") or "unavailable"),
        },
        "human_review_required": bool(audit.get("human_review_required", True)),
        "human_review": human_review,
        "production_ready": ready and review_passed,
        "reason": (
            None
            if ready and review_passed
            else (
                str(human_review.get("reason") or "Explicit high-fidelity human review is required.")
                if ready
                else "High-fidelity body components remain incomplete or unapproved."
            )
        ),
    }


def _platform_paths(acceptance_dir: Path, prefix: str) -> tuple[Path, Path]:
    dedicated = acceptance_dir / f"{prefix}-evidence" / f"{prefix}-probe.json"
    legacy = acceptance_dir / f"{prefix}-probe.json"
    if dedicated.is_file() and legacy.is_file():
        raise PersonReleaseStatusError(f"ambiguous {prefix} machine-probe layout")
    probe = dedicated if dedicated.is_file() else legacy
    attestation = acceptance_dir / f"bodyrig-renderer-acceptance-{prefix}.json"
    return probe, attestation


def _strict_platform_attestation(acceptance_dir: Path, *, prefix: str, platform: str) -> None:
    probe_path, attestation_path = _platform_paths(acceptance_dir, prefix)
    probe = _read_json(probe_path, f"{prefix} renderer machine probe")
    attestation = _read_json(attestation_path, f"{prefix} renderer attestation")

    if probe.get("format") != "bodyrig-renderer-probe" or probe.get("version") != 1 or probe.get("platform") != platform:
        raise PersonReleaseStatusError(f"{prefix} renderer machine probe format/platform mismatch")
    unity_platform = str(probe.get("unity_platform") or "")
    device_model = str(probe.get("device_model") or "")
    if platform == "windows-unity-univrm" and unity_platform != "WindowsPlayer":
        raise PersonReleaseStatusError("Windows physical acceptance was not observed in a built WindowsPlayer")
    if platform == "android-quest-class":
        if unity_platform != "Android":
            raise PersonReleaseStatusError("Quest physical acceptance was not observed in an Android runtime")
        if re.search(r"(?i)(quest|oculus)", device_model) is None:
            raise PersonReleaseStatusError("Quest physical acceptance does not identify Quest/Oculus hardware")

    if attestation.get("format") != "bodyrig-renderer-acceptance" or attestation.get("version") != 1:
        raise PersonReleaseStatusError(f"{prefix} renderer attestation format/version mismatch")
    if attestation.get("platform") != platform or attestation.get("result") != "pass":
        raise PersonReleaseStatusError(f"{prefix} renderer attestation is not a PASS")
    if attestation.get("attestation") != "operator-supplied":
        raise PersonReleaseStatusError(f"{prefix} renderer attestation is not operator-supplied")
    if attestation.get("machine_probe") is not True or attestation.get("deformation_probe") is not True:
        raise PersonReleaseStatusError(f"{prefix} renderer attestation lacks machine/deformation authority")
    if attestation.get("production_activation") is not False:
        raise PersonReleaseStatusError(f"{prefix} renderer attestation must remain non-activating")

    review = attestation.get("quality_review")
    if not isinstance(review, dict) or set(review) != QUALITY_REVIEW_FIELDS:
        raise PersonReleaseStatusError(f"{prefix} renderer attestation has no canonical structured human quality review")
    if review.get("revision") != "bodyrig-human-quality-v1":
        raise PersonReleaseStatusError(f"{prefix} renderer attestation uses an unsupported human quality review revision")
    for field in QUALITY_REVIEW_BOOLEAN_FIELDS:
        if review.get(field) is not True:
            raise PersonReleaseStatusError(f"{prefix} human quality review did not pass {field}")

    renderer = probe.get("active_renderer") if isinstance(probe.get("active_renderer"), dict) else {}
    exact_matches = {
        "renderer_name": renderer.get("name"),
        "renderer_version": renderer.get("version"),
        "unity_platform": probe.get("unity_platform"),
        "unity_version": probe.get("unity_version"),
        "graphics_device": probe.get("graphics_device"),
    }
    for field, expected in exact_matches.items():
        if not str(expected or "").strip() or str(attestation.get(field) or "") != str(expected):
            raise PersonReleaseStatusError(f"{prefix} renderer attestation no longer matches machine probe field {field}")
    quality_note = str(attestation.get("quality_note") or "").strip()
    if not quality_note:
        raise PersonReleaseStatusError(f"{prefix} renderer attestation has no operator quality note")
    if re.fullmatch(r"<[^>]+>", quality_note):
        raise PersonReleaseStatusError(f"{prefix} renderer attestation quality note is still a generated placeholder")


def _stages(gate: str, state: str) -> dict[str, str]:
    stages = {"gate_a": "pass", "windows": "pending", "quest": "pending", "release": "pending"}
    if state == "blocked":
        stages.update({"windows": "blocked", "quest": "blocked", "release": "blocked"})
    elif gate == "windows-probe":
        stages["windows"] = "machine-probe-required"
    elif gate == "windows-attestation":
        stages["windows"] = "human-review-required"
    elif gate == "quest-probe":
        stages["windows"] = "pass"
        stages["quest"] = "machine-probe-required"
    elif gate == "quest-attestation":
        stages["windows"] = "pass"
        stages["quest"] = "human-review-required"
    elif gate == "release":
        stages["windows"] = "pass"
        stages["quest"] = "pass"
        stages["release"] = "pass" if state == "complete" else "release-gate-required"
    else:
        raise PersonReleaseStatusError(f"unsupported physical acceptance gate: {gate}")
    return stages


def _operator_next_command(*, gate: str, state: str, acceptance_dir: Path, operator_root: Path) -> str | None:
    if state == "blocked":
        return None
    quoted_acceptance = f'"{acceptance_dir}"'

    def invoke(script_name: str) -> str:
        return f'& "{(operator_root / script_name).resolve()}"'

    if gate == "windows-probe":
        return f'{invoke("run-reference-windows-renderer-probe.ps1")} -AcceptanceDir {quoted_acceptance}'
    if gate == "windows-attestation":
        return (
            f'{invoke("record-reference-renderer-acceptance.ps1")} -AcceptanceDir {quoted_acceptance} '
            '-Platform "windows-unity-univrm" -ConfirmQualityChecklist '
            '-QualityNote "<your physical review>"'
        )
    if gate == "quest-probe":
        return f'{invoke("run-reference-quest-renderer-probe.ps1")} -AcceptanceDir {quoted_acceptance}'
    if gate == "quest-attestation":
        return (
            f'{invoke("record-reference-renderer-acceptance.ps1")} -AcceptanceDir {quoted_acceptance} '
            '-Platform "android-quest-class" -ConfirmQualityChecklist '
            '-QualityNote "<your physical headset review>"'
        )
    if gate == "release":
        if state == "complete":
            return None
        if state == "ready":
            return f'{invoke("complete-reference-acceptance.ps1")} -AcceptanceDir {quoted_acceptance}'
    raise PersonReleaseStatusError(f"unsupported actionable physical acceptance state: {state}/{gate}")


def _operator_checkout_authority(
    *,
    expected_revision: str,
    authority: Mapping[str, Any] | None,
) -> tuple[bool, Path | None, str | None, dict[str, Any]]:
    if authority is None:
        from .ui_jobs import operator_checkout_status

        authority = operator_checkout_status()
    value = dict(authority)
    if value.get("ok") is not True:
        return False, None, str(value.get("reason") or "BodyRig operator checkout is not authoritative"), value
    actual_revision = str(value.get("revision") or "").strip().lower()
    if actual_revision != str(expected_revision or "").strip().lower():
        return (
            False,
            None,
            f"BodyRig operator checkout revision {actual_revision or '?'} does not match acceptance revision {expected_revision or '?'}",
            value,
        )
    root_raw = str(value.get("root") or "").strip()
    if not root_raw:
        return False, None, "BodyRig operator checkout authority has no checkout root", value
    root = Path(root_raw).expanduser().resolve()
    missing = [name for name in _REFERENCE_OPERATOR_FILES if not (root / name).is_file()]
    if missing:
        return False, None, "BodyRig operator checkout is missing canonical reference dependencies: " + ", ".join(missing), value
    return True, root, None, value


def inspect_candidate_release_status(
    jobs: Iterable[Mapping[str, Any]],
    *,
    person_id: str,
    body_revision: str,
    body_id: str,
    package_sha256: str,
    operator_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    expected_sha = _sha(package_sha256, "registered body package_sha256")
    fidelity = _registered_fidelity_status(body_id=body_id, expected_sha=expected_sha)
    candidates = [
        dict(job)
        for job in jobs
        if job.get("format") == "bodyrig-ui-job"
        and job.get("version") == 1
        and job.get("kind") == "body-build"
        and job.get("person_id") == person_id
        and job.get("body_revision") == body_revision
    ]
    candidates.sort(key=lambda item: str(item.get("created_utc") or ""), reverse=True)
    if not candidates:
        return {
            "format": FORMAT,
            "version": VERSION,
            "state": "unavailable",
            "gate": "origin-evidence",
            "person_id": person_id,
            "body_revision": body_revision,
            "body_id": body_id,
            "package_sha256": expected_sha,
            "bodyrig_revision": None,
            "production_activation": False,
            "production_ready": False,
            "fidelity": fidelity,
            "message": "No succeeded BodyRig UI physical-build evidence chain is available for this body revision.",
            "next_command": None,
            "operator_checkout": {"required": False, "ready": False, "reason": "No originating physical-build chain"},
            "stages": {"gate_a": "unknown", "windows": "unknown", "quest": "unknown", "release": "unknown"},
        }

    job = candidates[0]
    if job.get("status") != "succeeded":
        raise PersonReleaseStatusError("originating body-build job is not a succeeded physical candidate")
    if str(job.get("canonical_body_id") or "") != str(body_id):
        raise PersonReleaseStatusError("originating body-build canonical body id no longer matches the registered revision")
    acceptance_raw = str(job.get("acceptance_dir") or "").strip()
    if not acceptance_raw:
        raise PersonReleaseStatusError("originating body-build job has no acceptance directory")
    acceptance_dir = Path(acceptance_raw).expanduser().resolve()

    try:
        status = apply_reference_policy(inspect_acceptance_dir(acceptance_dir))
    except AcceptanceStatusError as exc:
        raise PersonReleaseStatusError(f"physical acceptance evidence is invalid: {exc}") from exc

    if status.body_id != body_id:
        raise PersonReleaseStatusError("physical acceptance body id no longer matches the registered revision")
    gate_a = _read_json(acceptance_dir / "bodyrig-acceptance.json", "Gate A acceptance report")
    package = gate_a.get("package") if isinstance(gate_a.get("package"), dict) else {}
    if str(package.get("body_id") or "") != body_id:
        raise PersonReleaseStatusError("Gate A body id no longer matches the registered revision")
    if _sha(package.get("package_sha256"), "Gate A package SHA-256") != expected_sha:
        raise PersonReleaseStatusError("Gate A package SHA no longer matches the registered body revision")

    if status.state != "blocked" and status.gate in {"quest-probe", "quest-attestation", "release"}:
        _strict_platform_attestation(acceptance_dir, prefix="windows", platform="windows-unity-univrm")
    if status.state != "blocked" and status.gate == "release":
        _strict_platform_attestation(acceptance_dir, prefix="quest", platform="android-quest-class")

    payload = asdict(status)
    production = payload["state"] == "complete" and payload["gate"] == "release"
    fidelity_ready = fidelity.get("high_fidelity_ready") is True
    fidelity_review_ready = (fidelity.get("human_review") or {}).get("passed") is True
    production_ready = production and fidelity_ready and fidelity_review_ready
    operator_required = not production and payload["state"] not in {"blocked", "unavailable"}
    operator_ready = False
    operator_root: Path | None = None
    operator_reason: str | None = None
    authority_value: dict[str, Any] = {}
    if operator_required:
        operator_ready, operator_root, operator_reason, authority_value = _operator_checkout_authority(
            expected_revision=str(payload["bodyrig_revision"] or ""),
            authority=operator_authority,
        )
    elif payload["state"] == "blocked":
        operator_reason = "Physical acceptance is blocked before an operator command can be authorized"
    else:
        operator_reason = None

    message = str(payload["message"])
    if operator_required and not operator_ready and operator_reason:
        message += f" Executable next command withheld: {operator_reason}."
    if production and not fidelity_ready:
        message += " Physical release is complete, but Person Studio production remains locked by high-fidelity component evidence."
    elif production and not fidelity_review_ready:
        message += " Physical release and high-fidelity components are complete, but explicit high-fidelity human review is still required."
    next_command = None
    if operator_ready and operator_root is not None:
        next_command = _operator_next_command(
            gate=payload["gate"],
            state=payload["state"],
            acceptance_dir=acceptance_dir,
            operator_root=operator_root,
        )

    return {
        "format": FORMAT,
        "version": VERSION,
        "state": payload["state"],
        "gate": payload["gate"],
        "person_id": person_id,
        "body_revision": body_revision,
        "body_id": body_id,
        "package_sha256": expected_sha,
        "bodyrig_revision": payload["bodyrig_revision"],
        "production_activation": production,
        "production_ready": production_ready,
        "fidelity": fidelity,
        "message": message,
        "next_command": next_command,
        "operator_checkout": {
            "required": operator_required,
            "ready": operator_ready,
            "reason": operator_reason,
            "revision": authority_value.get("revision"),
            "root": authority_value.get("root") if operator_ready else None,
        },
        "stages": _stages(payload["gate"], payload["state"]),
    }


# High-fidelity Person Studio authority router. The legacy implementation above
# remains the exact fallback when no continuation exists for the body revision.
_legacy_inspect_candidate_release_status = inspect_candidate_release_status

from .high_fidelity_preview_jobs import HighFidelityPreviewError, manager as high_fidelity_preview_manager
from .high_fidelity_release_readiness import HighFidelityReleaseReadinessError, inspect_release_readiness
from .high_fidelity_release_readiness_cli import (
    HighFidelityReleaseReadinessCliError,
    bind_operator_checkout as bind_high_fidelity_operator_checkout,
)


def _high_fidelity_fidelity(readiness: Mapping[str, Any]) -> dict[str, Any]:
    audit = readiness.get("final_audit") if isinstance(readiness.get("final_audit"), Mapping) else {}
    components = dict(readiness.get("components") or {})
    complete = readiness.get("component_package_complete") is True
    blockers = [name for name, state in components.items() if state != "complete"]
    face_components = dict(audit.get("face_secondary_components") or {})
    face_ready = bool(audit.get("face_secondary_ready")) if audit else components.get("face_secondary") == "complete"
    face_blockers = list(audit.get("face_secondary_blockers") or []) if audit else []
    human_complete = readiness.get("high_fidelity_human_review_complete") is True
    review_gate = next(
        (
            gate
            for gate in readiness.get("gates") or []
            if isinstance(gate, Mapping) and gate.get("id") == "high_fidelity_human_review"
        ),
        None,
    )
    review_reason = str(review_gate.get("reason") or "") if isinstance(review_gate, Mapping) else ""
    if human_complete:
        human_review = {
            "state": "pass",
            "passed": True,
            "reason": None,
            "policy_revision": "bodyrig-high-fidelity-human-review-v1",
        }
    else:
        next_gate = readiness.get("next_gate") if isinstance(readiness.get("next_gate"), Mapping) else {}
        next_id = str(next_gate.get("gate") or "")
        required = next_id in {"high_fidelity_human_review", "high_fidelity_human_review_recovery"}
        human_review = {
            "state": "required" if required else ("blocked" if complete else "unavailable"),
            "passed": False,
            "reason": review_reason or str(next_gate.get("reason") or "") or "High-fidelity human review is not yet authoritative.",
        }
    return {
        "state": "ready" if complete else ("blocked" if readiness.get("state") == "blocked" else "unavailable"),
        "high_fidelity_ready": complete,
        "components": components,
        "blockers": blockers,
        "face_secondary": {
            "ready": face_ready,
            "components": face_components,
            "blockers": face_blockers,
            "semantic_vertex_map_authority": str(audit.get("semantic_vertex_map_authority") or "unavailable"),
        },
        "human_review_required": not human_complete,
        "human_review": human_review,
        "production_ready": readiness.get("production_ready") is True,
        "reason": None if readiness.get("production_ready") is True else str(
            (readiness.get("next_gate") or {}).get("reason") if isinstance(readiness.get("next_gate"), Mapping) else ""
        ) or "High-fidelity release authority is not production-ready.",
    }


def _high_fidelity_stage_map(readiness: Mapping[str, Any]) -> dict[str, str]:
    gate_states = {
        str(gate.get("id")): str(gate.get("state"))
        for gate in readiness.get("gates") or []
        if isinstance(gate, Mapping)
    }
    stages = {
        "gate_a": "pass" if gate_states.get("physical_gate_a") == "pass" else "pending",
        "windows": "pass" if gate_states.get("physical_windows_acceptance") == "pass" else "pending",
        "quest": "pass" if gate_states.get("physical_quest_acceptance") == "pass" else "pending",
        "release": "pass" if gate_states.get("final_release") == "pass" else "pending",
    }
    if readiness.get("production_ready") is True and readiness.get("production_activation") is True:
        return {key: "pass" for key in stages}
    next_gate = readiness.get("next_gate") if isinstance(readiness.get("next_gate"), Mapping) else {}
    next_id = str(next_gate.get("gate") or "")
    command = str(next_gate.get("command") or "")
    if next_id == "physical_windows_acceptance":
        stages["gate_a"] = "pass"
        stages["windows"] = "human-review-required" if "record-reference-renderer-acceptance.ps1" in command else "machine-probe-required"
    elif next_id == "physical_quest_acceptance":
        stages["gate_a"] = "pass"
        stages["windows"] = "pass"
        stages["quest"] = "human-review-required" if "record-reference-renderer-acceptance.ps1" in command else "machine-probe-required"
    elif next_id == "final_release":
        stages.update({"gate_a": "pass", "windows": "pass", "quest": "pass", "release": "release-gate-required"})
    if readiness.get("state") == "blocked":
        for key, value in list(stages.items()):
            if value == "pending":
                stages[key] = "blocked"
    return stages


def _high_fidelity_state_gate(readiness: Mapping[str, Any]) -> tuple[str, str]:
    if readiness.get("production_ready") is True and readiness.get("production_activation") is True:
        return "complete", "release"
    next_gate = readiness.get("next_gate") if isinstance(readiness.get("next_gate"), Mapping) else {}
    next_id = str(next_gate.get("gate") or "")
    command = str(next_gate.get("command") or "")
    if next_id == "physical_windows_acceptance":
        return ("human-review", "windows-attestation") if "record-reference-renderer-acceptance.ps1" in command else ("ready", "windows-probe")
    if next_id == "physical_quest_acceptance":
        return ("human-review", "quest-attestation") if "record-reference-renderer-acceptance.ps1" in command else ("ready", "quest-probe")
    if next_id == "final_release":
        return "ready", "release"
    if next_id == "physical_gate_a":
        return "ready", "high-fidelity-gate-a"
    if next_id in {"high_fidelity_human_review", "high_fidelity_human_review_recovery"}:
        return "human-review", "high-fidelity-human-review"
    if readiness.get("state") == "blocked":
        return "blocked", "high-fidelity-continuation"
    return "incomplete", "high-fidelity-continuation"


def _bind_high_fidelity_readiness(
    readiness: dict[str, Any],
    authority: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    next_gate = readiness.get("next_gate") if isinstance(readiness.get("next_gate"), Mapping) else None
    command = str(next_gate.get("command") or "").strip() if next_gate else ""
    if readiness.get("production_ready") is True and readiness.get("production_activation") is True:
        return readiness, {"required": False, "ready": False, "reason": None, "revision": None, "root": None}
    if not command:
        return readiness, {
            "required": bool(next_gate),
            "ready": False,
            "reason": str(next_gate.get("reason") or "No executable operator command is currently authorized.") if next_gate else None,
            "revision": None,
            "root": None,
        }
    if authority is None:
        from .ui_jobs import operator_checkout_status

        authority = operator_checkout_status()
    authority_value = dict(authority)
    root_raw = str(authority_value.get("root") or "").strip()
    if authority_value.get("ok") is not True or not root_raw:
        value = dict(readiness)
        next_value = dict(next_gate)
        next_value["command"] = None
        value["next_gate"] = next_value
        return value, {
            "required": True,
            "ready": False,
            "reason": str(authority_value.get("reason") or "BodyRig operator checkout is not authoritative"),
            "revision": authority_value.get("revision"),
            "root": None,
        }
    root = Path(root_raw).expanduser().resolve()
    try:
        bound = bind_high_fidelity_operator_checkout(readiness, root)
    except (OSError, ValueError, HighFidelityReleaseReadinessCliError) as exc:
        value = dict(readiness)
        next_value = dict(next_gate)
        next_value["command"] = None
        value["next_gate"] = next_value
        return value, {
            "required": True,
            "ready": False,
            "reason": str(exc),
            "revision": authority_value.get("revision"),
            "root": None,
        }
    checkout = bound.get("operator_checkout") if isinstance(bound.get("operator_checkout"), Mapping) else {}
    authorized = checkout.get("authorized") is True
    return bound, {
        "required": True,
        "ready": authorized,
        "reason": None if authorized else str(checkout.get("reason") or "operator checkout is not authorized"),
        "revision": checkout.get("revision"),
        "root": checkout.get("root") if authorized else None,
    }


def _high_fidelity_person_release_status(
    jobs: Iterable[Mapping[str, Any]],
    *,
    preview: Mapping[str, Any],
    person_id: str,
    body_revision: str,
    body_id: str,
    registered_package_sha256: str,
    operator_authority: Mapping[str, Any] | None,
) -> dict[str, Any]:
    preview_job_id = str(preview.get("job_id") or "")
    body_job_id = str(preview.get("body_job_id") or "")
    if str(preview.get("person_id") or "") != person_id or str(preview.get("body_revision") or "") != body_revision:
        raise PersonReleaseStatusError("high-fidelity preview no longer matches the requested person/body revision")
    if str(preview.get("canonical_body_id") or "") != body_id:
        raise PersonReleaseStatusError("high-fidelity preview body identity no longer matches the registered revision")
    candidates = [dict(job) for job in jobs]
    source = next((job for job in candidates if str(job.get("job_id") or "") == body_job_id), None)
    if source is None:
        raise PersonReleaseStatusError("high-fidelity preview source body-build job is unavailable from Person Studio authority")
    if source.get("kind") != "body-build" or source.get("status") != "succeeded":
        raise PersonReleaseStatusError("high-fidelity preview source body-build job is not a succeeded physical build")
    if str(source.get("canonical_body_id") or "") != body_id or str(source.get("body_revision") or "") != body_revision:
        raise PersonReleaseStatusError("high-fidelity preview source body-build authority no longer matches the registered revision")
    try:
        readiness = inspect_release_readiness(preview_job_id)
    except (OSError, ValueError, HighFidelityReleaseReadinessError) as exc:
        raise PersonReleaseStatusError(f"high-fidelity release readiness is invalid: {exc}") from exc
    readiness, operator = _bind_high_fidelity_readiness(dict(readiness), operator_authority)
    fidelity = _high_fidelity_fidelity(readiness)
    state, gate = _high_fidelity_state_gate(readiness)
    next_gate = readiness.get("next_gate") if isinstance(readiness.get("next_gate"), Mapping) else {}
    next_command = str(next_gate.get("command") or "").strip() or None
    package_sha = str(readiness.get("current_package_sha256") or "").strip().lower()
    if package_sha:
        package_sha = _sha(package_sha, "high-fidelity promoted package SHA-256")
    else:
        package_sha = registered_package_sha256
    accepted_revision = None
    for item in readiness.get("gates") or []:
        if not isinstance(item, Mapping) or item.get("id") != "physical_gate_a" or item.get("state") != "pass":
            continue
        evidence = item.get("evidence") if isinstance(item.get("evidence"), Mapping) else {}
        value = str(evidence.get("bodyrig_revision") or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{40}", value):
            accepted_revision = value
            break
    if accepted_revision is None:
        value = str(preview.get("bodyrig_revision") or "").strip().lower()
        accepted_revision = value if re.fullmatch(r"[0-9a-f]{40}", value) else None
    if readiness.get("production_ready") is True and readiness.get("production_activation") is True:
        message = "Fresh high-fidelity promoted-package Windows + Quest release authority is production-ready."
    else:
        reason = str(next_gate.get("reason") or "").strip()
        if not reason:
            invalid = [
                str(item.get("reason") or "").strip()
                for item in readiness.get("gates") or []
                if isinstance(item, Mapping) and item.get("state") in {"blocked", "invalid"}
            ]
            reason = invalid[-1] if invalid else str(readiness.get("state") or "high-fidelity release is incomplete")
        message = f"High-fidelity continuation authority selected. {reason}"
    return {
        "format": FORMAT,
        "version": VERSION,
        "state": state,
        "gate": gate,
        "person_id": person_id,
        "body_revision": body_revision,
        "body_id": body_id,
        "package_sha256": package_sha,
        "registered_package_sha256": registered_package_sha256,
        "high_fidelity_preview_job_id": preview_job_id,
        "bodyrig_revision": accepted_revision,
        "production_activation": readiness.get("production_activation") is True,
        "production_ready": readiness.get("production_ready") is True,
        "fidelity": fidelity,
        "message": message,
        "next_command": next_command,
        "operator_checkout": operator,
        "stages": _high_fidelity_stage_map(readiness),
    }


def inspect_candidate_release_status(
    jobs: Iterable[Mapping[str, Any]],
    *,
    person_id: str,
    body_revision: str,
    body_id: str,
    package_sha256: str,
    operator_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    expected_sha = _sha(package_sha256, "registered body package_sha256")
    try:
        preview = high_fidelity_preview_manager.latest_for_revision(person_id, body_revision)
    except HighFidelityPreviewError:
        return _legacy_inspect_candidate_release_status(
            jobs,
            person_id=person_id,
            body_revision=body_revision,
            body_id=body_id,
            package_sha256=expected_sha,
            operator_authority=operator_authority,
        )
    return _high_fidelity_person_release_status(
        jobs,
        preview=preview,
        person_id=person_id,
        body_revision=body_revision,
        body_id=body_id,
        registered_package_sha256=expected_sha,
        operator_authority=operator_authority,
    )
