from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .fine_identity_application import (
    FineIdentityApplicationError,
    REQUIRED_DOMAINS,
    build_application,
    validate_application,
)
from .high_fidelity_package_audit import (
    HighFidelityPackageAuditError,
    audit_high_fidelity_package,
)
from .package import MRBodyError, validate_package
from .photoidentity_fine_identity_attestation import (
    PhotoIdentityFineIdentityAttestationError,
    read_attestation,
)
from .photoidentity_fine_identity_reconstruction import (
    PhotoIdentityFineIdentityReconstructionError,
    _bodyrig_metadata,
    _package_avatar,
    _sha256_file,
    _source_authority,
    read_reconstruction_workspace,
)

FORMAT = "bodyrig-photoidentity-fine-identity-package-application"
VERSION = 1
PACKAGE_NAME = "applied.mrbody"
RECEIPT_NAME = "application.json"


class PhotoIdentityFineIdentityPackageError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _selected_references(attestation: Mapping[str, Any]) -> dict[str, list[str]]:
    selected = attestation.get("selected_evidence")
    if not isinstance(selected, list):
        raise PhotoIdentityFineIdentityPackageError(
            "fine-identity attestation selected evidence is invalid"
        )
    grouped: dict[str, list[str]] = {domain: [] for domain in REQUIRED_DOMAINS}
    for item in selected:
        if not isinstance(item, Mapping):
            raise PhotoIdentityFineIdentityPackageError(
                "fine-identity selected evidence entry is invalid"
            )
        domain = str(item.get("domain") or "")
        reference = str(item.get("reference") or "").strip()
        if domain not in grouped or not reference or reference in grouped[domain]:
            raise PhotoIdentityFineIdentityPackageError(
                "fine-identity selected evidence identity is invalid"
            )
        grouped[domain].append(reference)
    if any(len(grouped[domain]) < 2 for domain in REQUIRED_DOMAINS):
        raise PhotoIdentityFineIdentityPackageError(
            "fine-identity selected evidence coverage is incomplete"
        )
    return grouped


def _application_domains(
    *,
    attestation: Mapping[str, Any],
    reconstruction_references: Mapping[str, Any],
    dental_references: list[str],
) -> dict[str, dict[str, Any]]:
    grouped = _selected_references(attestation)
    oral = grouped["oral_teeth_detail"]
    if oral != list(dental_references):
        raise PhotoIdentityFineIdentityPackageError(
            "terminal fine-identity application lost exact source-derived dental reference lineage"
        )
    for domain in REQUIRED_DOMAINS:
        if domain == "oral_teeth_detail":
            continue
        observed = reconstruction_references.get(domain)
        if not isinstance(observed, list) or observed != grouped[domain]:
            raise PhotoIdentityFineIdentityPackageError(
                f"terminal fine-identity application lost exact reconstruction lineage for {domain}"
            )
    return {
        domain: {
            "sourceEvidenceCount": len(grouped[domain]),
            "geometryApplied": bool(REQUIRED_DOMAINS[domain]["geometry"]),
            "appearanceApplied": bool(REQUIRED_DOMAINS[domain]["appearance"]),
        }
        for domain in REQUIRED_DOMAINS
    }


def _embed_application(
    *,
    source_avatar: bytes,
    candidate_avatar: bytes,
    requirement: Mapping[str, Any],
    domains: Mapping[str, Mapping[str, Any]],
) -> tuple[bytes, dict[str, Any]]:
    source_metadata = _bodyrig_metadata(source_avatar)
    candidate_metadata = _bodyrig_metadata(candidate_avatar)
    if candidate_metadata != source_metadata:
        raise PhotoIdentityFineIdentityPackageError(
            "fine-identity candidate authority metadata drifted before package application"
        )
    try:
        application = build_application(
            requirement=requirement,
            source_avatar_vrm=source_avatar,
            candidate_avatar_vrm=candidate_avatar,
            domains=domains,
        )
        document, binary = _read_glb(candidate_avatar)
    except (FineIdentityApplicationError, PbrMaterialError) as exc:
        raise PhotoIdentityFineIdentityPackageError(str(exc)) from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, Mapping) else None
    if not isinstance(bodyrig, dict):
        raise PhotoIdentityFineIdentityPackageError(
            "fine-identity candidate lacks mutable BodyRig metadata"
        )
    if bodyrig.get("fineIdentityApplication") is not None:
        raise PhotoIdentityFineIdentityPackageError(
            "fine-identity candidate already carries application authority"
        )
    bodyrig["fineIdentityApplication"] = application
    try:
        applied = _write_glb(document, binary)
        validate_application(
            application,
            requirement=requirement,
            avatar_vrm=applied,
        )
    except (FineIdentityApplicationError, PbrMaterialError) as exc:
        raise PhotoIdentityFineIdentityPackageError(
            f"embedded fine-identity application is invalid: {exc}"
        ) from exc
    return applied, application


def _rewrite_package(source: Path, destination: Path, *, avatar_vrm: bytes) -> None:
    try:
        with zipfile.ZipFile(source, "r") as archive:
            order = [info.filename for info in archive.infolist()]
            payload = {name: archive.read(name) for name in order}
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise PhotoIdentityFineIdentityPackageError(
            "could not read source HFN package"
        ) from exc
    if "avatar.vrm" not in payload or "checksums.json" not in payload:
        raise PhotoIdentityFineIdentityPackageError(
            "source HFN package lacks canonical avatar/checksum files"
        )
    payload["avatar.vrm"] = avatar_vrm
    checksum_names = set(order) - {"manifest.json", "checksums.json"}
    payload["checksums.json"] = json.dumps(
        {
            name: hashlib.sha256(payload[name]).hexdigest()
            for name in checksum_names
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    try:
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in order:
                archive.writestr(name, payload[name])
    except FileExistsError as exc:
        raise PhotoIdentityFineIdentityPackageError(
            "fine-identity applied package is create-only"
        ) from exc
    except OSError as exc:
        raise PhotoIdentityFineIdentityPackageError(
            "could not write fine-identity applied package"
        ) from exc


def materialize_application(
    *,
    source_package_path: Path,
    reconstruction_workspace: Path,
    config_path: Path,
    attestation_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    source_package = source_package_path.expanduser().resolve()
    output = output_dir.expanduser().resolve()
    if output.exists():
        raise PhotoIdentityFineIdentityPackageError(
            f"fine-identity package output already exists: {output}"
        )

    try:
        reconstruction = read_reconstruction_workspace(
            workspace=reconstruction_workspace,
            config_path=config_path,
        )
    except PhotoIdentityFineIdentityReconstructionError as exc:
        raise PhotoIdentityFineIdentityPackageError(str(exc)) from exc
    prepared = reconstruction["prepared"]
    if _sha256_file(source_package) != prepared["source_package_sha256"]:
        raise PhotoIdentityFineIdentityPackageError(
            "source HFN package bytes do not match reconstruction input authority"
        )

    try:
        requirement, source_avatar, body_id = _source_authority(source_package)
        validated_source = validate_package(source_package)
    except (PhotoIdentityFineIdentityReconstructionError, MRBodyError) as exc:
        raise PhotoIdentityFineIdentityPackageError(str(exc)) from exc
    if body_id != prepared["canonical_body_id"] or str(validated_source.manifest["id"]) != body_id:
        raise PhotoIdentityFineIdentityPackageError(
            "fine-identity reconstruction targets a different canonical body"
        )
    if _sha256_bytes(source_avatar) != prepared["source_avatar_sha256"]:
        raise PhotoIdentityFineIdentityPackageError(
            "source avatar bytes do not match reconstruction input authority"
        )

    attestation_file = attestation_path.expanduser().resolve()
    if _sha256_file(attestation_file) != requirement["fineIdentityAttestationSha256"]:
        raise PhotoIdentityFineIdentityPackageError(
            "fine-identity attestation bytes do not match package requirement"
        )
    try:
        attestation = read_attestation(
            attestation_file,
            expected_bodyrig_revision=requirement["bodyrigRevision"],
        )
    except PhotoIdentityFineIdentityAttestationError as exc:
        raise PhotoIdentityFineIdentityPackageError(str(exc)) from exc
    if str(attestation.get("marker_inventory_sha256") or "").lower() != prepared["marker_inventory_sha256"]:
        raise PhotoIdentityFineIdentityPackageError(
            "distinctive-marker inventory lineage differs from reconstruction input"
        )

    try:
        source_audit = audit_high_fidelity_package(source_package)
    except HighFidelityPackageAuditError as exc:
        raise PhotoIdentityFineIdentityPackageError(str(exc)) from exc
    face_payload = (
        source_audit.get("render_payloads", {})
        .get("face_secondary", {})
    )
    source_dental = face_payload.get("source_dental") if isinstance(face_payload, Mapping) else None
    dental_refs = source_dental.get("source_references") if isinstance(source_dental, Mapping) else None
    if not isinstance(dental_refs, list):
        raise PhotoIdentityFineIdentityPackageError(
            "source package lacks canonical source-derived dental lineage"
        )

    domains = _application_domains(
        attestation=attestation,
        reconstruction_references=prepared["source_references"],
        dental_references=[str(item) for item in dental_refs],
    )
    candidate_path = Path(str(reconstruction["candidate_vrm_path"])).expanduser().resolve()
    candidate_avatar = candidate_path.read_bytes()
    applied_avatar, application = _embed_application(
        source_avatar=source_avatar,
        candidate_avatar=candidate_avatar,
        requirement=requirement,
        domains=domains,
    )

    output.mkdir(parents=True, exist_ok=False)
    package_path = output / PACKAGE_NAME
    receipt_path = output / RECEIPT_NAME
    try:
        _rewrite_package(source_package, package_path, avatar_vrm=applied_avatar)
        try:
            validated = validate_package(package_path)
            audit = audit_high_fidelity_package(package_path)
        except (MRBodyError, HighFidelityPackageAuditError) as exc:
            raise PhotoIdentityFineIdentityPackageError(
                f"fine-identity applied package failed strict audit: {exc}"
            ) from exc
        components = audit.get("components")
        if (
            str(validated.manifest["id"]) != body_id
            or audit.get("canonical_body_id") != body_id
            or audit.get("fine_identity_required") is not True
            or audit.get("fine_identity_ready") is not True
            or audit.get("high_fidelity_ready") is not True
            or audit.get("top_level_blockers") != []
            or not isinstance(components, Mapping)
            or not components
            or any(value != "complete" for value in components.values())
            or audit.get("production_ready") is not False
        ):
            raise PhotoIdentityFineIdentityPackageError(
                "fine-identity applied package did not reach canonical non-production readiness"
            )
        audit_fine = audit.get("fine_identity")
        if (
            not isinstance(audit_fine, Mapping)
            or audit_fine.get("application") != application
        ):
            raise PhotoIdentityFineIdentityPackageError(
                "final package audit did not preserve exact fine-identity application authority"
            )

        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "canonical_body_id": body_id,
            "operator_bodyrig_revision": prepared["operator_bodyrig_revision"],
            "requirement_bodyrig_revision": requirement["bodyrigRevision"],
            "fine_identity_authority_sha256": requirement["fineIdentityAuthoritySha256"],
            "fine_identity_attestation_sha256": requirement["fineIdentityAttestationSha256"],
            "source_package_sha256": prepared["source_package_sha256"],
            "reconstruction_input_sha256": _sha256_file(
                Path(str(reconstruction["input_manifest_path"]))
            ),
            "reconstruction_result_sha256": _sha256_file(
                Path(str(reconstruction["result_path"]))
            ),
            "candidate_vrm_sha256": _sha256_file(candidate_path),
            "applied_package_sha256": _sha256_file(package_path),
            "domains": domains,
            "application": application,
            "source_grounded": True,
            "generative": False,
            "human_review_required": True,
            "package_application_authority": True,
            "production_activation": False,
        }
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if json.loads(receipt_path.read_text(encoding="utf-8")) != receipt:
            raise PhotoIdentityFineIdentityPackageError(
                "fine-identity application receipt did not round-trip canonically"
            )
        return {
            **receipt,
            "package_path": str(package_path),
            "receipt_path": str(receipt_path),
            "audit": audit,
        }
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise
