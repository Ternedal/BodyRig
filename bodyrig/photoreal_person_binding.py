from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .hands_feet_nails_authority import (
    HandsFeetNailsAuthorityError,
    _assembly_identity,
    _release_identity,
)
from .person_profiles import PersonProfileError, active_bundle, load_profile
from .person_source_alignment import (
    PersonSourceAlignmentError,
    binding_path,
    read_binding,
)
from .photoreal_p3_physical_runtime_review import (
    PhotorealP3PhysicalRuntimeReviewError,
    validate_physical_runtime_review_receipt,
)

FORMAT = "bodyrig-photoreal-person-binding-authority"
VERSION = 1
POLICY_REVISION = "bodyrig-photoreal-person-binding-authority-v1"
BINDING_ID_RE = re.compile(r"^photoperson-[0-9a-f]{32}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "binding_id",
    "person_id",
    "person_revision",
    "assembly_fingerprint",
    "body_revision",
    "body_id",
    "body_package_sha256",
    "stash_performer_id",
    "bodyrig_revision",
    "source_binding_file_sha256",
    "source_binding_evidence_sha256",
    "assembly_receipt_file_sha256",
    "body_release_status_file_sha256",
    "p3_receipt_file_sha256",
    "p3_receipt_declared_sha256",
    "p3_receipt_content_sha256",
    "selected_epoch_id",
    "teacher_input_sha256",
    "p3_device_runtime_review_plan_sha256",
    "target_device_family",
    "target_device_model",
    "student_representation",
    "photoreal_binding_authority",
    "m4_photoreal_integration_eligible",
    "finalized_utc",
    "production_activation",
}


class PhotorealPersonBindingError(RuntimeError):
    pass


def _strict_v1(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealPersonBindingError("photoreal Person binding format/version mismatch")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PhotorealPersonBindingError("photoreal Person binding format/version mismatch") from exc
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealPersonBindingError("photoreal Person binding format/version mismatch")


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise PhotorealPersonBindingError(f"{label} is not a canonical SHA-256")
    return text


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise PhotorealPersonBindingError(f"evidence file is unreadable: {path}") from exc
    return digest.hexdigest()


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhotorealPersonBindingError("binding evidence cannot be canonically serialized") from exc


def _content_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealPersonBindingError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealPersonBindingError(f"{label} must be a JSON object")
    return value


def _binding_id(value: Mapping[str, Any]) -> str:
    evidence = {
        key: value[key]
        for key in (
            "person_id",
            "person_revision",
            "assembly_fingerprint",
            "body_revision",
            "body_id",
            "body_package_sha256",
            "stash_performer_id",
            "bodyrig_revision",
            "source_binding_file_sha256",
            "source_binding_evidence_sha256",
            "assembly_receipt_file_sha256",
            "body_release_status_file_sha256",
            "p3_receipt_file_sha256",
            "p3_receipt_declared_sha256",
            "p3_receipt_content_sha256",
            "selected_epoch_id",
            "teacher_input_sha256",
            "p3_device_runtime_review_plan_sha256",
            "target_device_family",
            "target_device_model",
            "student_representation",
        )
    }
    return "photoperson-" + hashlib.sha256(_canonical_json_bytes(evidence)).hexdigest()[:32]


def _profile_body_revision(profile: Mapping[str, Any], revision_id: str) -> Mapping[str, Any]:
    for item in profile.get("body_revisions", []):
        if isinstance(item, Mapping) and item.get("revision_id") == revision_id:
            return item
    raise PhotorealPersonBindingError("active Person revision references a missing body revision")


def build_photoreal_person_binding(
    person_library: str | os.PathLike[str],
    *,
    person_id: str,
    assembly_receipt_path: str | os.PathLike[str],
    body_release_status_path: str | os.PathLike[str],
    p3_physical_runtime_review_path: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    revision = str(bodyrig_revision or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise PhotorealPersonBindingError("BodyRig revision must be an exact 40-character commit SHA")

    library = Path(person_library).expanduser().resolve()
    assembly_path = Path(assembly_receipt_path).expanduser().resolve()
    release_path = Path(body_release_status_path).expanduser().resolve()
    p3_path = Path(p3_physical_runtime_review_path).expanduser().resolve()

    try:
        profile = load_profile(library, person_id)
        active = active_bundle(profile)
    except PersonProfileError as exc:
        raise PhotorealPersonBindingError(f"Person profile is invalid: {exc}") from exc
    if active is None:
        raise PhotorealPersonBindingError("Person has no active approved revision")

    assembly_receipt = _read_json(assembly_path, "Person assembly receipt")
    body_release_status = _read_json(release_path, "body release status")
    p3_raw = _read_json(p3_path, "P3 physical runtime review")

    try:
        assembly = _assembly_identity(assembly_receipt)
        release = _release_identity(body_release_status, assembly)
    except HandsFeetNailsAuthorityError as exc:
        raise PhotorealPersonBindingError(f"Person/body release identity is invalid: {exc}") from exc
    try:
        p3 = validate_physical_runtime_review_receipt(p3_raw)
    except PhotorealP3PhysicalRuntimeReviewError as exc:
        raise PhotorealPersonBindingError(f"P3 physical runtime review is invalid: {exc}") from exc

    if profile.get("person_id") != assembly["person_id"]:
        raise PhotorealPersonBindingError("Person profile and assembly identify different Persons")
    if active.get("revision_id") != assembly["person_revision"]:
        raise PhotorealPersonBindingError("active Person revision differs from the assembly revision")
    if active.get("body_revision") != assembly["body_revision"]:
        raise PhotorealPersonBindingError("active Person revision uses a different body revision")

    body_revision = _profile_body_revision(profile, assembly["body_revision"])
    if str(body_revision.get("body_id") or "").lower() != assembly["body_id"]:
        raise PhotorealPersonBindingError("Person profile body id differs from the assembly")
    if _sha(body_revision.get("package_sha256"), "Person body package SHA-256") != release["package_sha256"]:
        raise PhotorealPersonBindingError("Person profile body package differs from the promoted body release")

    source = profile.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "stash-performer":
        raise PhotorealPersonBindingError("Person has no authoritative Stash performer source")
    performer_id = str(source.get("performer_id") or "").strip()
    if not performer_id:
        raise PhotorealPersonBindingError("Person Stash performer binding has no performer id")
    if str(p3.get("performer_id") or "").strip() != performer_id:
        raise PhotorealPersonBindingError("P3 photoreal evidence belongs to a different Stash performer")

    try:
        source_binding = read_binding(
            library,
            profile,
            kind="body",
            revision_id=assembly["body_revision"],
        )
        source_binding_path = binding_path(
            library,
            assembly["person_id"],
            "body",
            assembly["body_revision"],
        )
    except PersonSourceAlignmentError as exc:
        raise PhotorealPersonBindingError(f"body source alignment is invalid: {exc}") from exc

    if p3.get("runtime_review_status") != "pass":
        raise PhotorealPersonBindingError("P3 physical runtime review is not an explicit all-PASS result")
    if p3.get("runtime_acceptance_authority") is not True:
        raise PhotorealPersonBindingError("P3 physical runtime review lacks runtime acceptance authority")
    if p3.get("photoreal_acceptance_authority") is not True:
        raise PhotorealPersonBindingError("P3 physical runtime review lacks photoreal acceptance authority")
    if p3.get("production_activation") is not False:
        raise PhotorealPersonBindingError("P3 physical runtime review crossed production authority")

    binding: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "binding_id": "",
        "person_id": assembly["person_id"],
        "person_revision": assembly["person_revision"],
        "assembly_fingerprint": assembly["assembly_fingerprint"],
        "body_revision": assembly["body_revision"],
        "body_id": assembly["body_id"],
        "body_package_sha256": release["package_sha256"],
        "stash_performer_id": performer_id,
        "bodyrig_revision": revision,
        "source_binding_file_sha256": _file_sha256(source_binding_path),
        "source_binding_evidence_sha256": _sha(
            source_binding.get("evidence", {}).get("sha256"),
            "body source-binding evidence SHA-256",
        ),
        "assembly_receipt_file_sha256": _file_sha256(assembly_path),
        "body_release_status_file_sha256": _file_sha256(release_path),
        "p3_receipt_file_sha256": _file_sha256(p3_path),
        "p3_receipt_declared_sha256": _sha(
            p3.get("p3_physical_runtime_review_sha256"),
            "P3 declared review SHA-256",
        ),
        "p3_receipt_content_sha256": _content_sha256(p3),
        "selected_epoch_id": str(p3.get("selected_epoch_id") or ""),
        "teacher_input_sha256": _sha(p3.get("teacher_input_sha256"), "teacher input SHA-256"),
        "p3_device_runtime_review_plan_sha256": _sha(
            p3.get("p3_device_runtime_review_plan_sha256"),
            "P3 device runtime review-plan SHA-256",
        ),
        "target_device_family": str(p3.get("target_device_family") or ""),
        "target_device_model": str(p3.get("target_device_model") or ""),
        "student_representation": str(p3.get("student_representation") or ""),
        "photoreal_binding_authority": True,
        "m4_photoreal_integration_eligible": True,
        "finalized_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "production_activation": False,
    }
    if not binding["selected_epoch_id"]:
        raise PhotorealPersonBindingError("P3 physical runtime review has no selected appearance epoch")
    if not binding["target_device_family"] or not binding["target_device_model"] or not binding["student_representation"]:
        raise PhotorealPersonBindingError("P3 physical runtime review has incomplete target/runtime identity")
    binding["binding_id"] = _binding_id(binding)
    return validate_photoreal_person_binding_structure(binding)


def validate_photoreal_person_binding_structure(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise PhotorealPersonBindingError("photoreal Person binding fields are not canonical")
    if value.get("format") != FORMAT or value.get("policy_revision") != POLICY_REVISION:
        raise PhotorealPersonBindingError("photoreal Person binding format/policy mismatch")
    _strict_v1(value.get("version"))

    for field in (
        "body_package_sha256",
        "source_binding_file_sha256",
        "source_binding_evidence_sha256",
        "assembly_receipt_file_sha256",
        "body_release_status_file_sha256",
        "p3_receipt_file_sha256",
        "p3_receipt_declared_sha256",
        "p3_receipt_content_sha256",
        "teacher_input_sha256",
        "p3_device_runtime_review_plan_sha256",
    ):
        _sha(value.get(field), field.replace("_", " "))
    revision = str(value.get("bodyrig_revision") or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise PhotorealPersonBindingError("photoreal Person binding BodyRig revision is invalid")

    canonical_identity = (
        ("person_id", PERSON_ID_RE),
        ("person_revision", PERSON_REVISION_RE),
        ("body_revision", BODY_REVISION_RE),
        ("body_id", BODY_ID_RE),
    )
    for field, pattern in canonical_identity:
        text = str(value.get(field) or "").strip().lower()
        if not pattern.fullmatch(text):
            raise PhotorealPersonBindingError(f"photoreal Person binding {field} is invalid")

    for field in (
        "stash_performer_id",
        "selected_epoch_id",
        "target_device_family",
        "target_device_model",
        "student_representation",
    ):
        if not isinstance(value.get(field), str) or not str(value[field]).strip():
            raise PhotorealPersonBindingError(f"photoreal Person binding {field} is invalid")

    binding_id = str(value.get("binding_id") or "").strip().lower()
    if not BINDING_ID_RE.fullmatch(binding_id) or binding_id != _binding_id(value):
        raise PhotorealPersonBindingError("photoreal Person binding id no longer matches exact evidence")
    if not isinstance(value.get("finalized_utc"), str) or not str(value["finalized_utc"]).endswith("Z"):
        raise PhotorealPersonBindingError("photoreal Person binding finalized timestamp is invalid")
    if value.get("photoreal_binding_authority") is not True:
        raise PhotorealPersonBindingError("photoreal Person binding authority is not granted")
    if value.get("m4_photoreal_integration_eligible") is not True:
        raise PhotorealPersonBindingError("photoreal Person binding is not eligible for M4 integration")
    if value.get("production_activation") is not False:
        raise PhotorealPersonBindingError("photoreal Person binding cannot activate production")
    return dict(value)


def revalidate_photoreal_person_binding(
    value: Mapping[str, Any],
    *,
    person_library: str | os.PathLike[str],
    person_id: str,
    assembly_receipt_path: str | os.PathLike[str],
    body_release_status_path: str | os.PathLike[str],
    p3_physical_runtime_review_path: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    existing = validate_photoreal_person_binding_structure(value)
    expected = build_photoreal_person_binding(
        person_library,
        person_id=person_id,
        assembly_receipt_path=assembly_receipt_path,
        body_release_status_path=body_release_status_path,
        p3_physical_runtime_review_path=p3_physical_runtime_review_path,
        bodyrig_revision=bodyrig_revision,
    )
    expected["finalized_utc"] = existing["finalized_utc"]
    if expected != existing:
        raise PhotorealPersonBindingError(
            "photoreal Person binding no longer matches the exact current "
            "Person/source/body/P3 evidence"
        )
    return existing


def write_photoreal_person_binding(
    output_path: str | os.PathLike[str],
    *,
    person_library: str | os.PathLike[str],
    person_id: str,
    assembly_receipt_path: str | os.PathLike[str],
    body_release_status_path: str | os.PathLike[str],
    p3_physical_runtime_review_path: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    authority = build_photoreal_person_binding(
        person_library,
        person_id=person_id,
        assembly_receipt_path=assembly_receipt_path,
        body_release_status_path=body_release_status_path,
        p3_physical_runtime_review_path=p3_physical_runtime_review_path,
        bodyrig_revision=bodyrig_revision,
    )
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(authority, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise PhotorealPersonBindingError(f"photoreal Person binding already exists: {output}") from exc
    return authority


def read_photoreal_person_binding(path: str | os.PathLike[str]) -> dict[str, Any]:
    return validate_photoreal_person_binding_structure(
        _read_json(Path(path).expanduser().resolve(), "photoreal Person binding")
    )
