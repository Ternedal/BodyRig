from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .acceptance_status import AcceptanceStatusError, inspect_acceptance_dir
from .acceptance_status_cli import _git_checkout_state, _operator_command, _resolve_operator_root
from .digital_twin_platform_acceptance import (
    DigitalTwinPlatformAcceptanceError,
    _composition_bundle,
    inspect_digital_twin_platform_acceptance,
)
from .digital_twin_release import (
    DigitalTwinReleaseError,
    _authority_from_chain,
    _chain_evidence,
    read_release,
    release_dir,
)
from .digital_twin_status import DigitalTwinStatusError, inspect_digital_twin_status
from .reference_acceptance_policy import apply_reference_policy

FORMAT = "bodyrig-digital-twin-operator-status"
VERSION = 1
_OPERATOR_SCRIPTS = (
    "run-windows-digital-twin-probe.ps1",
    "run-quest-digital-twin-probe.ps1",
    "finalize-digital-twin-release.ps1",
)
_M5_SCRIPT = {
    "windows-unity-univrm": "run-windows-digital-twin-probe.ps1",
    "android-quest-class": "run-quest-digital-twin-probe.ps1",
}


class DigitalTwinOperatorStatusError(RuntimeError):
    pass


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DigitalTwinOperatorStatusError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise DigitalTwinOperatorStatusError(f"{label} must be a JSON object: {path}")
    return value


def _ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _script_invocation(name: str, root: Path | None) -> str:
    if root is None:
        return f".\\{name}"
    return f"& {_ps_quote((root / name).resolve())}"


def _m5_command(platform: str, *, root: Path | None, composition_dir: Path, acceptance_dir: Path) -> str:
    try:
        script = _M5_SCRIPT[platform]
    except KeyError as exc:
        raise DigitalTwinOperatorStatusError(f"unsupported actionable M5 platform: {platform}") from exc
    return (
        f"{_script_invocation(script, root)} "
        f"-AcceptanceDir {_ps_quote(acceptance_dir)} "
        f"-CompositionAuthorityDir {_ps_quote(composition_dir)}"
    )


def _m6_command(*, root: Path | None, composition_dir: Path, acceptance_dir: Path) -> str:
    return (
        f"{_script_invocation('finalize-digital-twin-release.ps1', root)} "
        f"-CompositionAuthorityDir {_ps_quote(composition_dir)} "
        f"-AcceptanceDir {_ps_quote(acceptance_dir)}"
    )


def _frozen_m4_inputs(directory: Path) -> dict[str, dict[str, Any]]:
    return {
        "assembly": _json(directory / "person-assembly-receipt.json", "frozen Person assembly receipt"),
        "body_release": _json(directory / "body-release-status.json", "frozen body release status"),
        "hands_nails": _json(directory / "hands-feet-nails-authority.json", "frozen M2 hands/feet/nails authority"),
        "wardrobe": _json(directory / "wardrobe-authority.json", "frozen M3 wardrobe authority"),
    }


def _operator_root(value: str | Path | None) -> Path | None:
    explicit = Path(value) if value is not None else None
    try:
        root = _resolve_operator_root(explicit)
    except AcceptanceStatusError as exc:
        raise DigitalTwinOperatorStatusError(str(exc)) from exc
    if root is None:
        return None
    missing = tuple(name for name in _OPERATOR_SCRIPTS if not (root / name).is_file())
    if missing:
        if explicit is None:
            return None
        raise DigitalTwinOperatorStatusError(
            "BodyRig operator root is missing digital-twin operator dependencies: " + ", ".join(missing)
        )
    return root


def _bind_actionable_checkout(
    *,
    root: Path | None,
    expected_revision: str,
    state: str,
    next_gate: str,
    next_command: str | None,
    message: str,
) -> tuple[str, str, str | None, str]:
    if state != "required" or next_command is None:
        return state, next_gate, next_command, message
    if root is None:
        return (
            state,
            next_gate,
            None,
            message
            + " Inspection-only: no complete BodyRig Git checkout is available, so no executable next command is authorized.",
        )
    try:
        head, clean = _git_checkout_state(root)
    except AcceptanceStatusError as exc:
        raise DigitalTwinOperatorStatusError(str(exc)) from exc
    if head != expected_revision:
        return (
            "blocked",
            "operator-checkout",
            None,
            f"BodyRig operator checkout revision {head} does not match digital-twin evidence revision {expected_revision}. "
            "Checkout the exact evidence revision before continuing.",
        )
    if not clean:
        return (
            "blocked",
            "operator-checkout",
            None,
            f"BodyRig operator checkout is dirty. Digital-twin physical/release commands require exact clean revision {head}.",
        )
    return state, next_gate, next_command, message


def inspect_operator_status(
    *,
    composition_authority_dir: str | Path,
    acceptance_dir: str | Path,
    library_root: str | Path,
    operator_root: str | Path | None = None,
) -> dict[str, Any]:
    """Read-only operator view of the exact M4 -> physical -> M5 -> M6 chain.

    The function never writes evidence. It revalidates the live accepted package,
    computes the current M5 state and, when deterministic M6 evidence exists,
    performs full canonical M6 readback before reporting the twin complete.
    Executable next commands are exposed only from the exact clean evidence checkout.
    """

    composition_dir = Path(composition_authority_dir).expanduser().resolve()
    acceptance = Path(acceptance_dir).expanduser().resolve()
    library = Path(library_root).expanduser().resolve()
    if not composition_dir.is_dir():
        raise DigitalTwinOperatorStatusError(f"M4 composition authority directory not found: {composition_dir}")
    if not acceptance.is_dir():
        raise DigitalTwinOperatorStatusError(f"canonical physical acceptance directory not found: {acceptance}")

    authority_hint = _json(composition_dir / "authority.json", "M4 composition authority")
    body_id = str(authority_hint.get("body_id") or "").strip()
    if not body_id:
        raise DigitalTwinOperatorStatusError("M4 composition authority has no body id")
    package_path = acceptance / f"{body_id}.mrbody"
    if not package_path.is_file():
        raise DigitalTwinOperatorStatusError(f"exact accepted .mrbody is missing: {package_path}")

    try:
        composition, _composition_raw, _probe, _probe_raw = _composition_bundle(
            composition_dir,
            package_path=package_path,
        )
        m5_status = inspect_digital_twin_platform_acceptance(
            composition_authority_dir=composition_dir,
            acceptance_dir=acceptance,
        )
    except DigitalTwinPlatformAcceptanceError as exc:
        raise DigitalTwinOperatorStatusError(str(exc)) from exc

    revision = str(composition.get("bodyrig_revision") or "").strip().lower()
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise DigitalTwinOperatorStatusError("M4 composition authority has no canonical BodyRig revision")

    frozen = _frozen_m4_inputs(composition_dir)
    try:
        physical = apply_reference_policy(inspect_acceptance_dir(acceptance))
    except AcceptanceStatusError as exc:
        raise DigitalTwinOperatorStatusError(f"canonical physical acceptance is invalid: {exc}") from exc

    root = _operator_root(operator_root)
    final_release_authority: dict[str, Any] | None = None
    expected_release_id: str | None = None
    final_release_path: str | None = None
    final_release_error: str | None = None

    physical_complete = physical.state == "complete" and physical.gate == "release"
    if physical_complete and m5_status.get("m5_ready") is True:
        try:
            chain = _chain_evidence(
                composition_authority_dir=composition_dir,
                acceptance_dir=acceptance,
                expected_bodyrig_revision=revision,
            )
            candidate = _authority_from_chain(chain)
            expected_release_id = str(candidate["release_id"])
            candidate_dir = release_dir(
                library,
                person_id=str(candidate["person_id"]),
                person_revision=str(candidate["person_revision"]),
                release_id=expected_release_id,
            )
            final_release_path = str(candidate_dir / "authority.json")
            if candidate_dir.exists():
                final_release_authority = read_release(
                    library,
                    person_id=str(candidate["person_id"]),
                    person_revision=str(candidate["person_revision"]),
                    release_id=expected_release_id,
                    composition_authority_dir=composition_dir,
                    acceptance_dir=acceptance,
                )
        except DigitalTwinReleaseError as exc:
            final_release_error = str(exc)

    try:
        twin = inspect_digital_twin_status(
            assembly_receipt=frozen["assembly"],
            body_release_status=frozen["body_release"],
            hands_nails_authority=frozen["hands_nails"],
            wardrobe_authority=frozen["wardrobe"],
            embodiment_authority=composition,
            platform_acceptance_status=m5_status,
            final_release_authority=final_release_authority,
        )
    except DigitalTwinStatusError as exc:
        raise DigitalTwinOperatorStatusError(str(exc)) from exc

    next_command: str | None = None
    next_gate = str(twin.get("next_gate") or "")
    state = "complete" if twin.get("digital_twin_ready") is True else "required"
    message = str(twin.get("message") or "")

    if final_release_error is not None:
        state = "invalid"
        next_command = None
        message = f"Canonical M6 readback/preflight is invalid: {final_release_error}"
    elif not physical_complete:
        state = "invalid" if physical.state == "blocked" else "required"
        next_gate = f"body_physical:{physical.gate}"
        if state == "required" and root is not None:
            physical = _operator_command(physical, root)
            next_command = physical.next_command
        message = physical.message
    elif m5_status.get("m5_ready") is not True:
        m5_next = str(m5_status.get("next_gate") or "")
        platform = m5_next.split(":", 1)[1] if m5_next.startswith("m5:") else ""
        platform_status = (m5_status.get("platforms") or {}).get(platform)
        platform_state = str(platform_status.get("state") or "") if isinstance(platform_status, dict) else ""
        next_gate = "digital_twin_platform_acceptance"
        if platform_state == "required" and platform in _M5_SCRIPT:
            state = "required"
            next_command = _m5_command(
                platform,
                root=root,
                composition_dir=composition_dir,
                acceptance_dir=acceptance,
            )
            message = str(m5_status.get("message") or message)
        else:
            state = "invalid"
            next_command = None
            detail = str(platform_status.get("message") or "") if isinstance(platform_status, dict) else ""
            message = (
                f"M5 platform evidence is not safely actionable for {platform or 'unknown platform'}"
                + (f": {detail}" if detail else ".")
            )
    elif final_release_authority is None:
        next_gate = "digital_twin_final_release"
        state = "required"
        next_command = _m6_command(root=root, composition_dir=composition_dir, acceptance_dir=acceptance)
        message = "M1-M5 are complete for the exact lineage; canonical M6 finalization is the next required action."
    else:
        next_gate = "complete"
        state = "complete"
        next_command = None

    state, next_gate, next_command, message = _bind_actionable_checkout(
        root=root,
        expected_revision=revision,
        state=state,
        next_gate=next_gate,
        next_command=next_command,
        message=message,
    )

    return {
        "format": FORMAT,
        "version": VERSION,
        "read_only": True,
        "state": state,
        "person_id": str(composition.get("person_id") or ""),
        "person_revision": str(composition.get("person_revision") or ""),
        "body_id": str(composition.get("body_id") or ""),
        "bodyrig_revision": revision,
        "composition_authority_id": str(composition.get("authority_id") or ""),
        "operator_root": str(root) if root is not None else None,
        "m5_ready": m5_status.get("m5_ready") is True,
        "expected_m6_release_id": expected_release_id,
        "m6_authority_path": final_release_path,
        "digital_twin_release_eligible": twin.get("digital_twin_release_eligible") is True,
        "digital_twin_ready": twin.get("digital_twin_ready") is True and final_release_error is None,
        "production_activation": twin.get("production_activation") is True and final_release_error is None,
        "next_gate": next_gate,
        "next_command": next_command,
        "message": message,
        "physical_acceptance": {
            "state": physical.state,
            "gate": physical.gate,
            "next_command": physical.next_command,
        },
        "m5": m5_status,
        "digital_twin": twin,
    }
