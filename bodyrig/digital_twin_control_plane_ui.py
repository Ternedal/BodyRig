from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .operator_launch import OperatorLaunchError, launch_canonical_operator

from .digital_twin_composition_authority import (
    AUTHORITY_ID_RE,
    DigitalTwinCompositionAuthorityError,
    read_composition_authority,
)
from .digital_twin_operator_status import (
    DigitalTwinOperatorStatusError,
    inspect_operator_status,
)
from .hands_feet_nails_authority import (
    HandsFeetNailsAuthorityError,
    REVIEW_ID_RE as HFN_REVIEW_ID_RE,
    read_authority as read_hfn_review_authority,
)
from .hands_feet_nails_release_authority import (
    HandsFeetNailsReleaseAuthorityError,
    RELEASE_ID_RE as HFN_RELEASE_ID_RE,
    read_release_authority as read_hfn_release_authority,
)
from .hands_feet_nails_source_capture import (
    CAPTURE_ID_RE as HFN_CAPTURE_ID_RE,
    HandsFeetNailsSourceCaptureError,
    read_source_capture as read_hfn_source_capture,
)
from .person_assembly import PersonAssemblyError, read_receipt
from .person_release_status import PersonReleaseStatusError, inspect_candidate_release_status
from .wardrobe_authority import (
    REVIEW_ID_RE as WARDROBE_REVIEW_ID_RE,
    WardrobeAuthorityError,
    read_authority as read_wardrobe_review_authority,
)
from .wardrobe_release_authority import (
    RELEASE_ID_RE as WARDROBE_RELEASE_ID_RE,
    WardrobeReleaseAuthorityError,
    read_release_authority as read_wardrobe_release_authority,
)
from .wardrobe_source_capture import (
    CAPTURE_ID_RE as WARDROBE_CAPTURE_ID_RE,
    WardrobeSourceCaptureError,
    read_source_capture as read_wardrobe_source_capture,
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


def _evidence_stage(
    *,
    base: Path,
    id_pattern: Any,
    reader: Callable[[str], Mapping[str, Any]],
    errors: tuple[type[Exception], ...],
    label: str,
    limit: int = 8,
) -> dict[str, Any]:
    if base.is_symlink():
        return {
            "state": "blocked",
            "complete": False,
            "valid_count": 0,
            "rejected_count": 0,
            "candidate_ids": [],
            "scan_truncated": False,
            "message": f"{label} evidence-root er symlinket og afvises.",
        }
    if not base.is_dir():
        return {
            "state": "required",
            "complete": False,
            "valid_count": 0,
            "rejected_count": 0,
            "candidate_ids": [],
            "scan_truncated": False,
            "message": f"{label} mangler.",
        }

    try:
        directories = [
            item
            for item in sorted(base.iterdir(), key=lambda value: value.name)
            if item.is_dir()
            and not item.is_symlink()
            and id_pattern.fullmatch(item.name) is not None
        ]
    except OSError:
        return {
            "state": "blocked",
            "complete": False,
            "valid_count": 0,
            "rejected_count": 0,
            "candidate_ids": [],
            "scan_truncated": False,
            "message": f"{label} evidence-directory kunne ikke strict-læses.",
        }
    truncated = len(directories) > limit
    valid: list[str] = []
    rejected = 0
    for directory in directories[:limit]:
        try:
            reader(directory.name)
        except errors:
            rejected += 1
            continue
        valid.append(directory.name)

    if valid:
        state = "complete"
        message = f"{len(valid)} strict-valid {label.lower()} fundet."
    elif rejected:
        state = "blocked"
        message = f"{rejected} {label.lower()} kandidater fejlede strict readback."
    else:
        state = "required"
        message = f"{label} mangler."
    if truncated:
        message += f" Scan er bounded til {limit} canonical kandidater."

    return {
        "state": state,
        "complete": state == "complete",
        "valid_count": len(valid),
        "rejected_count": rejected,
        "candidate_ids": valid[:8],
        "scan_truncated": truncated,
        "message": message,
    }


def _finalized_stage(milestone: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    state = str(milestone.get("state") or "blocked")
    authority_id = str(milestone.get("authority_id") or "").strip() or None
    return {
        "state": state,
        "complete": milestone.get("complete") is True,
        "authority_id": authority_id,
        "message": str(milestone.get("message") or f"{label} status mangler."),
    }


def _empty_component_progress(message: str) -> dict[str, Any]:
    def stage(label: str) -> dict[str, Any]:
        return {
            "state": "blocked",
            "complete": False,
            "valid_count": 0,
            "rejected_count": 0,
            "candidate_ids": [],
            "scan_truncated": False,
            "message": f"{label} afventer aktiv Person Revision.",
        }

    return {
        "authority": {
            "read_only": True,
            "capture_mutation_authority": False,
            "human_review_authority": False,
            "finalization_authority": False,
        },
        "m2": {
            "source_capture": stage("M2 source capture"),
            "review": stage("M2 render + human review"),
            "finalized": {
                "state": "blocked",
                "complete": False,
                "authority_id": None,
                "message": message,
            },
            "next_substage": "source_capture",
        },
        "m3": {
            "source_capture": stage("M3 source capture"),
            "review": stage("M3 render + human review"),
            "finalized": {
                "state": "blocked",
                "complete": False,
                "authority_id": None,
                "message": message,
            },
            "next_substage": "source_capture",
        },
    }


def _empty_realization_progress(message: str) -> dict[str, Any]:
    def blocked(label: str) -> dict[str, Any]:
        return {
            "state": "blocked",
            "complete": False,
            "message": f"{label} afventer aktiv Person Revision.",
        }

    return {
        "authority": {
            "read_only": True,
            "composition_mutation_authority": False,
            "physical_acceptance_authority": False,
            "platform_attestation_authority": False,
            "m6_activation_authority": False,
        },
        "m4": {
            "composition": blocked("M4 composition"),
            "physical_acceptance": blocked("M4 fysisk acceptance"),
            "next_substage": "composition",
        },
        "m5": {
            "windows": blocked("M5 Windows realization"),
            "quest": blocked("M5 Quest realization"),
            "finalized": {
                "state": "blocked",
                "complete": False,
                "authority_id": None,
                "message": message,
            },
            "next_substage": "windows",
        },
        "m6": {
            "release": {
                "state": "blocked",
                "complete": False,
                "authority_id": None,
                "message": message,
            },
            "next_substage": "release",
        },
    }


def _component_progress(
    *,
    root: Path,
    person_id: str,
    person_revision: str,
    body_revision: str,
    assembly: Mapping[str, Any],
    body_release: Mapping[str, Any],
    m2: Mapping[str, Any],
    m3: Mapping[str, Any],
) -> dict[str, Any]:
    hfn_capture = _evidence_stage(
        base=root / "hands-feet-nails-source-captures" / person_id / body_revision,
        id_pattern=HFN_CAPTURE_ID_RE,
        reader=lambda capture_id: read_hfn_source_capture(
            root,
            person_id,
            body_revision=body_revision,
            capture_id=capture_id,
        ),
        errors=(HandsFeetNailsSourceCaptureError,),
        label="M2 source capture",
    )
    hfn_review = _evidence_stage(
        base=root / "hands-feet-nails-authorities" / person_id / person_revision,
        id_pattern=HFN_REVIEW_ID_RE,
        reader=lambda review_id: read_hfn_review_authority(
            root,
            assembly_receipt=assembly,
            body_release_status=body_release,
            review_id=review_id,
        ),
        errors=(HandsFeetNailsAuthorityError,),
        label="M2 render + human review",
    )
    wardrobe_capture = _evidence_stage(
        base=root / "wardrobe-source-captures" / person_id / body_revision,
        id_pattern=WARDROBE_CAPTURE_ID_RE,
        reader=lambda capture_id: read_wardrobe_source_capture(
            root,
            person_id,
            body_revision=body_revision,
            capture_id=capture_id,
        ),
        errors=(WardrobeSourceCaptureError,),
        label="M3 source capture",
    )
    wardrobe_review = _evidence_stage(
        base=root / "wardrobe-authorities" / person_id / person_revision,
        id_pattern=WARDROBE_REVIEW_ID_RE,
        reader=lambda review_id: read_wardrobe_review_authority(
            root,
            assembly_receipt=assembly,
            body_release_status=body_release,
            review_id=review_id,
        ),
        errors=(WardrobeAuthorityError,),
        label="M3 render + human review",
    )

    m2_final = _finalized_stage(m2, label="M2 finalized authority")
    m3_final = _finalized_stage(m3, label="M3 finalized authority")

    def next_substage(
        source: Mapping[str, Any],
        review: Mapping[str, Any],
        finalized: Mapping[str, Any],
    ) -> str:
        if source.get("complete") is not True:
            return "source_capture"
        if review.get("complete") is not True:
            return "review"
        if finalized.get("complete") is not True:
            return "finalized"
        return "complete"

    return {
        "authority": {
            "read_only": True,
            "capture_mutation_authority": False,
            "human_review_authority": False,
            "finalization_authority": False,
        },
        "m2": {
            "source_capture": hfn_capture,
            "review": hfn_review,
            "finalized": m2_final,
            "next_substage": next_substage(hfn_capture, hfn_review, m2_final),
        },
        "m3": {
            "source_capture": wardrobe_capture,
            "review": wardrobe_review,
            "finalized": m3_final,
            "next_substage": next_substage(wardrobe_capture, wardrobe_review, m3_final),
        },
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


def _realization_progress(
    *,
    m4: Mapping[str, Any],
    m5: Mapping[str, Any],
    m6: Mapping[str, Any],
    acceptance: Path | None,
    acceptance_error: str | None,
    operator_status_valid: bool,
    m5_detail: Mapping[str, Any] | None,
) -> dict[str, Any]:
    composition = _finalized_stage(m4, label="M4 composition authority")
    if composition.get("complete") is not True:
        physical_acceptance = {
            "state": "blocked",
            "complete": False,
            "evidence_dir": None,
            "message": "M4 fysisk acceptance afventer strict-valid composition authority.",
        }
    elif acceptance is None:
        physical_acceptance = {
            "state": "blocked" if acceptance_error else "required",
            "complete": False,
            "evidence_dir": None,
            "message": acceptance_error or "Eksakt fysisk acceptance-kæde mangler.",
        }
    elif not operator_status_valid:
        physical_acceptance = {
            "state": "blocked",
            "complete": False,
            "evidence_dir": str(acceptance),
            "message": acceptance_error or "Fysisk acceptance er fundet, men downstream strict status kunne ikke valideres.",
        }
    else:
        physical_acceptance = {
            "state": "complete",
            "complete": True,
            "evidence_dir": str(acceptance),
            "message": "Eksakt M4-bundet fysisk acceptance-kæde er strict-valideret.",
        }

    platforms = m5_detail.get("platforms") if isinstance(m5_detail, Mapping) else None
    platforms = platforms if isinstance(platforms, Mapping) else {}

    def platform_stage(key: str, label: str) -> dict[str, Any]:
        raw = platforms.get(key)
        if not isinstance(raw, Mapping):
            return {
                "state": "blocked",
                "complete": False,
                "evidence_dir": None,
                "message": f"{label} evidence mangler fra strict M5 status.",
            }
        ready = raw.get("ready") is True
        state = "complete" if ready else str(raw.get("state") or "blocked")
        if state not in {"complete", "required", "blocked"}:
            state = "blocked"
        return {
            "state": state,
            "complete": ready,
            "evidence_dir": str(raw.get("evidence_dir") or "") or None,
            "message": str(raw.get("message") or f"{label} status mangler."),
        }

    windows = platform_stage("windows-unity-univrm", "M5 Windows")
    quest = platform_stage("android-quest-class", "M5 Quest")
    m5_final = _finalized_stage(m5, label="M5 finalized realization")
    m6_release = _finalized_stage(m6, label="M6 canonical release")

    def next_stage(items: Sequence[tuple[str, Mapping[str, Any]]]) -> str:
        for key, item in items:
            if item.get("complete") is not True:
                return key
        return "complete"

    return {
        "authority": {
            "read_only": True,
            "composition_mutation_authority": False,
            "physical_acceptance_authority": False,
            "platform_attestation_authority": False,
            "m6_activation_authority": False,
        },
        "m4": {
            "composition": composition,
            "physical_acceptance": physical_acceptance,
            "next_substage": next_stage(
                (
                    ("composition", composition),
                    ("physical_acceptance", physical_acceptance),
                )
            ),
        },
        "m5": {
            "windows": windows,
            "quest": quest,
            "finalized": m5_final,
            "next_substage": next_stage(
                (
                    ("windows", windows),
                    ("quest", quest),
                    ("finalized", m5_final),
                )
            ),
        },
        "m6": {
            "release": m6_release,
            "next_substage": next_stage((("release", m6_release),)),
        },
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
            "component_progress": _empty_component_progress(
                "M2/M3 afventer aktiv Person Revision."
            ),
            "realization_progress": _empty_realization_progress(
                "M4-M6 afventer aktiv Person Revision."
            ),
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
                "raw_next_command_exposed": False,
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
        first_unresolved = next(
            (
                (key, item)
                for key, item in (
                    ("m1", m1),
                    ("m2", m2),
                    ("m3", m3),
                    ("m4", m4),
                    ("m5", m5),
                )
                if not item["complete"]
            ),
            ("m5", m5),
        )
        next_gate, next_milestone = first_unresolved
        state = (
            str(next_milestone.get("state") or "blocked")
            if str(next_milestone.get("state") or "") in {"required", "blocked"}
            else "blocked"
        )
        message = str(next_milestone.get("message") or "Digital twin-kæden er ikke komplet.")
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
            authority_id=(
                str(operator_status.get("expected_m6_release_id") or "") or None
                if ready
                else None
            ),
        )
        state = "complete" if ready else str(operator_status.get("state") or "required")
        next_gate = "complete" if ready else str(operator_status.get("next_gate") or "m6")
        message = str(operator_status.get("message") or m6["message"])
        m5_detail = _public_m5(operator_status.get("m5"))

    milestones = {"m1": m1, "m2": m2, "m3": m3, "m4": m4, "m5": m5, "m6": m6}
    component_progress = _component_progress(
        root=root,
        person_id=person_id,
        person_revision=person_revision,
        body_revision=body_revision_id,
        assembly=assembly,
        body_release=body_release,
        m2=m2,
        m3=m3,
    )
    realization_progress = _realization_progress(
        m4=m4,
        m5=m5,
        m6=m6,
        acceptance=acceptance,
        acceptance_error=acceptance_error,
        operator_status_valid=operator_status is not None,
        m5_detail=m5_detail,
    )
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
        "component_progress": component_progress,
        "realization_progress": realization_progress,
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

_M5_ACTIONABLE_PLATFORMS = {"windows-unity-univrm", "android-quest-class"}


def advance_person_digital_twin_m5(
    profile: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    *,
    library_root: str | Path,
    operator_root: str | Path,
) -> dict[str, Any]:
    root = Path(library_root).expanduser().resolve()
    operator = Path(operator_root).expanduser().resolve()
    status = inspect_person_digital_twin_readiness(
        profile,
        jobs,
        library_root=root,
        operator_root=operator,
    )
    if status.get("state") != "required" or status.get("next_gate") != "digital_twin_platform_acceptance":
        raise DigitalTwinControlPlaneError(
            "Den aktuelle digital-twin gate er ikke et maskinelt M5 realization-trin."
        )

    person_id = str(status.get("person_id") or "").strip()
    person_revision = str(status.get("person_revision") or "").strip()
    body_revision = str(status.get("body_revision") or "").strip()
    milestones = status.get("milestones")
    m4 = milestones.get("m4") if isinstance(milestones, Mapping) else None
    authority_id = str(m4.get("authority_id") or "").strip() if isinstance(m4, Mapping) else ""
    acceptance_raw = str(status.get("physical_acceptance_dir") or "").strip()
    if not person_id or not person_revision or not authority_id or not acceptance_raw:
        raise DigitalTwinControlPlaneError(
            "M5 continuation mangler exact Person/M4/physical acceptance authority."
        )

    composition_dir = (
        root
        / "digital-twin-composition-authorities"
        / person_id
        / person_revision
        / authority_id
    ).resolve()
    acceptance = Path(acceptance_raw).expanduser().resolve()
    try:
        raw = inspect_operator_status(
            composition_authority_dir=composition_dir,
            acceptance_dir=acceptance,
            library_root=root,
            operator_root=operator,
        )
    except DigitalTwinOperatorStatusError as exc:
        raise DigitalTwinControlPlaneError(str(exc)) from exc

    command = raw.get("next_command")
    m5 = raw.get("m5")
    m5_next = str(m5.get("next_gate") or "") if isinstance(m5, Mapping) else ""
    platform = m5_next.split(":", 1)[1] if m5_next.startswith("m5:") else ""
    if (
        raw.get("state") != "required"
        or raw.get("next_gate") != "digital_twin_platform_acceptance"
        or platform not in _M5_ACTIONABLE_PLATFORMS
        or not isinstance(command, str)
        or not command.strip()
    ):
        raise DigitalTwinControlPlaneError(
            "Canonical M5 status ændrede sig eller er ikke sikkert launch-klar."
        )

    try:
        launch = launch_canonical_operator(
            command,
            category="digital-twin",
            context={
                "person_id": person_id,
                "person_revision": person_revision,
                "body_revision": body_revision,
                "gate": "digital_twin_platform_acceptance",
                "platform": platform,
                "composition_authority_id": authority_id,
            },
            cwd=operator,
        )
    except OperatorLaunchError as exc:
        raise DigitalTwinControlPlaneError(str(exc)) from exc

    return {
        "launched": True,
        "action": "advance-m5",
        "platform": platform,
        "launch": launch,
        "production_activation": False,
    }

