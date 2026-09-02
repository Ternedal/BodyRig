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

FORMAT = "bodyrig-person-release-status"
VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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
    if not str(attestation.get("quality_note") or "").strip():
        raise PersonReleaseStatusError(f"{prefix} renderer attestation has no operator quality note")


def _stages(gate: str, state: str) -> dict[str, str]:
    stages = {"gate_a": "pass", "windows": "pending", "quest": "pending", "release": "pending"}
    if gate == "windows-probe":
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


def _operator_next_command(*, gate: str, state: str, acceptance_dir: Path) -> str | None:
    quoted = f'"{acceptance_dir}"'
    if gate == "windows-probe":
        return f'.\\run-reference-windows-renderer-probe.ps1 -AcceptanceDir {quoted}'
    if gate == "windows-attestation":
        return (
            f'.\\record-reference-renderer-acceptance.ps1 -AcceptanceDir {quoted} '
            '-Platform "windows-unity-univrm" -ConfirmQualityChecklist '
            '-QualityNote "<your physical review>"'
        )
    if gate == "quest-probe":
        return f'.\\run-reference-quest-renderer-probe.ps1 -AcceptanceDir {quoted}'
    if gate == "quest-attestation":
        return (
            f'.\\record-reference-renderer-acceptance.ps1 -AcceptanceDir {quoted} '
            '-Platform "android-quest-class" -ConfirmQualityChecklist '
            '-QualityNote "<your physical headset review>"'
        )
    if gate == "release":
        if state == "complete":
            return None
        if state == "ready":
            return f'.\\complete-reference-acceptance.ps1 -AcceptanceDir {quoted}'
    raise PersonReleaseStatusError(f"unsupported actionable physical acceptance state: {state}/{gate}")


def inspect_candidate_release_status(
    jobs: Iterable[Mapping[str, Any]],
    *,
    person_id: str,
    body_revision: str,
    body_id: str,
    package_sha256: str,
) -> dict[str, Any]:
    expected_sha = _sha(package_sha256, "registered body package_sha256")
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
            "message": "No succeeded BodyRig UI physical-build evidence chain is available for this body revision.",
            "next_command": None,
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
        status = inspect_acceptance_dir(acceptance_dir)
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

    if status.gate in {"quest-probe", "quest-attestation", "release"}:
        _strict_platform_attestation(acceptance_dir, prefix="windows", platform="windows-unity-univrm")
    if status.gate == "release":
        _strict_platform_attestation(acceptance_dir, prefix="quest", platform="android-quest-class")

    payload = asdict(status)
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
        "production_activation": payload["state"] == "complete" and payload["gate"] == "release",
        "message": payload["message"],
        "next_command": _operator_next_command(
            gate=payload["gate"],
            state=payload["state"],
            acceptance_dir=acceptance_dir,
        ),
        "stages": _stages(payload["gate"], payload["state"]),
    }
