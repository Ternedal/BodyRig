from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .acceptance_status_cli import _git_checkout_state
from .digital_twin_operator_status import (
    DigitalTwinOperatorStatusError,
    inspect_operator_status,
)
from .digital_twin_photoreal_link import (
    DigitalTwinPhotorealLinkError,
    build_photoreal_link,
    photoreal_link_dir,
    read_photoreal_link,
)
from .digital_twin_photoreal_m5_link import (
    DigitalTwinPhotorealM5LinkError,
    build_photoreal_m5_link,
    photoreal_m5_link_dir,
    read_photoreal_m5_link,
)
from .digital_twin_photoreal_release import (
    DigitalTwinPhotorealReleaseError,
    build_photoreal_release,
    photoreal_release_dir,
    read_photoreal_release,
)

FORMAT = "bodyrig-photoreal-digital-twin-operator-status"
VERSION = 1

_PHOTOREAL_SCRIPTS = (
    "link-photoreal-v2-m4.ps1",
    "link-photoreal-v2-m5.ps1",
    "finalize-photoreal-digital-twin.ps1",
)


class PhotorealDigitalTwinOperatorStatusError(RuntimeError):
    pass


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotorealDigitalTwinOperatorStatusError(
            f"{label} is unreadable: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealDigitalTwinOperatorStatusError(
            f"{label} must be a JSON object: {path}"
        )
    return value


def _ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _script_invocation(name: str, root: Path | None) -> str:
    if root is None:
        return f".\\{name}"
    return f"& {_ps_quote((root / name).resolve())}"


def _resolved_operator_root(
    canonical: dict[str, Any],
    *,
    explicit_operator_root: str | Path | None,
) -> Path | None:
    value = canonical.get("operator_root")
    if value is None:
        return None
    root = Path(str(value)).expanduser().resolve()
    missing = tuple(name for name in _PHOTOREAL_SCRIPTS if not (root / name).is_file())
    if missing:
        if explicit_operator_root is not None:
            raise PhotorealDigitalTwinOperatorStatusError(
                "BodyRig operator root is missing Photoreal operator dependencies: "
                + ", ".join(missing)
            )
        return None
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
            + " Inspection-only: no complete BodyRig Git checkout is available, "
            "so no executable Photoreal next command is authorized.",
        )
    try:
        head, clean = _git_checkout_state(root)
    except Exception as exc:
        raise PhotorealDigitalTwinOperatorStatusError(
            f"Could not verify BodyRig operator checkout: {exc}"
        ) from exc
    if head != expected_revision:
        return (
            "blocked",
            "operator-checkout",
            None,
            f"BodyRig operator checkout revision {head} does not match Photoreal evidence "
            f"revision {expected_revision}. Checkout the exact evidence revision before continuing.",
        )
    if not clean:
        return (
            "blocked",
            "operator-checkout",
            None,
            f"BodyRig operator checkout is dirty. Photoreal authority commands require "
            f"exact clean revision {head}.",
        )
    return state, next_gate, next_command, message


def _m4_link_command(
    *,
    root: Path | None,
    composition_dir: Path,
    photoreal_binding: Path,
    p3_review: Path,
) -> str:
    return (
        f"{_script_invocation('link-photoreal-v2-m4.ps1', root)} "
        f"-CompositionAuthorityDir {_ps_quote(composition_dir)} "
        f"-PhotorealPersonBinding {_ps_quote(photoreal_binding)} "
        f"-P3PhysicalReview {_ps_quote(p3_review)}"
    )


def _m5_link_command(
    *,
    root: Path | None,
    composition_dir: Path,
    acceptance_dir: Path,
    m4_link_dir: Path,
) -> str:
    return (
        f"{_script_invocation('link-photoreal-v2-m5.ps1', root)} "
        f"-CompositionAuthorityDir {_ps_quote(composition_dir)} "
        f"-AcceptanceDir {_ps_quote(acceptance_dir)} "
        f"-M4PhotorealLinkDir {_ps_quote(m4_link_dir)}"
    )


def _photoreal_release_command(
    *,
    root: Path | None,
    canonical_m6_dir: Path,
    composition_dir: Path,
    acceptance_dir: Path,
    photoreal_m5_dir: Path,
    m4_link_dir: Path,
    library_root: Path,
) -> str:
    return (
        f"{_script_invocation('finalize-photoreal-digital-twin.ps1', root)} "
        f"-CanonicalM6ReleaseDir {_ps_quote(canonical_m6_dir)} "
        f"-CompositionAuthorityDir {_ps_quote(composition_dir)} "
        f"-AcceptanceDir {_ps_quote(acceptance_dir)} "
        f"-PhotorealM5LinkDir {_ps_quote(photoreal_m5_dir)} "
        f"-M4PhotorealLinkDir {_ps_quote(m4_link_dir)} "
        f"-LibraryRoot {_ps_quote(library_root)}"
    )


def inspect_photoreal_operator_status(
    *,
    composition_authority_dir: str | Path,
    acceptance_dir: str | Path,
    library_root: str | Path,
    photoreal_person_binding: str | Path,
    p3_physical_review: str | Path,
    operator_root: str | Path | None = None,
) -> dict[str, Any]:
    """Read-only status for the exact canonical + Photoreal digital-twin chain.

    The inspector never writes authority. It delegates canonical M4/M5/M6
    validation to the existing operator status, then strict-builds/reads the
    additive Photoreal M4 link, M5 link and final Photoreal M6 release.
    """

    composition_dir = Path(composition_authority_dir).expanduser().resolve()
    acceptance = Path(acceptance_dir).expanduser().resolve()
    library = Path(library_root).expanduser().resolve()
    binding_path = Path(photoreal_person_binding).expanduser().resolve()
    p3_path = Path(p3_physical_review).expanduser().resolve()

    if not composition_dir.is_dir():
        raise PhotorealDigitalTwinOperatorStatusError(
            f"M4 composition authority directory not found: {composition_dir}"
        )
    if not acceptance.is_dir():
        raise PhotorealDigitalTwinOperatorStatusError(
            f"canonical physical acceptance directory not found: {acceptance}"
        )
    if not binding_path.is_file():
        raise PhotorealDigitalTwinOperatorStatusError(
            f"Photoreal Person binding not found: {binding_path}"
        )
    if not p3_path.is_file():
        raise PhotorealDigitalTwinOperatorStatusError(
            f"P3 physical runtime review not found: {p3_path}"
        )

    authority_hint = _json(
        composition_dir / "authority.json",
        "M4 composition authority",
    )
    revision = str(authority_hint.get("bodyrig_revision") or "").strip().lower()
    person_id = str(authority_hint.get("person_id") or "").strip()
    person_revision = str(authority_hint.get("person_revision") or "").strip()
    body_id = str(authority_hint.get("body_id") or "").strip()
    if (
        len(revision) != 40
        or any(character not in "0123456789abcdef" for character in revision)
        or not person_id
        or not person_revision
        or not body_id
    ):
        raise PhotorealDigitalTwinOperatorStatusError(
            "M4 composition authority lacks canonical Person/body/revision identity"
        )

    try:
        canonical = inspect_operator_status(
            composition_authority_dir=composition_dir,
            acceptance_dir=acceptance,
            library_root=library,
            operator_root=operator_root,
        )
    except (DigitalTwinOperatorStatusError, OSError, ValueError) as exc:
        raise PhotorealDigitalTwinOperatorStatusError(
            f"canonical digital-twin status is invalid: {exc}"
        ) from exc

    root = _resolved_operator_root(
        canonical,
        explicit_operator_root=operator_root,
    )

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "read_only": True,
        "state": "required",
        "person_id": person_id,
        "person_revision": person_revision,
        "body_id": body_id,
        "bodyrig_revision": revision,
        "operator_root": str(root) if root is not None else None,
        "library_root": str(library),
        "photoreal_person_binding": str(binding_path),
        "p3_physical_review": str(p3_path),
        "canonical_state": str(canonical.get("state") or ""),
        "canonical_m5_ready": canonical.get("m5_ready") is True,
        "canonical_digital_twin_ready": canonical.get("digital_twin_ready") is True,
        "canonical_production_activation": canonical.get("production_activation") is True,
        "expected_m4_photoreal_link_id": None,
        "m4_photoreal_link_path": None,
        "m4_photoreal_link_ready": False,
        "expected_photoreal_m5_link_id": None,
        "photoreal_m5_link_path": None,
        "photoreal_m5_ready": False,
        "expected_photoreal_release_id": None,
        "photoreal_release_path": None,
        "photoreal_digital_twin_ready": False,
        "production_activation": False,
        "next_gate": "",
        "next_command": None,
        "message": "",
    }

    canonical_state = str(canonical.get("state") or "")
    if canonical_state in {"invalid", "blocked"}:
        result.update(
            {
                "state": canonical_state,
                "next_gate": str(canonical.get("next_gate") or "canonical-digital-twin"),
                "next_command": None,
                "message": str(
                    canonical.get("message")
                    or "Canonical digital-twin chain is not safely actionable."
                ),
            }
        )
        return result

    try:
        expected_m4 = build_photoreal_link(
            library,
            composition_authority_dir_path=composition_dir,
            photoreal_person_binding_path=binding_path,
            p3_physical_runtime_review_path=p3_path,
            bodyrig_revision=revision,
        )
        m4_dir = photoreal_link_dir(
            library,
            person_id=str(expected_m4["person_id"]),
            person_revision=str(expected_m4["person_revision"]),
            link_id=str(expected_m4["link_id"]),
        )
        result["expected_m4_photoreal_link_id"] = str(expected_m4["link_id"])
        result["m4_photoreal_link_path"] = str(m4_dir / "authority.json")
        if m4_dir.exists():
            read_photoreal_link(
                library,
                person_id=str(expected_m4["person_id"]),
                person_revision=str(expected_m4["person_revision"]),
                link_id=str(expected_m4["link_id"]),
                composition_authority_dir_path=composition_dir,
            )
            result["m4_photoreal_link_ready"] = True
    except (DigitalTwinPhotorealLinkError, OSError, ValueError) as exc:
        result.update(
            {
                "state": "invalid",
                "next_gate": "photoreal_m4_link",
                "next_command": None,
                "message": f"Photoreal M4 link preflight/readback is invalid: {exc}",
            }
        )
        return result

    if result["m4_photoreal_link_ready"] is not True:
        state, gate, command, message = _bind_actionable_checkout(
            root=root,
            expected_revision=revision,
            state="required",
            next_gate="photoreal_m4_link",
            next_command=_m4_link_command(
                root=root,
                composition_dir=composition_dir,
                photoreal_binding=binding_path,
                p3_review=p3_path,
            ),
            message=(
                "Accepted P3/Person authority is valid; bind it to the exact "
                "M4 composition before Photoreal-aware M5."
            ),
        )
        result.update(
            {
                "state": state,
                "next_gate": gate,
                "next_command": command,
                "message": message,
            }
        )
        return result

    if canonical.get("m5_ready") is not True:
        result.update(
            {
                "state": canonical_state or "required",
                "next_gate": str(
                    canonical.get("next_gate")
                    or "digital_twin_platform_acceptance"
                ),
                "next_command": canonical.get("next_command"),
                "message": str(
                    canonical.get("message")
                    or "Canonical M5 Windows/Quest realization is required."
                ),
            }
        )
        return result

    try:
        expected_m5 = build_photoreal_m5_link(
            library,
            composition_authority_dir_path=composition_dir,
            acceptance_dir_path=acceptance,
            photoreal_link_authority_dir_path=m4_dir,
            bodyrig_revision=revision,
        )
        m5_dir = photoreal_m5_link_dir(
            library,
            person_id=str(expected_m5["person_id"]),
            person_revision=str(expected_m5["person_revision"]),
            link_id=str(expected_m5["link_id"]),
        )
        result["expected_photoreal_m5_link_id"] = str(expected_m5["link_id"])
        result["photoreal_m5_link_path"] = str(m5_dir / "authority.json")
        if m5_dir.exists():
            read_photoreal_m5_link(
                library,
                person_id=str(expected_m5["person_id"]),
                person_revision=str(expected_m5["person_revision"]),
                link_id=str(expected_m5["link_id"]),
                composition_authority_dir_path=composition_dir,
                acceptance_dir_path=acceptance,
                photoreal_link_authority_dir_path=m4_dir,
            )
            result["photoreal_m5_ready"] = True
    except (DigitalTwinPhotorealM5LinkError, OSError, ValueError) as exc:
        result.update(
            {
                "state": "invalid",
                "next_gate": "photoreal_m5_link",
                "next_command": None,
                "message": f"Photoreal M5 link preflight/readback is invalid: {exc}",
            }
        )
        return result

    if result["photoreal_m5_ready"] is not True:
        state, gate, command, message = _bind_actionable_checkout(
            root=root,
            expected_revision=revision,
            state="required",
            next_gate="photoreal_m5_link",
            next_command=_m5_link_command(
                root=root,
                composition_dir=composition_dir,
                acceptance_dir=acceptance,
                m4_link_dir=m4_dir,
            ),
            message=(
                "Canonical Windows/Quest M5 is complete; bind those exact "
                "realizations to the M4 Photoreal authority."
            ),
        )
        result.update(
            {
                "state": state,
                "next_gate": gate,
                "next_command": command,
                "message": message,
            }
        )
        return result

    if not (
        canonical.get("digital_twin_ready") is True
        and canonical.get("production_activation") is True
    ):
        result.update(
            {
                "state": canonical_state or "required",
                "next_gate": str(
                    canonical.get("next_gate") or "digital_twin_final_release"
                ),
                "next_command": canonical.get("next_command"),
                "message": str(
                    canonical.get("message")
                    or "Canonical M6 release must complete before Photoreal M6."
                ),
            }
        )
        return result

    canonical_m6_path = canonical.get("m6_authority_path")
    if not isinstance(canonical_m6_path, str) or not canonical_m6_path:
        result.update(
            {
                "state": "invalid",
                "next_gate": "digital_twin_final_release",
                "next_command": None,
                "message": (
                    "Canonical digital twin reports ready but exposes no exact "
                    "M6 authority path for Photoreal release binding."
                ),
            }
        )
        return result
    canonical_m6_dir = Path(canonical_m6_path).expanduser().resolve().parent

    try:
        expected_release = build_photoreal_release(
            library,
            canonical_m6_release_dir_path=canonical_m6_dir,
            composition_authority_dir_path=composition_dir,
            acceptance_dir_path=acceptance,
            photoreal_m5_link_authority_dir_path=m5_dir,
            m4_photoreal_link_authority_dir_path=m4_dir,
            bodyrig_revision=revision,
        )
        release_dir = photoreal_release_dir(
            library,
            person_id=str(expected_release["person_id"]),
            person_revision=str(expected_release["person_revision"]),
            release_id=str(expected_release["release_id"]),
        )
        result["expected_photoreal_release_id"] = str(expected_release["release_id"])
        result["photoreal_release_path"] = str(release_dir / "authority.json")
        if release_dir.exists():
            final = read_photoreal_release(
                library,
                person_id=str(expected_release["person_id"]),
                person_revision=str(expected_release["person_revision"]),
                release_id=str(expected_release["release_id"]),
                canonical_m6_release_dir_path=canonical_m6_dir,
                composition_authority_dir_path=composition_dir,
                acceptance_dir_path=acceptance,
                photoreal_m5_link_authority_dir_path=m5_dir,
                m4_photoreal_link_authority_dir_path=m4_dir,
            )
            if (
                final.get("photoreal_digital_twin_ready") is True
                and final.get("production_activation") is True
                and final.get("state") == "released"
            ):
                result["photoreal_digital_twin_ready"] = True
                result["production_activation"] = True
    except (DigitalTwinPhotorealReleaseError, OSError, ValueError) as exc:
        result.update(
            {
                "state": "invalid",
                "next_gate": "photoreal_m6_release",
                "next_command": None,
                "message": f"Photoreal M6 preflight/readback is invalid: {exc}",
            }
        )
        return result

    if result["photoreal_digital_twin_ready"] is not True:
        state, gate, command, message = _bind_actionable_checkout(
            root=root,
            expected_revision=revision,
            state="required",
            next_gate="photoreal_m6_release",
            next_command=_photoreal_release_command(
                root=root,
                canonical_m6_dir=canonical_m6_dir,
                composition_dir=composition_dir,
                acceptance_dir=acceptance,
                photoreal_m5_dir=m5_dir,
                m4_link_dir=m4_dir,
                library_root=library,
            ),
            message=(
                "Canonical M6 and Photoreal M5 are complete for the exact "
                "lineage; final Photoreal M6 is the next required action."
            ),
        )
        result.update(
            {
                "state": state,
                "next_gate": gate,
                "next_command": command,
                "message": message,
            }
        )
        return result

    result.update(
        {
            "state": "complete",
            "next_gate": "complete",
            "next_command": None,
            "message": (
                "Final Photoreal M6 strict-readback is complete for this exact "
                "Person Revision and canonical release."
            ),
        }
    )
    return result
