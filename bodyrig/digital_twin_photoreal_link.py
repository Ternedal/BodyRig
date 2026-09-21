from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .digital_twin_composition_authority import (
    DigitalTwinCompositionAuthorityError,
    composition_authority_dir,
    read_composition_authority,
)
from .photoreal_person_binding import (
    PhotorealPersonBindingError,
    revalidate_photoreal_person_binding,
    validate_photoreal_person_binding_structure,
)
from .photoreal_p3_physical_runtime_review import (
    PhotorealP3PhysicalRuntimeReviewError,
    validate_physical_runtime_review_receipt,
)

FORMAT = "bodyrig-digital-twin-photoreal-link"
VERSION = 1
POLICY_REVISION = "bodyrig-digital-twin-photoreal-link-v1"
VISUAL_AUTHORITY = "photoreal-v2-p3"
LINK_ID_RE = re.compile(r"^dtphoto-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")

TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "link_id",
    "person_id",
    "person_revision",
    "assembly_fingerprint",
    "body_revision",
    "body_id",
    "body_package_sha256",
    "bodyrig_revision",
    "composition_authority_id",
    "composition_authority_file_sha256",
    "composition_authority_content_sha256",
    "photoreal_binding_id",
    "photoreal_binding_file_sha256",
    "photoreal_binding_content_sha256",
    "p3_receipt_file_sha256",
    "p3_receipt_declared_sha256",
    "stash_performer_id",
    "selected_epoch_id",
    "teacher_input_sha256",
    "p3_device_runtime_review_plan_sha256",
    "target_device_family",
    "target_device_model",
    "student_representation",
    "visual_authority",
    "m5_photoreal_integration_eligible",
    "finalized_utc",
    "production_activation",
}


class DigitalTwinPhotorealLinkError(RuntimeError):
    pass


def _v1(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 1


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise DigitalTwinPhotorealLinkError(f"{label} is not a canonical SHA-256")
    return text


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
        raise DigitalTwinPhotorealLinkError(
            "M4 Photoreal link evidence cannot be canonically serialized"
        ) from exc


def _content_sha256(value: Mapping[str, Any]) -> str:
    return _sha256_bytes(_canonical_json_bytes(value))


def _read_json_bytes(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise DigitalTwinPhotorealLinkError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise DigitalTwinPhotorealLinkError(f"{label} must be a JSON object")
    return raw, value


def _link_id(value: Mapping[str, Any]) -> str:
    evidence = {
        key: value[key]
        for key in (
            "person_id",
            "person_revision",
            "assembly_fingerprint",
            "body_revision",
            "body_id",
            "body_package_sha256",
            "bodyrig_revision",
            "composition_authority_id",
            "composition_authority_file_sha256",
            "composition_authority_content_sha256",
            "photoreal_binding_id",
            "photoreal_binding_file_sha256",
            "photoreal_binding_content_sha256",
            "p3_receipt_file_sha256",
            "p3_receipt_declared_sha256",
            "stash_performer_id",
            "selected_epoch_id",
            "teacher_input_sha256",
            "p3_device_runtime_review_plan_sha256",
            "target_device_family",
            "target_device_model",
            "student_representation",
            "visual_authority",
        )
    }
    return "dtphoto-" + hashlib.sha256(_canonical_json_bytes(evidence)).hexdigest()[:32]


def photoreal_link_dir(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    person_revision: str,
    link_id: str,
) -> Path:
    for label, item in (
        ("person id", person_id),
        ("person revision", person_revision),
        ("link id", link_id),
    ):
        text = str(item or "")
        if not text or Path(text).name != text or "/" in text or "\\" in text:
            raise DigitalTwinPhotorealLinkError(f"{label} is not a safe path component")
    if not LINK_ID_RE.fullmatch(link_id):
        raise DigitalTwinPhotorealLinkError("M4 Photoreal link id is invalid")
    return (
        Path(root).expanduser().resolve()
        / "digital-twin-photoreal-links"
        / person_id
        / person_revision
        / link_id
    )


def validate_photoreal_link_structure(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise DigitalTwinPhotorealLinkError("M4 Photoreal link fields are not canonical")
    if (
        value.get("format") != FORMAT
        or not _v1(value.get("version"))
        or value.get("policy_revision") != POLICY_REVISION
    ):
        raise DigitalTwinPhotorealLinkError("M4 Photoreal link format/version/policy mismatch")

    for field in (
        "assembly_fingerprint",
        "body_package_sha256",
        "composition_authority_file_sha256",
        "composition_authority_content_sha256",
        "photoreal_binding_file_sha256",
        "photoreal_binding_content_sha256",
        "p3_receipt_file_sha256",
        "p3_receipt_declared_sha256",
        "teacher_input_sha256",
        "p3_device_runtime_review_plan_sha256",
    ):
        _sha(value.get(field), field.replace("_", " "))

    revision = str(value.get("bodyrig_revision") or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise DigitalTwinPhotorealLinkError("M4 Photoreal link BodyRig revision is invalid")

    for field in (
        "person_id",
        "person_revision",
        "body_revision",
        "body_id",
        "composition_authority_id",
        "photoreal_binding_id",
        "stash_performer_id",
        "selected_epoch_id",
        "target_device_family",
        "target_device_model",
        "student_representation",
    ):
        if not isinstance(value.get(field), str) or not str(value[field]).strip():
            raise DigitalTwinPhotorealLinkError(f"M4 Photoreal link {field} is invalid")

    if value.get("visual_authority") != VISUAL_AUTHORITY:
        raise DigitalTwinPhotorealLinkError("M4 Photoreal link visual authority is not canonical")
    if value.get("m5_photoreal_integration_eligible") is not True:
        raise DigitalTwinPhotorealLinkError("M4 Photoreal link does not authorize M5 integration")
    if value.get("production_activation") is not False:
        raise DigitalTwinPhotorealLinkError("M4 Photoreal link cannot activate production")

    link_id = str(value.get("link_id") or "").strip().lower()
    if not LINK_ID_RE.fullmatch(link_id) or link_id != _link_id(value):
        raise DigitalTwinPhotorealLinkError("M4 Photoreal link id no longer matches exact evidence")
    if not isinstance(value.get("finalized_utc"), str) or not str(value["finalized_utc"]).endswith("Z"):
        raise DigitalTwinPhotorealLinkError("M4 Photoreal link finalized timestamp is invalid")
    return dict(value)


def _validated_inputs(
    root: Path,
    *,
    composition_authority_dir_path: Path,
    photoreal_person_binding_path: Path,
    p3_physical_runtime_review_path: Path,
    bodyrig_revision: str,
) -> tuple[dict[str, Any], bytes, dict[str, Any], bytes, dict[str, Any], bytes]:
    revision = str(bodyrig_revision or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise DigitalTwinPhotorealLinkError(
            "BodyRig revision must be an exact 40-character commit SHA"
        )

    composition_raw, composition_hint = _read_json_bytes(
        composition_authority_dir_path / "authority.json",
        "M4 composition authority",
    )
    person_id = str(composition_hint.get("person_id") or "")
    person_revision = str(composition_hint.get("person_revision") or "")
    authority_id = str(composition_hint.get("authority_id") or "")
    expected_dir = composition_authority_dir(
        root,
        person_id,
        person_revision,
        authority_id,
    ).resolve()
    if expected_dir != composition_authority_dir_path.resolve():
        raise DigitalTwinPhotorealLinkError(
            "M4 composition authority directory is not under the exact canonical Person authority path"
        )
    try:
        composition = read_composition_authority(
            root,
            person_id=person_id,
            person_revision=person_revision,
            authority_id=authority_id,
        )
    except (DigitalTwinCompositionAuthorityError, OSError, ValueError) as exc:
        raise DigitalTwinPhotorealLinkError(f"M4 composition authority is invalid: {exc}") from exc
    if str(composition.get("bodyrig_revision") or "").lower() != revision:
        raise DigitalTwinPhotorealLinkError(
            "M4 composition and Photoreal link were not finalized from the same BodyRig revision"
        )

    photoreal_raw, photoreal_value = _read_json_bytes(
        photoreal_person_binding_path,
        "Photoreal Person binding",
    )
    p3_raw, p3_value = _read_json_bytes(
        p3_physical_runtime_review_path,
        "P3 physical runtime review",
    )
    try:
        photoreal = validate_photoreal_person_binding_structure(photoreal_value)
        p3 = validate_physical_runtime_review_receipt(p3_value)
        revalidate_photoreal_person_binding(
            photoreal,
            person_library=root,
            person_id=person_id,
            assembly_receipt_path=composition_authority_dir_path
            / "person-assembly-receipt.json",
            body_release_status_path=composition_authority_dir_path
            / "body-release-status.json",
            p3_physical_runtime_review_path=p3_physical_runtime_review_path,
            bodyrig_revision=revision,
        )
    except (
        PhotorealPersonBindingError,
        PhotorealP3PhysicalRuntimeReviewError,
        OSError,
        ValueError,
    ) as exc:
        raise DigitalTwinPhotorealLinkError(
            f"Photoreal Person authority is invalid: {exc}"
        ) from exc

    exact_fields = (
        "person_id",
        "person_revision",
        "assembly_fingerprint",
        "body_revision",
        "body_id",
        "body_package_sha256",
        "bodyrig_revision",
    )
    for field in exact_fields:
        if str(photoreal.get(field) or "").lower() != str(composition.get(field) or "").lower():
            raise DigitalTwinPhotorealLinkError(
                f"Photoreal Person binding and M4 composition differ on exact {field}"
            )
    if p3.get("photoreal_acceptance_authority") is not True:
        raise DigitalTwinPhotorealLinkError("P3 evidence no longer grants photoreal acceptance")
    return composition, composition_raw, photoreal, photoreal_raw, p3, p3_raw


def build_photoreal_link(
    person_library: str | os.PathLike[str],
    *,
    composition_authority_dir_path: str | os.PathLike[str],
    photoreal_person_binding_path: str | os.PathLike[str],
    p3_physical_runtime_review_path: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    root = Path(person_library).expanduser().resolve()
    composition_dir = Path(composition_authority_dir_path).expanduser().resolve()
    photoreal_path = Path(photoreal_person_binding_path).expanduser().resolve()
    p3_path = Path(p3_physical_runtime_review_path).expanduser().resolve()
    (
        composition,
        composition_raw,
        photoreal,
        photoreal_raw,
        p3,
        p3_raw,
    ) = _validated_inputs(
        root,
        composition_authority_dir_path=composition_dir,
        photoreal_person_binding_path=photoreal_path,
        p3_physical_runtime_review_path=p3_path,
        bodyrig_revision=bodyrig_revision,
    )

    link: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "link_id": "",
        "person_id": str(composition["person_id"]),
        "person_revision": str(composition["person_revision"]),
        "assembly_fingerprint": str(composition["assembly_fingerprint"]),
        "body_revision": str(composition["body_revision"]),
        "body_id": str(composition["body_id"]),
        "body_package_sha256": str(composition["body_package_sha256"]),
        "bodyrig_revision": str(composition["bodyrig_revision"]),
        "composition_authority_id": str(composition["authority_id"]),
        "composition_authority_file_sha256": _sha256_bytes(composition_raw),
        "composition_authority_content_sha256": _content_sha256(composition),
        "photoreal_binding_id": str(photoreal["binding_id"]),
        "photoreal_binding_file_sha256": _sha256_bytes(photoreal_raw),
        "photoreal_binding_content_sha256": _content_sha256(photoreal),
        "p3_receipt_file_sha256": _sha256_bytes(p3_raw),
        "p3_receipt_declared_sha256": _sha(
            p3.get("p3_physical_runtime_review_sha256"),
            "P3 physical runtime review SHA-256",
        ),
        "stash_performer_id": str(photoreal["stash_performer_id"]),
        "selected_epoch_id": str(photoreal["selected_epoch_id"]),
        "teacher_input_sha256": str(photoreal["teacher_input_sha256"]),
        "p3_device_runtime_review_plan_sha256": str(
            photoreal["p3_device_runtime_review_plan_sha256"]
        ),
        "target_device_family": str(photoreal["target_device_family"]),
        "target_device_model": str(photoreal["target_device_model"]),
        "student_representation": str(photoreal["student_representation"]),
        "visual_authority": VISUAL_AUTHORITY,
        "m5_photoreal_integration_eligible": True,
        "finalized_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "production_activation": False,
    }
    link["link_id"] = _link_id(link)
    return validate_photoreal_link_structure(link)


def write_photoreal_link(
    person_library: str | os.PathLike[str],
    *,
    composition_authority_dir_path: str | os.PathLike[str],
    photoreal_person_binding_path: str | os.PathLike[str],
    p3_physical_runtime_review_path: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    root = Path(person_library).expanduser().resolve()
    link = build_photoreal_link(
        root,
        composition_authority_dir_path=composition_authority_dir_path,
        photoreal_person_binding_path=photoreal_person_binding_path,
        p3_physical_runtime_review_path=p3_physical_runtime_review_path,
        bodyrig_revision=bodyrig_revision,
    )
    target = photoreal_link_dir(
        root,
        person_id=str(link["person_id"]),
        person_revision=str(link["person_revision"]),
        link_id=str(link["link_id"]),
    )
    if target.exists():
        raise DigitalTwinPhotorealLinkError(
            "exact M4 Photoreal link already exists; create-only authority cannot be overwritten"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.parent / f".{link['link_id']}.staging-{uuid.uuid4().hex}"
    try:
        stage.mkdir(parents=False, exist_ok=False)
        shutil.copyfile(
            Path(photoreal_person_binding_path).expanduser().resolve(),
            stage / "photoreal-person-binding.json",
        )
        shutil.copyfile(
            Path(p3_physical_runtime_review_path).expanduser().resolve(),
            stage / "p3-physical-runtime-review.json",
        )
        (stage / "authority.json").write_bytes(_canonical_json_bytes(link) + b"\n")
        os.replace(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return read_photoreal_link(
        root,
        person_id=str(link["person_id"]),
        person_revision=str(link["person_revision"]),
        link_id=str(link["link_id"]),
        composition_authority_dir_path=composition_authority_dir_path,
    )


def read_photoreal_link(
    person_library: str | os.PathLike[str],
    *,
    person_id: str,
    person_revision: str,
    link_id: str,
    composition_authority_dir_path: str | os.PathLike[str],
) -> dict[str, Any]:
    root = Path(person_library).expanduser().resolve()
    directory = photoreal_link_dir(
        root,
        person_id=person_id,
        person_revision=person_revision,
        link_id=link_id,
    )
    if not directory.is_dir():
        raise DigitalTwinPhotorealLinkError("M4 Photoreal link authority is missing")

    authority_raw, authority = _read_json_bytes(directory / "authority.json", "M4 Photoreal link")
    photoreal_raw, _photoreal = _read_json_bytes(
        directory / "photoreal-person-binding.json",
        "frozen Photoreal Person binding",
    )
    p3_raw, _p3 = _read_json_bytes(
        directory / "p3-physical-runtime-review.json",
        "frozen P3 physical runtime review",
    )
    value = validate_photoreal_link_structure(authority)
    if str(value.get("link_id") or "") != link_id:
        raise DigitalTwinPhotorealLinkError("Photoreal link path does not match contained link id")
    if _sha256_bytes(photoreal_raw) != str(value["photoreal_binding_file_sha256"]):
        raise DigitalTwinPhotorealLinkError("frozen Photoreal Person binding bytes were modified")
    if _sha256_bytes(p3_raw) != str(value["p3_receipt_file_sha256"]):
        raise DigitalTwinPhotorealLinkError("frozen P3 physical runtime review bytes were modified")

    composition_dir = Path(composition_authority_dir_path).expanduser().resolve()
    (
        composition,
        composition_raw,
        photoreal,
        _,
        p3,
        _,
    ) = _validated_inputs(
        root,
        composition_authority_dir_path=composition_dir,
        photoreal_person_binding_path=directory / "photoreal-person-binding.json",
        p3_physical_runtime_review_path=directory / "p3-physical-runtime-review.json",
        bodyrig_revision=str(value["bodyrig_revision"]),
    )
    if _sha256_bytes(composition_raw) != str(value["composition_authority_file_sha256"]):
        raise DigitalTwinPhotorealLinkError("live M4 composition authority bytes changed")
    if _content_sha256(composition) != str(value["composition_authority_content_sha256"]):
        raise DigitalTwinPhotorealLinkError("live M4 composition authority content changed")
    if _content_sha256(photoreal) != str(value["photoreal_binding_content_sha256"]):
        raise DigitalTwinPhotorealLinkError("frozen Photoreal Person binding content changed")
    if str(p3.get("p3_physical_runtime_review_sha256") or "") != str(
        value["p3_receipt_declared_sha256"]
    ):
        raise DigitalTwinPhotorealLinkError("frozen P3 receipt declared digest changed")

    rebuilt = build_photoreal_link(
        root,
        composition_authority_dir_path=composition_dir,
        photoreal_person_binding_path=directory / "photoreal-person-binding.json",
        p3_physical_runtime_review_path=directory / "p3-physical-runtime-review.json",
        bodyrig_revision=str(value["bodyrig_revision"]),
    )
    rebuilt["finalized_utc"] = value["finalized_utc"]
    if rebuilt != value:
        raise DigitalTwinPhotorealLinkError(
            "M4 Photoreal link no longer matches exact M4/Person/P3 evidence"
        )
    return value
