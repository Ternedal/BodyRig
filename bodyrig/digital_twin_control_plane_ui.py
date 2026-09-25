from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .digital_twin_composition_authority import (
    AUTHORITY_ID_RE,
    DigitalTwinCompositionAuthorityError,
    read_composition_authority,
)
from .digital_twin_operator_status import (
    DigitalTwinOperatorStatusError,
    inspect_operator_status,
)
from .hands_feet_nails_release_authority import (
    HandsFeetNailsReleaseAuthorityError,
    RELEASE_ID_RE as HFN_RELEASE_ID_RE,
    read_release_authority as read_hfn_release_authority,
)
from .person_assembly import PersonAssemblyError, read_receipt
from .person_release_status import PersonReleaseStatusError, inspect_candidate_release_status
from .wardrobe_release_authority import (
    RELEASE_ID_RE as WARDROBE_RELEASE_ID_RE,
    WardrobeReleaseAuthorityError,
    read_release_authority as read_wardrobe_release_authority,
)


class DigitalTwinControlPlaneError(RuntimeError):
    pass


def _milestone(
    state: str,
    *,
    message: str,
    authority_id: str | None = None,
) -> dict[str, Any]:
    return {
        "state": state,
        "complete": state == "complete",
        "message": message,
        "authority_id": authority_id,
    }


def _active_revision(profile: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    revision_id = str(profile.get("active_person_revision") or "").strip()
    if not revision_id:
        return None
    matches = [
        dict(item)
        for item in profile.get("person_revisions", [])
        if isinstance(item, Mapping) and str(item.get("revision_id") or "") == revision_id
    ]
    if len(matches) != 1:
        raise DigitalTwinControlPlaneError(
            "Active Person Revision does not resolve to exactly one profile revision."
        )
    return revision_id, matches[0]


def _body_revision(profile: Mapping[str, Any], revision_id: str) -> dict[str, Any]:
    matches = [
        dict(item)
        for item in profile.get("body_revisions", [])
        if isinstance(item, Mapping) and str(item.get("revision_id") or "") == revision_id
    ]
    if len(matches) != 1:
        raise DigitalTwinControlPlaneError(
            "Active Person Revision body binding does not resolve exactly."
        )
    return matches[0]


def _valid_release_authorities(
    *,
    root: Path,
    category: str,
    person_id: str,
    person_revision: str,
    id_pattern: Any,
    reader: Callable[..., dict[str, Any]],
    assembly: Mapping[str, Any],
    body_release: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    base = root / category / person_id / person_revision
    if not base.is_dir() or base.is_symlink():
        return [], []
    valid: list[dict[str, Any]] = []
    rejected: list[str] = []
    for directory in sorted(base.iterdir(), key=lambda item: item.name):
        if directory.is_symlink() or not directory.is_dir():
            continue
        release_id = directory.name
        if id_pattern.fullmatch(release_id) is None:
            continue
        try:
            value = reader(
                root,
                assembly_receipt=assembly,
                body_release_status=body_release,
                release_id=release_id,
            )
        except (HandsFeetNailsReleaseAuthorityError, WardrobeReleaseAuthorityError) as exc:
            rejected.append(f"{release_id}: {exc}")
            continue
        valid.append(value)
    return valid, rejected


def _valid_m4_authorities(
    *,
    root: Path,
    person_id: str,
    person_revision: str,
) -> tuple[list[tuple[Path, dict[str, Any]]], list[str]]:
    base = root / "digital-twin-composition-authorities" / person_id / person_revision
    if not base.is_dir() or base.is_symlink():
        return [], []
    valid: list[tuple[Path, dict[str, Any]]] = []
    rejected: list[str] = []
    for directory in sorted(base.iterdir(), key=lambda item: item.name):
        if directory.is_symlink() or not directory.is_dir():
            continue
        authority_id = directory.name
        if AUTHORITY_ID_RE.fullmatch(authority_id) is None:
            continue
        try:
            value = read_composition_authority(
                root,
                person_id=person_id,
                person_revision=person_revision,
                authority_id=authority_id,
            )
        except DigitalTwinCompositionAuthorityError as exc:
            rejected.append(f"{authority_id}: {exc}")
            continue
        valid.append((directory.resolve(), value))
    return valid, rejected


def _acceptance_dir(
    jobs: Sequence[Mapping[str, Any]],
    *,
    person_id: str,
    body_revision: str,
    body_id: str,
    bodyrig_revision: str,
) -> tuple[Path | None, str | None]:
    candidates: list[Path] = []
    for job in jobs:
        if (
            job.get("format") != "bodyrig-ui-job"
            or job.get("kind") != "body-build"
            or job.get("status") != "succeeded"
            or str(job.get("person_id") or "") != person_id
            or str(job.get("body_revision") or "") != body_revision
            or str(job.get("canonical_body_id") or "") != body_id
            or str(job.get("bodyrig_revision") or "").strip().lower() != bodyrig_revision
        ):
            continue
        raw = str(job.get("acceptance_dir") or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser().resolve()
        if path.is_dir() and not path.is_symlink():
            candidates.append(path)

    unique = sorted({str(path): path for path in candidates}.values(), key=str)
    if not unique:
        return None, "No exact succeeded body-build acceptance chain matches the active M4 authority."
    if len(unique) != 1:
        return None, "Multiple succeeded body-build acceptance chains match the active M4 authority."
    return unique[0], None


def _public_m5(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    platforms = value.get("platforms")
    clean_platforms: dict[str, Any] = {}
    if isinstance(platforms, Mapping):
        for key in ("windows-unity-univrm", "android-quest-class"):
            item = platforms.get(key)
            if not isinstance(item, Mapping):
                continue
            clean_platforms[key] = {
                "ready": item.get("ready") is True,
                "state": str(item.get("state") or "unknown"),
                "message": str(item.get("message") or ""),
                "evidence_dir": str(item.get("evidence_dir") or "") or None,
            }
    return {
        "m5_ready": value.get("m5_ready") is True,
        "next_gate": str(value.get("next_gate") or ""),
        "message": str(value.get("message") or ""),
        "blockers": [
            str(item)
            for item in (value.get("blockers") or [])
            if isinstance(item, str)
        ][:20],
        "platforms": clean_platforms,
    }


def inspect_person_digital_twin_readiness(
    profile: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    *,
    library_root: str | Path,
    operator_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(library_root).expanduser().resolve()
    person_id = str(profile.get("person_id") or "").strip()
    active = _active_revision(profile)
    if active is None:
        return {
            "read_only": True,
            "state": "not-assembled",
            "person_id": person_id,
            "person_revision": None,
            "body_revision": None,
            "digital_twin_ready": False,
            "production_activation": False,
            "next_gate": "person_assembly",
            "message": "Ingen aktiv godkendt Person Revision er valgt.",
            "milestones": {
                "m1": _milestone("required", message="Godkend og aktivér en audition-bound Person Revision."),
                "m2": _milestone("blocked", message="M2 afventer aktiv Person Revision."),
                "m3": _milestone("blocked", message="M3 afventer aktiv Person Revision."),
                "m4": _milestone("blocked", message="M4 afventer M1-M3."),
                "m5": _milestone("blocked", message="M5 afventer M4."),
                "m6": _milestone("blocked", message="M6 afventer M5."),
            },
            "authority": {
                "browser_command_authority": False,
                "mutation_authority": False,
            },
        }

    person_revision, bundle = active
    body_revision_id = str(bundle.get("body_revision") or "")
    body_item = _body_revision(profile, body_revision_id)
    body_id = str(body_item.get("body_id") or "")
    package_sha256 = str(body_item.get("package_sha256") or "")

    try:
        assembly = read_receipt(
            root,
            person_id=person_id,
            person_revision=person_revision,
        )
    except PersonAssemblyError as exc:
        raise DigitalTwinControlPlaneError(f"Person assembly authority is invalid: {exc}") from exc

    try:
        body_release = inspect_candidate_release_status(
            jobs,
            person_id=person_id,
            body_revision=body_revision_id,
            body_id=body_id,
            package_sha256=package_sha256,
        )
    except PersonReleaseStatusError as exc:
        raise DigitalTwinControlPlaneError(f"M1 body release authority is invalid: {exc}") from exc

    body_ready = (
        body_release.get("production_ready") is True
        and body_release.get("production_activation") is True
    )
    m1_state = "complete" if body_ready else (
        "blocked" if str(body_release.get("state") or "") == "blocked" else "required"
    )
    m1 = _milestone(
        m1_state,
        message=str(body_release.get("message") or "Body release authority is incomplete."),
    )

    hfn, hfn_rejected = _valid_release_authorities(
        root=root,
        category="hands-feet-nails-release-authorities",
        person_id=person_id,
        person_revision=person_revision,
        id_pattern=HFN_RELEASE_ID_RE,
        reader=read_hfn_release_authority,
        assembly=assembly,
        body_release=body_release,
    )
    wardrobe, wardrobe_rejected = _valid_release_authorities(
        root=root,
        category="wardrobe-release-authorities",
        person_id=person_id,
        person_revision=person_revision,
        id_pattern=WARDROBE_RELEASE_ID_RE,
        reader=read_wardrobe_release_authority,
        assembly=assembly,
        body_release=body_release,
    )

    if len(hfn) == 1:
        m2 = _milestone(
            "complete",
            message="Eksakt finalized hands/feet/nails authority er strict-valideret.",
            authority_id=str(hfn[0].get("release_id") or ""),
        )
        hfn_authority: Mapping[str, Any] | None = hfn[0]
    elif len(hfn) > 1:
        m2 = _milestone("blocked", message="Flere strict-valid M2 release authorities er fundet; selection er ambiguous.")
        hfn_authority = None
    else:
        m2 = _milestone(
            "blocked" if hfn_rejected else "required",
            message=(hfn_rejected[0] if hfn_rejected else "Finalized hands/feet/nails authority mangler."),
        )
        hfn_authority = None

    if len(wardrobe) == 1:
        m3 = _milestone(
            "complete",
            message="Eksakt finalized wardrobe/footwear authority er strict-valideret.",
            authority_id=str(wardrobe[0].get("release_id") or ""),
        )
        wardrobe_authority: Mapping[str, Any] | None = wardrobe[0]
    elif len(wardrobe) > 1:
        m3 = _milestone("blocked", message="Flere strict-valid M3 release authorities er fundet; selection er ambiguous.")
        wardrobe_authority = None
    else:
        m3 = _milestone(
            "blocked" if wardrobe_rejected else "required",
            message=(wardrobe_rejected[0] if wardrobe_rejected else "Finalized wardrobe/footwear authority mangler."),
        )
        wardrobe_authority = None

    m4_values, m4_rejected = _valid_m4_authorities(
        root=root,
        person_id=person_id,
        person_revision=person_revision,
    )
    composition_dir: Path | None = None
    composition: Mapping[str, Any] | None = None
    if len(m4_values) == 1:
        composition_dir, composition = m4_values[0]
        frozen_m2 = composition.get("hands_feet_nails")
        frozen_m3 = composition.get("wardrobe")
        if isinstance(frozen_m2, Mapping):
            m2 = _milestone(
                "complete",
                message="M4-frozen M2 hands/feet/nails authority er strict-valideret i den aktive composition.",
                authority_id=str(frozen_m2.get("release_id") or "") or None,
            )
        if isinstance(frozen_m3, Mapping):
            m3 = _milestone(
                "complete",
                message="M4-frozen M3 wardrobe/footwear authority er strict-valideret i den aktive composition.",
                authority_id=str(frozen_m3.get("release_id") or "") or None,
            )
        m4 = _milestone(
            "complete",
            message="Eksakt M4 Person Revision composition authority er strict-valideret.",
            authority_id=str(composition.get("authority_id") or ""),
        )
    elif len(m4_values) > 1:
        m4 = _milestone("blocked", message="Flere strict-valid M4 composition authorities er fundet; active composition er ambiguous.")
    else:
        prereq_complete = m1["complete"] and m2["complete"] and m3["complete"]
        m4 = _milestone(
            "blocked" if m4_rejected or not prereq_complete else "required",
            message=(
                m4_rejected[0]
                if m4_rejected
                else (
                    "M4 afventer komplette M1-M3 authorities."
                    if not prereq_complete
                    else "M4 Person Revision composition authority mangler."
                )
            ),
        )

    operator_status: dict[str, Any] | None = None
    acceptance: Path | None = None
    acceptance_error: str | None = None
    if composition_dir is not None and composition is not None:
        acceptance, acceptance_error = _acceptance_dir(
            jobs,
            person_id=person_id,
            body_revision=body_revision_id,
            body_id=str(composition.get("body_id") or ""),
            bodyrig_revision=str(composition.get("bodyrig_revision") or "").lower(),
        )
        if acceptance is not None:
            try:
                operator_status = inspect_operator_status(
                    composition_authority_dir=composition_dir,
                    acceptance_dir=acceptance,
                    library_root=root,
                    operator_root=operator_root,
                )
            except DigitalTwinOperatorStatusError as exc:
                acceptance_error = str(exc)

    if operator_status is None:
        m5 = _milestone(
            "blocked" if m4["complete"] else "blocked",
            message=acceptance_error or "M5 afventer en entydig strict-valid M4 + fysisk acceptance-kæde.",
        )
        m6 = _milestone("blocked", message="M6 afventer M5.")
        state = "blocked" if any(
            item["state"] == "blocked" for item in (m1, m2, m3, m4, m5)
        ) else "required"
        next_gate = next(
            (
                key
                for key, item in (
                    ("m1", m1),
                    ("m2", m2),
                    ("m3", m3),
                    ("m4", m4),
                    ("m5", m5),
                )
                if not item["complete"]
            ),
            "m5",
        )
        message = m5["message"] if m4["complete"] else "Digital twin-kæden er endnu ikke klar til M5/M6 strict status."
        ready = False
        activation = False
        m5_detail = None
    else:
        m5_complete = operator_status.get("m5_ready") is True
        m5_state = "complete" if m5_complete else (
            "blocked"
            if str(operator_status.get("state") or "") in {"blocked", "invalid"}
            else "required"
        )
        m5 = _milestone(
            m5_state,
            message=(
                "Windows + Quest M5 realization er strict-valideret."
                if m5_complete
                else str(operator_status.get("message") or "M5 realization mangler.")
            ),
        )
        ready = (
            operator_status.get("digital_twin_ready") is True
            and operator_status.get("production_activation") is True
        )
        activation = operator_status.get("production_activation") is True
        m6_state = "complete" if ready else (
            "blocked"
            if str(operator_status.get("state") or "") in {"blocked", "invalid"}
            else "required"
        )
        m6 = _milestone(
            m6_state,
            message=(
                "Canonical M6 release er strict-valideret og aktiv."
                if ready
                else str(operator_status.get("message") or "Canonical M6 release mangler.")
            ),
            authority_id=str(operator_status.get("expected_m6_release_id") or "") or None,
        )
        state = "complete" if ready else str(operator_status.get("state") or "required")
        next_gate = "complete" if ready else str(operator_status.get("next_gate") or "m6")
        message = str(operator_status.get("message") or m6["message"])
        m5_detail = _public_m5(operator_status.get("m5"))

    milestones = {"m1": m1, "m2": m2, "m3": m3, "m4": m4, "m5": m5, "m6": m6}
    return {
        "read_only": True,
        "state": state,
        "person_id": person_id,
        "person_revision": person_revision,
        "body_revision": body_revision_id,
        "body_id": body_id,
        "digital_twin_ready": ready,
        "production_activation": activation,
        "next_gate": next_gate,
        "message": message,
        "milestones": milestones,
        "physical_acceptance_dir": str(acceptance) if acceptance is not None else None,
        "m5": m5_detail,
        "diagnostics": {
            "m2_rejected_count": len(hfn_rejected),
            "m3_rejected_count": len(wardrobe_rejected),
            "m4_rejected_count": len(m4_rejected),
            "acceptance_error": acceptance_error,
        },
        "authority": {
            "browser_command_authority": False,
            "mutation_authority": False,
            "raw_next_command_exposed": False,
        },
    }
