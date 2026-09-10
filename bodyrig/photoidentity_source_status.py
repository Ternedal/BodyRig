from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoidentity_authority import PhotoIdentityAuthorityError, validate_authoritative_bundle
from .photoidentity_registry import (
    DIRNAME as REGISTRY_DIRNAME,
    PhotoIdentityRegistryError,
    _job_authority,
    require_body_job_photoidentity_evidence,
)
from .photoidentity_source_chain import PhotoIdentitySourceChainError, validate_registration_source_chain

FORMAT = "bodyrig-photoidentity-source-status"
VERSION = 1


class PhotoIdentitySourceStatusError(RuntimeError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentitySourceStatusError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentitySourceStatusError(f"{label} must be a JSON object")
    return value


def _pair_state(paths: tuple[Path, ...], *, label: str) -> bool:
    present = [path.exists() for path in paths]
    if any(present) and not all(present):
        raise PhotoIdentitySourceStatusError(f"partial {label} state exists; refusing ambiguous source authority")
    return all(present)


def _stage(
    *,
    sweep_root: Path,
    base_report: Mapping[str, Any],
    name: str,
    next_action: str,
    human_review_required: bool = False,
    final_report: Mapping[str, Any] | None = None,
    body_job_id: str | None = None,
) -> dict[str, Any]:
    report = dict(final_report or base_report)
    return {
        "format": FORMAT,
        "version": VERSION,
        "stage": name,
        "next_action": next_action,
        "performer_id": str(base_report["performer_id"]),
        "bodyrig_revision": str(base_report["bodyrig_revision"]),
        "baseline_source_manifest_sha256": str(base_report["baseline_source_manifest_sha256"]),
        "sweep_root": str(sweep_root),
        "body_job_id": body_job_id,
        "source_evidence_sufficient": bool(report.get("source_evidence_sufficient", False)),
        "reconstruction_source_permitted": bool(report.get("reconstruction_permitted", False)),
        "human_review_required": bool(human_review_required),
        "avatar_render_permitted": name == "registered",
        "generic_guessing_permitted": False,
        "production_activation": False,
    }


def inspect_source_status(
    sweep_root: str | Path,
    *,
    body_job_id: str | None = None,
) -> dict[str, Any]:
    root = Path(sweep_root).expanduser().resolve()
    if not root.is_dir():
        raise PhotoIdentitySourceStatusError("photoidentity sweep root is missing")

    base_observations = root / "human-parsing-evidence" / "photoidentity-observations.json"
    base_report_path = root / "human-parsing-evidence" / "photoidentity-evidence.json"
    if not _pair_state((base_observations, base_report_path), label="human-parsing evidence"):
        raise PhotoIdentitySourceStatusError(
            "photoidentity sweep has no completed OpenPose/SCHP evidence; run collect-photoidentity-evidence.ps1 first"
        )
    try:
        base_report = validate_authoritative_bundle(base_report_path, base_observations, require_sufficient=False)
    except PhotoIdentityAuthorityError as exc:
        raise PhotoIdentitySourceStatusError(f"base photoidentity evidence is invalid: {exc}") from exc

    nail_discovery = root / "nail-source-candidates.json"
    nail_private_index = root / "private-nail-source-candidates" / "private-candidate-index.json"
    nail_receipt = root / "photoidentity-nail-source-attestation.json"
    nail_observations = root / "nail-attested-evidence" / "photoidentity-observations.json"
    nail_report_path = root / "nail-attested-evidence" / "photoidentity-evidence.json"
    nail_review_index = root / "private-nail-source-review" / "review-index.json"

    if nail_receipt.exists() and not _pair_state(
        (nail_discovery, nail_private_index, nail_receipt, nail_observations, nail_report_path),
        label="nail attestation",
    ):
        raise AssertionError("unreachable")
    if not nail_receipt.exists():
        if nail_observations.exists() or nail_report_path.exists():
            raise PhotoIdentitySourceStatusError("nail-attested evidence exists without its human receipt")
        if not nail_discovery.exists():
            if nail_private_index.exists() or nail_review_index.exists():
                raise PhotoIdentitySourceStatusError("private nail state exists without public discovery authority")
            return _stage(
                sweep_root=root,
                base_report=base_report,
                name="nail-discovery",
                next_action="discover_nail_sources",
            )
        if not nail_private_index.is_file():
            raise PhotoIdentitySourceStatusError("nail discovery exists without its private exact-source index")
        if not nail_review_index.exists():
            return _stage(
                sweep_root=root,
                base_report=base_report,
                name="nail-review-prepare",
                next_action="prepare_nail_source_review",
            )
        return _stage(
            sweep_root=root,
            base_report=base_report,
            name="nail-human-review",
            next_action="record_complete_nail_attestation_after_source_review",
            human_review_required=True,
        )

    nail_receipt_value = _read_json(nail_receipt, label="Nail source attestation receipt")
    if set(nail_receipt_value.get("attested_domains") or []) != {"fingernails_detail", "toenails_detail"}:
        raise PhotoIdentitySourceStatusError(
            "partial create-only nail attestation is noncanonical; complete fingernails and toenails must be attested atomically"
        )
    try:
        nail_report = validate_authoritative_bundle(nail_report_path, nail_observations, require_sufficient=False)
    except PhotoIdentityAuthorityError as exc:
        raise PhotoIdentitySourceStatusError(f"nail-attested evidence is invalid: {exc}") from exc
    for field in ("performer_id", "bodyrig_revision", "baseline_source_manifest_sha256"):
        if str(nail_report.get(field) or "") != str(base_report.get(field) or ""):
            raise PhotoIdentitySourceStatusError(f"nail evidence changed base authority: {field}")

    anatomy_discovery = root / "anatomy-source-candidates.json"
    anatomy_private_index = root / "private-anatomy-source-candidates" / "private-candidate-index.json"
    anatomy_receipt = root / "photoidentity-anatomy-source-attestation.json"
    anatomy_observations = root / "anatomy-attested-evidence" / "photoidentity-observations.json"
    anatomy_report_path = root / "anatomy-attested-evidence" / "photoidentity-evidence.json"
    anatomy_review_index = root / "private-anatomy-source-review" / "review-index.json"

    if anatomy_receipt.exists() and not _pair_state(
        (anatomy_discovery, anatomy_private_index, anatomy_receipt, anatomy_observations, anatomy_report_path),
        label="anatomy attestation",
    ):
        raise AssertionError("unreachable")
    if not anatomy_receipt.exists():
        if anatomy_observations.exists() or anatomy_report_path.exists():
            raise PhotoIdentitySourceStatusError("anatomy-attested evidence exists without its human receipt")
        if not anatomy_discovery.exists():
            if anatomy_private_index.exists() or anatomy_review_index.exists():
                raise PhotoIdentitySourceStatusError("private anatomy state exists without public discovery authority")
            return _stage(
                sweep_root=root,
                base_report=base_report,
                final_report=nail_report,
                name="anatomy-discovery",
                next_action="discover_rear_torso_waist_sources",
            )
        if not anatomy_private_index.is_file():
            raise PhotoIdentitySourceStatusError("anatomy discovery exists without its private exact-source index")
        if not anatomy_review_index.exists():
            return _stage(
                sweep_root=root,
                base_report=base_report,
                final_report=nail_report,
                name="anatomy-review-prepare",
                next_action="prepare_anatomy_source_review",
            )
        return _stage(
            sweep_root=root,
            base_report=base_report,
            final_report=nail_report,
            name="anatomy-human-review",
            next_action="record_atomic_anatomy_attestation_after_source_review",
            human_review_required=True,
        )

    try:
        chain = validate_registration_source_chain(
            anatomy_report_path,
            anatomy_observations,
            expected_performer_id=str(base_report["performer_id"]),
            expected_bodyrig_revision=str(base_report["bodyrig_revision"]),
            expected_baseline_source_manifest_sha256=str(base_report["baseline_source_manifest_sha256"]),
        )
    except PhotoIdentitySourceChainError as exc:
        raise PhotoIdentitySourceStatusError(f"final human source chain is invalid: {exc}") from exc
    final_report = dict(chain["report"])

    normalized_job_id = str(body_job_id or "").strip() or None
    if normalized_job_id is None:
        return _stage(
            sweep_root=root,
            base_report=base_report,
            final_report=final_report,
            name="ready-for-registration",
            next_action="register_source_authority_for_body_job",
        )

    try:
        job, _, _, job_root, _ = _job_authority(normalized_job_id)
    except PhotoIdentityRegistryError as exc:
        raise PhotoIdentitySourceStatusError(f"body-job authority is invalid: {exc}") from exc
    registry_root = job_root / REGISTRY_DIRNAME
    if not registry_root.exists():
        return _stage(
            sweep_root=root,
            base_report=base_report,
            final_report=final_report,
            body_job_id=normalized_job_id,
            name="ready-for-registration",
            next_action="register_source_authority_for_body_job",
        )
    try:
        require_body_job_photoidentity_evidence(str(job["person_id"]), normalized_job_id)
    except PhotoIdentityRegistryError as exc:
        raise PhotoIdentitySourceStatusError(f"registered photoidentity authority is invalid: {exc}") from exc
    return _stage(
        sweep_root=root,
        base_report=base_report,
        final_report=final_report,
        body_job_id=normalized_job_id,
        name="registered",
        next_action="high_fidelity_preview_gate_may_be_evaluated",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route the fail-closed BodyRig photoidentity source-sufficiency workflow.")
    parser.add_argument("--sweep-root", required=True)
    parser.add_argument("--body-job-id", default=None)
    args = parser.parse_args(argv)
    try:
        result = inspect_source_status(args.sweep_root, body_job_id=args.body_job_id)
    except (OSError, ValueError, PhotoIdentitySourceStatusError) as exc:
        print(f"BodyRig photoidentity source status: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
