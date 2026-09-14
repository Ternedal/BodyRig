from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .hands_feet_nails_authority import HandsFeetNailsAuthorityError, validate_render_manifest
from .hands_feet_nails_detail_candidate import (
    HandsFeetNailsDetailCandidateError,
    read_detail_candidate,
)
from .hands_feet_nails_fingernail_geometry_candidate import (
    HandsFeetNailsFingernailGeometryError,
    geometry_paths,
    read_fingernail_geometry_candidate,
)
from .hands_feet_nails_toenail_geometry_candidate import (
    HandsFeetNailsToenailGeometryError,
    geometry_paths as toenail_geometry_paths,
    read_toenail_geometry_candidate,
)
from .high_fidelity_hfn_review import HighFidelityHfnReviewError, read_review

CANDIDATE_GATE = "hfn_detail_candidate"
RENDER_GATE = "hfn_render_review"
HUMAN_GATE = "hfn_human_review"
GATE_ORDER = (CANDIDATE_GATE, RENDER_GATE, HUMAN_GATE)
RENDER_AUTHORITY_FIELDS = {
    "format", "version", "bodyrig_revision", "body_id", "package_sha256",
    "runtime_manifest_sha256", "comparison_authority_sha256", "render_manifest_sha256",
    "render_region_sha256", "comparison_only", "human_review_required", "production_activation",
}
COMPARISON_FIELDS = {
    "format", "version", "authority", "bodyrig_revision", "runtime_manifest_sha256",
    "package_sha256", "physical_acceptance_authority", "comparison_only", "production_activation",
}


class HighFidelityHfnContinuationError(RuntimeError):
    pass


def _is_v1(value: Any) -> bool:
    return not isinstance(value, bool) and value == 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityHfnContinuationError(f"{label} is missing or unreadable") from exc
    if not isinstance(value, dict):
        raise HighFidelityHfnContinuationError(f"{label} must be a JSON object")
    return value


def _quote(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _gate(gate_id: str, state: str, *, reason: str = "", evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": gate_id,
        "state": state,
        "passed": state == "pass",
        "reason": reason,
        "evidence": evidence or {},
    }


def _candidate_receipt_matches(raw: Mapping[str, Any], *, source_package_sha256: str, bodyrig_revision: str) -> bool:
    return (
        raw.get("format") == "bodyrig-hands-feet-nails-detail-candidate"
        and _is_v1(raw.get("version"))
        and str(raw.get("source_package_sha256") or "").lower() == source_package_sha256
        and str(raw.get("bodyrig_revision") or "").lower() == bodyrig_revision
    )


def _find_candidate(
    root: Path,
    *,
    person_id: str,
    body_revision: str,
    source_package_sha256: str,
    bodyrig_revision: str,
) -> dict[str, Any] | None:
    base = root / "hands-feet-nails-detail-candidates" / person_id / body_revision
    if not base.is_dir():
        return None
    matches: list[dict[str, Any]] = []
    for receipt_path in sorted(base.glob("*/*.json")):
        try:
            raw = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or not _candidate_receipt_matches(
            raw,
            source_package_sha256=source_package_sha256,
            bodyrig_revision=bodyrig_revision,
        ):
            continue
        capture_id = receipt_path.parent.name
        candidate_id = receipt_path.stem
        try:
            candidate = read_detail_candidate(
                root,
                person_id,
                body_revision=body_revision,
                capture_id=capture_id,
                candidate_id=candidate_id,
            )
        except HandsFeetNailsDetailCandidateError as exc:
            raise HighFidelityHfnContinuationError(
                f"matching HFN detail candidate is invalid: {exc}"
            ) from exc
        if not _is_v1(candidate.get("version")):
            raise HighFidelityHfnContinuationError("matching HFN detail candidate version is not canonical v1")
        if candidate["source_package_sha256"] != source_package_sha256:
            raise HighFidelityHfnContinuationError(
                "validated HFN detail candidate source package changed during discovery"
            )
        matches.append(candidate)
    if len(matches) > 1:
        raise HighFidelityHfnContinuationError(
            "multiple valid HFN detail candidates target the exact same promoted package; continuation is ambiguous"
        )
    return matches[0] if matches else None


def _geometry_review_candidate(root: Path, detail: Mapping[str, Any], *, bodyrig_revision: str) -> dict[str, Any]:
    try:
        fingernail = read_fingernail_geometry_candidate(
            root,
            str(detail["person_id"]),
            body_revision=str(detail["body_revision"]),
            capture_id=str(detail["capture_id"]),
            candidate_id=str(detail["candidate_id"]),
        )
    except HandsFeetNailsFingernailGeometryError as exc:
        raise HighFidelityHfnContinuationError(f"HFN fingernail geometry authority is invalid: {exc}") from exc
    detail_receipt = Path(str(detail["receipt_path"])).expanduser().resolve()
    if (
        fingernail.get("source_detail_package_sha256") != detail.get("candidate_package_sha256")
        or fingernail.get("source_detail_receipt_sha256") != _sha256(detail_receipt)
        or fingernail.get("body_id") != detail.get("body_id")
        or fingernail.get("bodyrig_revision") != bodyrig_revision
        or fingernail.get("active_basecolor_sha256") != detail.get("candidate_basecolor_sha256")
        or fingernail.get("plate_count") != 10
    ):
        raise HighFidelityHfnContinuationError(
            "HFN fingernail geometry no longer binds the exact detail candidate/body/revision authority"
        )
    try:
        toenail = read_toenail_geometry_candidate(
            root,
            str(detail["person_id"]),
            body_revision=str(detail["body_revision"]),
            capture_id=str(detail["capture_id"]),
            candidate_id=str(detail["candidate_id"]),
        )
    except HandsFeetNailsToenailGeometryError as exc:
        raise HighFidelityHfnContinuationError(f"HFN toenail geometry authority is invalid: {exc}") from exc
    fingernail_receipt = Path(str(fingernail["receipt_path"])).expanduser().resolve()
    if (
        toenail.get("source_fingernail_package_sha256") != fingernail.get("geometry_package_sha256")
        or toenail.get("source_fingernail_receipt_sha256") != _sha256(fingernail_receipt)
        or toenail.get("source_detail_package_sha256") != detail.get("candidate_package_sha256")
        or toenail.get("body_id") != detail.get("body_id")
        or toenail.get("bodyrig_revision") != bodyrig_revision
        or toenail.get("active_basecolor_sha256") != detail.get("candidate_basecolor_sha256")
        or toenail.get("plate_count") != 10
    ):
        raise HighFidelityHfnContinuationError(
            "HFN toenail geometry no longer binds the exact fingernail/detail/body/revision authority"
        )
    return {
        **dict(detail),
        "candidate_package_sha256": str(toenail["geometry_package_sha256"]),
        "candidate_avatar_sha256": str(toenail["geometry_avatar_sha256"]),
        "package_path": str(toenail["package_path"]),
        "receipt_path": str(toenail["receipt_path"]),
        "detail_candidate_package_sha256": str(detail["candidate_package_sha256"]),
        "fingernail_geometry_package_sha256": str(fingernail["geometry_package_sha256"]),
        "fingernail_plate_count": int(fingernail["plate_count"]),
        "toenail_geometry_package_sha256": str(toenail["geometry_package_sha256"]),
        "toenail_plate_count": int(toenail["plate_count"]),
        "individual_middle_toe_landmarks_observed": bool(toenail["individual_middle_toe_landmarks_observed"]),
    }


def _validate_render_authority(
    render_dir: Path,
    *,
    candidate: Mapping[str, Any],
    bodyrig_revision: str,
) -> dict[str, Any]:
    manifest = render_dir / "snapshots" / "hands-feet-nails-render-set.json"
    try:
        render = validate_render_manifest(
            manifest,
            body_id=str(candidate["body_id"]),
            package_sha256=str(candidate["candidate_package_sha256"]),
        )
    except HandsFeetNailsAuthorityError as exc:
        raise HighFidelityHfnContinuationError(str(exc)) from exc
    render_manifest = render.get("manifest")
    if not isinstance(render_manifest, Mapping) or not _is_v1(render_manifest.get("version")):
        raise HighFidelityHfnContinuationError("HFN render-manifest version is not canonical v1")
    comparison_path = render_dir / "comparison-authority.json"
    authority_path = render_dir / "hands-feet-nails-render-authority.json"
    comparison = _read_json(comparison_path, label="HFN comparison authority")
    authority = _read_json(authority_path, label="HFN render authority")
    if set(comparison) != COMPARISON_FIELDS:
        raise HighFidelityHfnContinuationError("HFN comparison-authority fields are not canonical")
    package_sha = str(candidate["candidate_package_sha256"])
    if (
        comparison.get("format") != "bodyrig-fidelity-comparison-authority"
        or not _is_v1(comparison.get("version"))
        or comparison.get("authority") != "validated-package-comparison-only"
        or comparison.get("bodyrig_revision") != bodyrig_revision
        or comparison.get("package_sha256") != package_sha
        or comparison.get("physical_acceptance_authority") is not False
        or comparison.get("comparison_only") is not True
        or comparison.get("production_activation") is not False
    ):
        raise HighFidelityHfnContinuationError("HFN comparison-authority is stale or crossed its review-only boundary")
    if set(authority) != RENDER_AUTHORITY_FIELDS:
        raise HighFidelityHfnContinuationError("HFN render-authority fields are not canonical")
    if (
        authority.get("format") != "bodyrig-hands-feet-nails-render-authority"
        or not _is_v1(authority.get("version"))
        or authority.get("bodyrig_revision") != bodyrig_revision
        or authority.get("body_id") != candidate["body_id"]
        or authority.get("package_sha256") != package_sha
        or authority.get("runtime_manifest_sha256") != comparison.get("runtime_manifest_sha256")
        or authority.get("comparison_authority_sha256") != _sha256(comparison_path)
        or authority.get("render_manifest_sha256") != render["manifest_sha256"]
        or authority.get("render_region_sha256") != render["region_sha256"]
        or authority.get("comparison_only") is not True
        or authority.get("human_review_required") is not True
        or authority.get("production_activation") is not False
    ):
        raise HighFidelityHfnContinuationError("HFN render-authority is stale, mismatched or crossed its review-only boundary")
    return {
        "manifest_path": str(manifest),
        "manifest_sha256": render["manifest_sha256"],
        "region_sha256": dict(render["region_sha256"]),
        "render_authority_sha256": _sha256(authority_path),
    }


def inspect_hfn_continuation(
    *,
    root: Path,
    person_id: str,
    body_revision: str,
    bodyrig_revision: str,
    source_package_path: Path,
    source_package_sha256: str,
    render_dir: Path,
    human_review_dir: Path,
) -> dict[str, Any]:
    actions: dict[str, dict[str, Any]] = {}
    gates: list[dict[str, Any]] = []
    root = root.expanduser().resolve()
    source_package_path = source_package_path.expanduser().resolve()
    if not source_package_path.is_file() or _sha256(source_package_path) != source_package_sha256:
        gates.append(_gate(CANDIDATE_GATE, "invalid", reason="face-secondary package bytes changed before HFN continuation"))
        return {"gates": gates, "actions": actions, "package_path": source_package_path, "package_sha256": source_package_sha256}
    try:
        detail = _find_candidate(
            root,
            person_id=person_id,
            body_revision=body_revision,
            source_package_sha256=source_package_sha256,
            bodyrig_revision=bodyrig_revision,
        )
    except HighFidelityHfnContinuationError as exc:
        gates.append(_gate(CANDIDATE_GATE, "invalid", reason=str(exc)))
        return {"gates": gates, "actions": actions, "package_path": source_package_path, "package_sha256": source_package_sha256}
    if detail is None:
        command = (
            ".\\prepare-hands-feet-nails-detail-candidate.ps1 "
            f"-Root {_quote(root)} -PersonId {_quote(person_id)} -BodyRevision {_quote(body_revision)} "
            "-CaptureId <CAPTURE_ID> -UvEvidence <UV_EVIDENCE_PATH> "
            f"-PackagePath {_quote(source_package_path)}"
        )
        actions[CANDIDATE_GATE] = {
            "gate": CANDIDATE_GATE,
            "command": command,
            "operator_input_required": True,
            "reason": "Select the exact source-grounded HFN capture/UV evidence for this promoted package, then materialize its detail-bearing candidate.",
        }
        gates.append(_gate(CANDIDATE_GATE, "required", reason="no exact HFN detail candidate targets the face-secondary promoted package"))
        return {"gates": gates, "actions": actions, "package_path": source_package_path, "package_sha256": source_package_sha256}

    geometry_package, geometry_receipt = geometry_paths(
        root,
        str(detail["person_id"]),
        str(detail["body_revision"]),
        str(detail["capture_id"]),
        str(detail["candidate_id"]),
    )
    if not geometry_package.is_file() and not geometry_receipt.is_file():
        actions[CANDIDATE_GATE] = {
            "gate": CANDIDATE_GATE,
            "command": (
                ".\\prepare-hands-feet-nails-fingernail-geometry-candidate.ps1 "
                f"-Root {_quote(root)} -PersonId {_quote(person_id)} -BodyRevision {_quote(body_revision)} "
                f"-CaptureId {_quote(detail['capture_id'])} -CandidateId {_quote(detail['candidate_id'])}"
            ),
            "operator_input_required": False,
            "reason": "Materialize the source-bound skinned fingernail plate geometry on the exact HFN detail candidate before toenail materialization.",
        }
        gates.append(_gate(
            CANDIDATE_GATE,
            "required",
            reason="HFN detail candidate exists, but its exact fingernail geometry candidate has not been materialized",
            evidence={
                "candidate_id": detail["candidate_id"],
                "detail_candidate_package_sha256": detail["candidate_package_sha256"],
            },
        ))
        return {
            "gates": gates,
            "actions": actions,
            "package_path": Path(detail["package_path"]).resolve(),
            "package_sha256": str(detail["candidate_package_sha256"]),
            "candidate": detail,
        }
    if geometry_package.is_file() != geometry_receipt.is_file():
        gates.append(_gate(CANDIDATE_GATE, "invalid", reason="HFN fingernail geometry package/receipt authority is incomplete"))
        return {
            "gates": gates,
            "actions": actions,
            "package_path": Path(detail["package_path"]).resolve(),
            "package_sha256": str(detail["candidate_package_sha256"]),
            "candidate": detail,
        }
    try:
        fingernail = read_fingernail_geometry_candidate(
            root,
            str(detail["person_id"]),
            body_revision=str(detail["body_revision"]),
            capture_id=str(detail["capture_id"]),
            candidate_id=str(detail["candidate_id"]),
        )
    except HandsFeetNailsFingernailGeometryError as exc:
        gates.append(_gate(CANDIDATE_GATE, "invalid", reason=f"HFN fingernail geometry authority is invalid: {exc}"))
        return {"gates": gates, "actions": actions, "package_path": Path(detail["package_path"]).resolve(), "package_sha256": str(detail["candidate_package_sha256"]), "candidate": detail}

    toenail_package, toenail_receipt = toenail_geometry_paths(
        root,
        str(detail["person_id"]),
        str(detail["body_revision"]),
        str(detail["capture_id"]),
        str(detail["candidate_id"]),
    )
    if not toenail_package.is_file() and not toenail_receipt.is_file():
        actions[CANDIDATE_GATE] = {
            "gate": CANDIDATE_GATE,
            "command": (
                ".\\prepare-hands-feet-nails-toenail-geometry-candidate.ps1 "
                f"-Root {_quote(root)} -PersonId {_quote(person_id)} -BodyRevision {_quote(body_revision)} "
                f"-CaptureId {_quote(detail['capture_id'])} -CandidateId {_quote(detail['candidate_id'])}"
            ),
            "operator_input_required": False,
            "reason": "Materialize source-bound skinned toenail plate geometry on the exact fingernail-geometry package before any render or human review.",
        }
        gates.append(_gate(
            CANDIDATE_GATE,
            "required",
            reason="HFN fingernail geometry exists, but its exact toenail geometry candidate has not been materialized",
            evidence={
                "candidate_id": detail["candidate_id"],
                "detail_candidate_package_sha256": detail["candidate_package_sha256"],
                "fingernail_geometry_package_sha256": fingernail["geometry_package_sha256"],
                "fingernail_plate_count": fingernail["plate_count"],
            },
        ))
        return {
            "gates": gates,
            "actions": actions,
            "package_path": Path(str(fingernail["package_path"])).resolve(),
            "package_sha256": str(fingernail["geometry_package_sha256"]),
            "candidate": {**dict(detail), "fingernail_geometry_package_sha256": fingernail["geometry_package_sha256"], "fingernail_plate_count": fingernail["plate_count"]},
        }
    if toenail_package.is_file() != toenail_receipt.is_file():
        gates.append(_gate(CANDIDATE_GATE, "invalid", reason="HFN toenail geometry package/receipt authority is incomplete"))
        return {
            "gates": gates,
            "actions": actions,
            "package_path": Path(str(fingernail["package_path"])).resolve(),
            "package_sha256": str(fingernail["geometry_package_sha256"]),
            "candidate": detail,
        }
    try:
        candidate = _geometry_review_candidate(root, detail, bodyrig_revision=bodyrig_revision)
    except HighFidelityHfnContinuationError as exc:
        gates.append(_gate(CANDIDATE_GATE, "invalid", reason=str(exc)))
        return {
            "gates": gates,
            "actions": actions,
            "package_path": Path(detail["package_path"]).resolve(),
            "package_sha256": str(detail["candidate_package_sha256"]),
            "candidate": detail,
        }

    candidate_package = Path(candidate["package_path"]).resolve()
    candidate_sha = str(candidate["candidate_package_sha256"])
    gates.append(_gate(CANDIDATE_GATE, "pass", evidence={
        "candidate_id": candidate["candidate_id"],
        "capture_id": candidate["capture_id"],
        "candidate_package_sha256": candidate_sha,
        "detail_candidate_package_sha256": candidate["detail_candidate_package_sha256"],
        "fingernail_geometry_package_sha256": candidate["fingernail_geometry_package_sha256"],
        "fingernail_plate_count": candidate["fingernail_plate_count"],
        "toenail_geometry_package_sha256": candidate["toenail_geometry_package_sha256"],
        "toenail_plate_count": candidate["toenail_plate_count"],
        "individual_middle_toe_landmarks_observed": candidate["individual_middle_toe_landmarks_observed"],
        "source_package_sha256": candidate["source_package_sha256"],
        "clean_appearance_ab": candidate["clean_appearance_ab"],
    }))

    manifest_path = render_dir / "snapshots" / "hands-feet-nails-render-set.json"
    if not render_dir.exists():
        actions[RENDER_GATE] = {
            "gate": RENDER_GATE,
            "command": (
                ".\\prepare-hands-feet-nails-render-review.ps1 "
                f"-PackagePath {_quote(candidate_package)} -OutputDir {_quote(render_dir)}"
            ),
            "operator_input_required": False,
            "reason": "Render the canonical four HFN detail views from the exact fingernail+toenail geometry candidate package.",
        }
        gates.append(_gate(RENDER_GATE, "required", reason="canonical HFN fingernail+toenail geometry render review has not been created"))
        return {"gates": gates, "actions": actions, "package_path": candidate_package, "package_sha256": candidate_sha, "candidate": candidate}
    try:
        render = _validate_render_authority(
            render_dir,
            candidate=candidate,
            bodyrig_revision=bodyrig_revision,
        )
    except HighFidelityHfnContinuationError as exc:
        gates.append(_gate(RENDER_GATE, "invalid", reason=str(exc)))
        return {"gates": gates, "actions": actions, "package_path": candidate_package, "package_sha256": candidate_sha, "candidate": candidate}
    gates.append(_gate(RENDER_GATE, "pass", evidence={
        "render_manifest_sha256": render["manifest_sha256"],
        "render_authority_sha256": render["render_authority_sha256"],
        "fingernail_geometry_package_sha256": candidate["fingernail_geometry_package_sha256"],
        "toenail_geometry_package_sha256": candidate["toenail_geometry_package_sha256"],
    }))

    if not human_review_dir.exists():
        actions[HUMAN_GATE] = {
            "gate": HUMAN_GATE,
            "command": (
                ".\\record-high-fidelity-hfn-review.ps1 "
                f"-Root {_quote(root)} -PersonId {_quote(person_id)} -BodyRevision {_quote(body_revision)} "
                f"-CaptureId {_quote(candidate['capture_id'])} -CandidateId {_quote(candidate['candidate_id'])} "
                f"-RenderDir {_quote(render_dir)} -OutputDir {_quote(human_review_dir)} "
                "-ConfirmDetailChecklist -QualityNote <QUALITY_NOTE>"
            ),
            "operator_input_required": True,
            "reason": "Review the exact fingernail+toenail geometry candidate against the four canonical HFN views and source closeups, then confirm every M2 checklist item with a real quality note.",
        }
        gates.append(_gate(HUMAN_GATE, "required", reason="geometry-package-bound HFN human review has not been recorded"))
        return {"gates": gates, "actions": actions, "package_path": candidate_package, "package_sha256": candidate_sha, "candidate": candidate}
    try:
        review = read_review(
            human_review_dir,
            root=root,
            person_id=person_id,
            body_revision=body_revision,
            capture_id=str(candidate["capture_id"]),
            candidate_id=str(candidate["candidate_id"]),
            render_manifest_path=manifest_path,
            bodyrig_revision=bodyrig_revision,
        )
    except HighFidelityHfnReviewError as exc:
        gates.append(_gate(HUMAN_GATE, "invalid", reason=str(exc)))
        return {"gates": gates, "actions": actions, "package_path": candidate_package, "package_sha256": candidate_sha, "candidate": candidate}
    gates.append(_gate(HUMAN_GATE, "pass", evidence={
        "review_id": review["review_id"],
        "candidate_package_sha256": review["candidate_package_sha256"],
        "render_manifest_sha256": review["render_manifest_sha256"],
    }))
    return {
        "gates": gates,
        "actions": actions,
        "package_path": candidate_package,
        "package_sha256": candidate_sha,
        "candidate": candidate,
        "review": review,
    }
