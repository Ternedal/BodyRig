from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .fine_identity_application import (
    FineIdentityApplicationError,
    build_application,
    validate_application,
    validate_requirement,
)
from .package import MRBodyError, validate_package

FORMAT = "bodyrig-fine-identity-package-certification"
VERSION = 1
POLICY_REVISION = "bodyrig-fine-identity-package-certification-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
CERT_RE = re.compile(r"^finecert-[0-9a-f]{32}$")

TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "certification_id",
    "body_id",
    "bodyrig_revision",
    "source_package_sha256",
    "uncertified_candidate_package_sha256",
    "certified_package_sha256",
    "source_avatar_sha256",
    "uncertified_candidate_avatar_sha256",
    "certified_avatar_sha256",
    "fine_identity_authority_sha256",
    "fine_identity_attestation_sha256",
    "application_sha256",
    "domains",
    "source_grounded",
    "generative",
    "package_application_authority",
    "geometry_modified",
    "appearance_modified",
    "rig_preserved",
    "human_review_required",
    "production_activation",
}


class FineIdentityPackageCertificationError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise FineIdentityPackageCertificationError(f"required package input is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise FineIdentityPackageCertificationError(f"{label} is not a canonical SHA-256")
    return text


def _revision(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(text):
        raise FineIdentityPackageCertificationError("fine-identity certification BodyRig revision is not canonical")
    return text


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _read_json_bytes(value: bytes, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FineIdentityPackageCertificationError(f"{label} is unreadable JSON") from exc
    if not isinstance(parsed, dict):
        raise FineIdentityPackageCertificationError(f"{label} must be a JSON object")
    return parsed


def _package_bundle(path: str | os.PathLike[str], *, label: str) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    try:
        validated = validate_package(resolved)
        package_bytes = resolved.read_bytes()
        with zipfile.ZipFile(resolved, "r") as archive:
            order = [item.filename for item in archive.infolist()]
            payload = {name: archive.read(name) for name in order}
    except (MRBodyError, OSError, zipfile.BadZipFile, KeyError) as exc:
        raise FineIdentityPackageCertificationError(f"{label} is not a valid .mrbody package") from exc
    return {
        "path": resolved,
        "validated": validated,
        "package_sha256": _sha256_bytes(package_bytes),
        "order": order,
        "payload": payload,
        "avatar": payload["avatar.vrm"],
        "avatar_sha256": _sha256_bytes(payload["avatar.vrm"]),
    }


def _requirement_from_avatar(
    avatar_vrm: bytes,
    *,
    label: str,
    reject_existing_application: bool,
) -> tuple[dict[str, Any], dict[str, Any], bytes, dict[str, Any]]:
    try:
        document, binary = _read_glb(avatar_vrm)
    except PbrMaterialError as exc:
        raise FineIdentityPackageCertificationError(f"{label} VRM is unreadable: {exc}") from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise FineIdentityPackageCertificationError(f"{label} lacks BodyRig VRM metadata")
    requirement_raw = bodyrig.get("fineIdentityRequirement")
    if not isinstance(requirement_raw, Mapping):
        raise FineIdentityPackageCertificationError(f"{label} lacks a fine-identity requirement")
    try:
        requirement = validate_requirement(requirement_raw)
    except FineIdentityApplicationError as exc:
        raise FineIdentityPackageCertificationError(f"{label} fine-identity requirement is invalid: {exc}") from exc
    if reject_existing_application and bodyrig.get("fineIdentityApplication") is not None:
        raise FineIdentityPackageCertificationError(f"{label} already carries a fine-identity application")
    return document, bodyrig, binary, requirement


def _assert_package_lineage(source: Mapping[str, Any], candidate: Mapping[str, Any]) -> None:
    source_validated = source["validated"]
    candidate_validated = candidate["validated"]
    if source_validated.manifest.get("id") != candidate_validated.manifest.get("id"):
        raise FineIdentityPackageCertificationError("fine-identity candidate changed canonical body id")
    if source_validated.bodyprint != candidate_validated.bodyprint:
        raise FineIdentityPackageCertificationError("fine-identity candidate changed bodyprint authority")
    source_names = set(source["order"])
    candidate_names = set(candidate["order"])
    if source_names != candidate_names:
        raise FineIdentityPackageCertificationError("fine-identity candidate changed package payload set")
    for name in sorted(source_names - {"avatar.vrm", "checksums.json"}):
        if source["payload"][name] != candidate["payload"][name]:
            raise FineIdentityPackageCertificationError(
                f"fine-identity candidate changed protected package payload: {name}"
            )
    if source["package_sha256"] == candidate["package_sha256"]:
        raise FineIdentityPackageCertificationError("fine-identity candidate package bytes are unchanged")


def _embed_application(
    avatar_vrm: bytes,
    *,
    expected_requirement: Mapping[str, Any],
    application: Mapping[str, Any],
) -> bytes:
    document, bodyrig, binary, requirement = _requirement_from_avatar(
        avatar_vrm,
        label="Uncertified fine-identity candidate",
        reject_existing_application=True,
    )
    if requirement != dict(expected_requirement):
        raise FineIdentityPackageCertificationError(
            "fine-identity candidate requirement differs from exact source requirement"
        )
    try:
        validated_application = validate_application(
            application,
            requirement=requirement,
            avatar_vrm=avatar_vrm,
        )
    except FineIdentityApplicationError as exc:
        raise FineIdentityPackageCertificationError(str(exc)) from exc
    bodyrig["fineIdentityApplication"] = validated_application
    try:
        return _write_glb(document, binary)
    except PbrMaterialError as exc:
        raise FineIdentityPackageCertificationError(str(exc)) from exc


def _rewrite_package(candidate: Mapping[str, Any], destination: Path, *, avatar_vrm: bytes) -> None:
    payload = dict(candidate["payload"])
    order = list(candidate["order"])
    payload["avatar.vrm"] = avatar_vrm
    checksum_names = set(order) - {"manifest.json", "checksums.json"}
    payload["checksums.json"] = json.dumps(
        {name: _sha256_bytes(payload[name]) for name in checksum_names},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    if destination.exists():
        raise FineIdentityPackageCertificationError(
            f"refusing to overwrite certified fine-identity package: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in order:
                archive.writestr(name, payload[name])
    except FileExistsError as exc:
        raise FineIdentityPackageCertificationError(
            f"refusing to overwrite certified fine-identity package: {destination}"
        ) from exc
    except OSError as exc:
        raise FineIdentityPackageCertificationError("could not write certified fine-identity package") from exc


def _certification_id(
    *,
    source_package_sha256: str,
    candidate_package_sha256: str,
    attestation_sha256: str,
    application_sha256: str,
) -> str:
    value = {
        "source_package_sha256": source_package_sha256,
        "candidate_package_sha256": candidate_package_sha256,
        "attestation_sha256": attestation_sha256,
        "application_sha256": application_sha256,
        "policy_revision": POLICY_REVISION,
    }
    return "finecert-" + hashlib.sha256(_canonical_json(value)).hexdigest()[:32]


def validate_certification_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise FineIdentityPackageCertificationError("fine-identity certification fields are not canonical")
    version = value.get("version")
    if (
        value.get("format") != FORMAT
        or isinstance(version, bool)
        or version != VERSION
        or value.get("policy_revision") != POLICY_REVISION
    ):
        raise FineIdentityPackageCertificationError("fine-identity certification format/version/policy mismatch")
    certification_id = str(value.get("certification_id") or "").strip().lower()
    if not CERT_RE.fullmatch(certification_id):
        raise FineIdentityPackageCertificationError("fine-identity certification id is invalid")
    body_id = str(value.get("body_id") or "").strip()
    if not body_id:
        raise FineIdentityPackageCertificationError("fine-identity certification body id is missing")
    revision = _revision(value.get("bodyrig_revision"))
    for field in (
        "source_package_sha256",
        "uncertified_candidate_package_sha256",
        "certified_package_sha256",
        "source_avatar_sha256",
        "uncertified_candidate_avatar_sha256",
        "certified_avatar_sha256",
        "fine_identity_authority_sha256",
        "fine_identity_attestation_sha256",
        "application_sha256",
    ):
        _sha(value.get(field), label=field.replace("_", " "))
    domains = value.get("domains")
    if not isinstance(domains, Mapping) or not domains:
        raise FineIdentityPackageCertificationError("fine-identity certification domains are missing")
    if (
        value.get("source_grounded") is not True
        or value.get("package_application_authority") is not True
        or value.get("geometry_modified") is not True
        or value.get("appearance_modified") is not True
        or value.get("rig_preserved") is not True
        or value.get("human_review_required") is not True
        or value.get("generative") is not False
        or value.get("production_activation") is not False
    ):
        raise FineIdentityPackageCertificationError(
            "fine-identity certification crossed its source/review/production boundary"
        )
    if value["source_package_sha256"] == value["uncertified_candidate_package_sha256"]:
        raise FineIdentityPackageCertificationError("fine-identity certification has unchanged candidate package")
    if value["uncertified_candidate_package_sha256"] == value["certified_package_sha256"]:
        raise FineIdentityPackageCertificationError("fine-identity certification did not embed application metadata")
    return {**dict(value), "certification_id": certification_id, "bodyrig_revision": revision}


def certify_package(
    *,
    source_package_path: str | os.PathLike[str],
    candidate_package_path: str | os.PathLike[str],
    attestation_path: str | os.PathLike[str],
    output_package_path: str | os.PathLike[str],
    receipt_path: str | os.PathLike[str],
    bodyrig_revision: str,
    domain_application: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    revision = _revision(bodyrig_revision)
    source = _package_bundle(source_package_path, label="Source fine-identity package")
    candidate = _package_bundle(candidate_package_path, label="Uncertified fine-identity candidate")
    _assert_package_lineage(source, candidate)

    _source_document, _source_bodyrig, _source_binary, source_requirement = _requirement_from_avatar(
        source["avatar"],
        label="Source fine-identity package",
        reject_existing_application=True,
    )
    _candidate_document, _candidate_bodyrig, _candidate_binary, candidate_requirement = _requirement_from_avatar(
        candidate["avatar"],
        label="Uncertified fine-identity candidate",
        reject_existing_application=True,
    )
    if source_requirement != candidate_requirement:
        raise FineIdentityPackageCertificationError(
            "fine-identity candidate requirement differs from exact source requirement"
        )
    if source_requirement["bodyrigRevision"] != revision:
        raise FineIdentityPackageCertificationError(
            "fine-identity certification revision differs from embedded requirement"
        )

    attestation_file = Path(attestation_path).expanduser().resolve()
    try:
        attestation_bytes = attestation_file.read_bytes()
    except OSError as exc:
        raise FineIdentityPackageCertificationError("fine-identity attestation is unreadable") from exc
    attestation = _read_json_bytes(attestation_bytes, label="Fine-identity attestation")

    try:
        application = build_application(
            requirement=source_requirement,
            attestation=attestation,
            attestation_bytes=attestation_bytes,
            source_avatar_vrm=source["avatar"],
            candidate_avatar_vrm=candidate["avatar"],
            domain_application=domain_application,
        )
    except FineIdentityApplicationError as exc:
        raise FineIdentityPackageCertificationError(str(exc)) from exc

    certified_avatar = _embed_application(
        candidate["avatar"],
        expected_requirement=source_requirement,
        application=application,
    )
    try:
        validate_application(
            application,
            requirement=source_requirement,
            avatar_vrm=certified_avatar,
        )
    except FineIdentityApplicationError as exc:
        raise FineIdentityPackageCertificationError(
            f"embedded fine-identity application failed self-validation: {exc}"
        ) from exc

    output = Path(output_package_path).expanduser().resolve()
    receipt_out = Path(receipt_path).expanduser().resolve()
    if output.exists() or receipt_out.exists():
        raise FineIdentityPackageCertificationError(
            "fine-identity certification outputs are create-only"
        )

    package_created = False
    receipt_created = False
    try:
        _rewrite_package(candidate, output, avatar_vrm=certified_avatar)
        package_created = True
        certified = _package_bundle(output, label="Certified fine-identity package")
        if certified["validated"].manifest.get("id") != source["validated"].manifest.get("id"):
            raise FineIdentityPackageCertificationError("certified package changed canonical body id")
        if certified["validated"].bodyprint != source["validated"].bodyprint:
            raise FineIdentityPackageCertificationError("certified package changed bodyprint authority")
        _doc, certified_bodyrig, _bin, certified_requirement = _requirement_from_avatar(
            certified["avatar"],
            label="Certified fine-identity package",
            reject_existing_application=False,
        )
        if certified_requirement != source_requirement:
            raise FineIdentityPackageCertificationError("certified package changed fine-identity requirement")
        embedded_application = certified_bodyrig.get("fineIdentityApplication")
        try:
            validated_embedded = validate_application(
                embedded_application,
                requirement=source_requirement,
                avatar_vrm=certified["avatar"],
            )
        except FineIdentityApplicationError as exc:
            raise FineIdentityPackageCertificationError(
                f"certified package fine-identity application is invalid: {exc}"
            ) from exc
        if validated_embedded != application:
            raise FineIdentityPackageCertificationError(
                "certified package fine-identity application changed after embedding"
            )

        application_sha = _sha256_bytes(_canonical_json(application))
        attestation_sha = _sha256_bytes(attestation_bytes)
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "policy_revision": POLICY_REVISION,
            "certification_id": _certification_id(
                source_package_sha256=source["package_sha256"],
                candidate_package_sha256=candidate["package_sha256"],
                attestation_sha256=attestation_sha,
                application_sha256=application_sha,
            ),
            "body_id": str(source["validated"].manifest["id"]),
            "bodyrig_revision": revision,
            "source_package_sha256": source["package_sha256"],
            "uncertified_candidate_package_sha256": candidate["package_sha256"],
            "certified_package_sha256": certified["package_sha256"],
            "source_avatar_sha256": source["avatar_sha256"],
            "uncertified_candidate_avatar_sha256": candidate["avatar_sha256"],
            "certified_avatar_sha256": certified["avatar_sha256"],
            "fine_identity_authority_sha256": source_requirement["fineIdentityAuthoritySha256"],
            "fine_identity_attestation_sha256": source_requirement["fineIdentityAttestationSha256"],
            "application_sha256": application_sha,
            "domains": {key: dict(item) for key, item in application["domains"].items()},
            "source_grounded": True,
            "generative": False,
            "package_application_authority": True,
            "geometry_modified": True,
            "appearance_modified": True,
            "rig_preserved": True,
            "human_review_required": True,
            "production_activation": False,
        }
        validated_receipt = validate_certification_receipt(receipt)
        receipt_out.parent.mkdir(parents=True, exist_ok=True)
        with receipt_out.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(
                    validated_receipt,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n"
            )
        receipt_created = True
        return {
            **validated_receipt,
            "package_path": str(output),
            "receipt_path": str(receipt_out),
        }
    except Exception:
        if receipt_created:
            receipt_out.unlink(missing_ok=True)
        if package_created:
            output.unlink(missing_ok=True)
        raise
