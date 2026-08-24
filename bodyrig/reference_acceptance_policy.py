from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .acceptance_status import AcceptanceStatus


LEGACY_RENDERER_EVIDENCE = (
    "windows-probe.json",
    "windows-deformation-probe.json",
    "quest-probe.json",
    "quest-deformation-probe.json",
)
CONTRACT_PATH = Path(__file__).resolve().parents[1] / "reference-renderer" / "renderer-contract.json"


def _blocked(status: AcceptanceStatus, gate: str, message: str) -> AcceptanceStatus:
    return replace(status, state="blocked", gate=gate, message=message, next_command=None)


def _read_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _load_contract() -> dict[str, Any] | None:
    contract = _read_object(CONTRACT_PATH)
    if contract is None:
        return None
    expected_fields = {
        "format",
        "version",
        "renderer_name",
        "renderer_version",
        "unity_editor_version",
        "univrm_version",
        "application_id",
        "deformation_sequence_revision",
    }
    if set(contract) != expected_fields:
        return None
    if contract.get("format") != "bodyrig-reference-renderer-contract" or contract.get("version") != 1:
        return None
    for field in expected_fields - {"format", "version"}:
        if not str(contract.get(field) or "").strip():
            return None
    return contract


def _reference_mismatch(acceptance_dir: Path, contract: dict[str, Any]) -> str | None:
    for prefix in ("windows", "quest"):
        evidence_dir = acceptance_dir / f"{prefix}-evidence"
        probe_path = evidence_dir / f"{prefix}-probe.json"
        deformation_path = evidence_dir / f"{prefix}-deformation-probe.json"
        attestation_path = acceptance_dir / f"bodyrig-renderer-acceptance-{prefix}.json"

        probe = _read_object(probe_path)
        if probe is not None:
            renderer = probe.get("active_renderer") if isinstance(probe.get("active_renderer"), dict) else {}
            if renderer.get("name") != contract["renderer_name"]:
                return f"{prefix} machine probe renderer name does not match renderer-contract.json."
            if renderer.get("version") != contract["renderer_version"]:
                return f"{prefix} machine probe renderer version does not match renderer-contract.json."
            if probe.get("unity_version") != contract["unity_editor_version"]:
                return f"{prefix} machine probe Unity version does not match renderer-contract.json."

        deformation = _read_object(deformation_path)
        if deformation is not None:
            if deformation.get("unity_version") != contract["unity_editor_version"]:
                return f"{prefix} deformation probe Unity version does not match renderer-contract.json."
            if deformation.get("sequence_revision") != contract["deformation_sequence_revision"]:
                return f"{prefix} deformation sequence does not match renderer-contract.json."

        attestation = _read_object(attestation_path)
        if attestation is not None:
            if attestation.get("renderer_name") != contract["renderer_name"]:
                return f"{prefix} human attestation renderer name does not match renderer-contract.json."
            if attestation.get("renderer_version") != contract["renderer_version"]:
                return f"{prefix} human attestation renderer version does not match renderer-contract.json."
            if attestation.get("unity_version") != contract["unity_editor_version"]:
                return f"{prefix} human attestation Unity version does not match renderer-contract.json."
            if attestation.get("deformation_sequence_revision") != contract["deformation_sequence_revision"]:
                return f"{prefix} human attestation deformation sequence does not match renderer-contract.json."
    return None


def apply_reference_policy(status: AcceptanceStatus) -> AcceptanceStatus:
    """Apply the canonical BodyRig V1 reference-renderer policy to generic status.

    The generic status reader intentionally remains able to inspect legacy root-file
    renderer evidence. The canonical reference-renderer path, however, only releases
    dedicated transactional ``windows-evidence/`` and ``quest-evidence/`` bundles.
    It also requires every physical evidence layer to match the single renderer
    contract before more physical work or human review is proposed.

    Already-complete historical release artifacts remain readable; this policy does
    not retroactively rewrite or invalidate an existing activating release artifact.
    """

    if not status.acceptance_dir or status.state == "complete":
        return status

    acceptance_dir = Path(status.acceptance_dir)
    present = tuple(name for name in LEGACY_RENDERER_EVIDENCE if (acceptance_dir / name).is_file())
    if present:
        files = ", ".join(present)
        return _blocked(
            status,
            "reference-layout",
            "Legacy root renderer evidence is readable but cannot continue through the canonical "
            "BodyRig V1 reference-renderer release policy. Start a fresh Gate A acceptance bundle "
            "from the original physical-clone PASS session and use the transactional reference "
            f"wrappers. Legacy files present: {files}.",
        )

    has_reference_evidence = any(
        (acceptance_dir / f"{prefix}-evidence").exists()
        or (acceptance_dir / f"bodyrig-renderer-acceptance-{prefix}.json").exists()
        for prefix in ("windows", "quest")
    )
    if not has_reference_evidence:
        return status

    contract = _load_contract()
    if contract is None:
        return _blocked(
            status,
            "reference-contract",
            f"Canonical reference renderer contract is unavailable or invalid: {CONTRACT_PATH}",
        )

    mismatch = _reference_mismatch(acceptance_dir, contract)
    if mismatch:
        return _blocked(
            status,
            "reference-contract",
            f"Reference renderer evidence is not canonical: {mismatch} Re-run the affected physical renderer gate from the exact accepted BodyRig revision.",
        )
    return status
