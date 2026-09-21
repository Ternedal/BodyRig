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

from .digital_twin_photoreal_m5_link import (
    DigitalTwinPhotorealM5LinkError,
    photoreal_m5_link_dir,
    read_photoreal_m5_link,
)
from .digital_twin_release import (
    DigitalTwinReleaseError,
    read_release,
    release_dir,
)

FORMAT = "bodyrig-digital-twin-photoreal-release"
VERSION = 1
POLICY_REVISION = "bodyrig-digital-twin-photoreal-release-v1"
VISUAL_AUTHORITY = "photoreal-v2-p3"
RELEASE_ID_RE = re.compile(r"^dtphotorel-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")

TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "release_id",
    "person_id",
    "person_revision",
    "assembly_fingerprint",
    "body_revision",
    "body_id",
    "body_package_sha256",
    "bodyrig_revision",
    "canonical_m6_release_id",
    "canonical_m6_release_file_sha256",
    "canonical_m6_release_content_sha256",
    "photoreal_m5_link_id",
    "photoreal_m5_link_file_sha256",
    "photoreal_m5_link_content_sha256",
    "m4_photoreal_link_id",
    "windows_realization_sha256",
    "quest_realization_sha256",
    "visual_authority",
    "state",
    "canonical_digital_twin_ready",
    "photoreal_digital_twin_ready",
    "finalized_utc",
    "production_activation",
}


class DigitalTwinPhotorealReleaseError(RuntimeError):
    pass


def _v1(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 1


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise DigitalTwinPhotorealReleaseError(f"{label} is not a canonical SHA-256")
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
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M6 release cannot be canonically serialized"
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
        raise DigitalTwinPhotorealReleaseError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise DigitalTwinPhotorealReleaseError(f"{label} must be a JSON object")
    return raw, value


def _release_id(value: Mapping[str, Any]) -> str:
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
            "canonical_m6_release_id",
            "canonical_m6_release_file_sha256",
            "canonical_m6_release_content_sha256",
            "photoreal_m5_link_id",
            "photoreal_m5_link_file_sha256",
            "photoreal_m5_link_content_sha256",
            "m4_photoreal_link_id",
            "windows_realization_sha256",
            "quest_realization_sha256",
            "visual_authority",
        )
    }
    return "dtphotorel-" + hashlib.sha256(_canonical_json_bytes(evidence)).hexdigest()[:32]


def photoreal_release_dir(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    person_revision: str,
    release_id: str,
) -> Path:
    for label, item in (
        ("person id", person_id),
        ("person revision", person_revision),
        ("release id", release_id),
    ):
        text = str(item or "")
        if not text or Path(text).name != text or "/" in text or "\\" in text:
            raise DigitalTwinPhotorealReleaseError(f"{label} is not a safe path component")
    if not RELEASE_ID_RE.fullmatch(release_id):
        raise DigitalTwinPhotorealReleaseError("Photoreal M6 release id is invalid")
    return (
        Path(root).expanduser().resolve()
        / "digital-twin-photoreal-releases"
        / person_id
        / person_revision
        / release_id
    )


def validate_photoreal_release_structure(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M6 release fields are not canonical"
        )
    if (
        value.get("format") != FORMAT
        or not _v1(value.get("version"))
        or value.get("policy_revision") != POLICY_REVISION
    ):
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M6 release format/version/policy mismatch"
        )
    for field in (
        "assembly_fingerprint",
        "body_package_sha256",
        "canonical_m6_release_file_sha256",
        "canonical_m6_release_content_sha256",
        "photoreal_m5_link_file_sha256",
        "photoreal_m5_link_content_sha256",
        "windows_realization_sha256",
        "quest_realization_sha256",
    ):
        _sha(value.get(field), field.replace("_", " "))
    revision = str(value.get("bodyrig_revision") or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M6 BodyRig revision is invalid"
        )
    for field in (
        "person_id",
        "person_revision",
        "body_revision",
        "body_id",
        "canonical_m6_release_id",
        "photoreal_m5_link_id",
        "m4_photoreal_link_id",
    ):
        if not isinstance(value.get(field), str) or not str(value[field]).strip():
            raise DigitalTwinPhotorealReleaseError(
                f"Photoreal M6 {field} is invalid"
            )
    if value.get("visual_authority") != VISUAL_AUTHORITY:
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M6 visual authority is not canonical"
        )
    if value.get("state") != "released":
        raise DigitalTwinPhotorealReleaseError("Photoreal M6 release is not released")
    if value.get("canonical_digital_twin_ready") is not True:
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M6 lacks canonical digital-twin readiness"
        )
    if value.get("photoreal_digital_twin_ready") is not True:
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M6 has not reached photoreal digital-twin readiness"
        )
    if value.get("production_activation") is not True:
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M6 release is not production activating"
        )
    release_id = str(value.get("release_id") or "").strip().lower()
    if not RELEASE_ID_RE.fullmatch(release_id) or release_id != _release_id(value):
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M6 release id no longer matches exact evidence"
        )
    if not isinstance(value.get("finalized_utc"), str) or not str(
        value["finalized_utc"]
    ).endswith("Z"):
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M6 finalized timestamp is invalid"
        )
    return dict(value)


def _validated_inputs(
    root: Path,
    *,
    canonical_m6_release_dir_path: Path,
    composition_authority_dir_path: Path,
    acceptance_dir_path: Path,
    photoreal_m5_link_authority_dir_path: Path,
    m4_photoreal_link_authority_dir_path: Path,
    bodyrig_revision: str,
) -> tuple[dict[str, Any], bytes, dict[str, Any], bytes]:
    revision = str(bodyrig_revision or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise DigitalTwinPhotorealReleaseError(
            "BodyRig revision must be an exact 40-character commit SHA"
        )

    m6_raw, m6_hint = _read_json_bytes(
        canonical_m6_release_dir_path / "authority.json",
        "canonical M6 release authority",
    )
    person_id = str(m6_hint.get("person_id") or "")
    person_revision = str(m6_hint.get("person_revision") or "")
    canonical_release_id = str(m6_hint.get("release_id") or "")
    expected_m6_dir = release_dir(
        root,
        person_id=person_id,
        person_revision=person_revision,
        release_id=canonical_release_id,
    ).resolve()
    if expected_m6_dir != canonical_m6_release_dir_path.resolve():
        raise DigitalTwinPhotorealReleaseError(
            "canonical M6 release directory is not the exact Person/release path"
        )
    try:
        canonical_m6 = read_release(
            root,
            person_id=person_id,
            person_revision=person_revision,
            release_id=canonical_release_id,
            composition_authority_dir=composition_authority_dir_path,
            acceptance_dir=acceptance_dir_path,
        )
    except (DigitalTwinReleaseError, OSError, ValueError) as exc:
        raise DigitalTwinPhotorealReleaseError(
            f"canonical M6 release is invalid: {exc}"
        ) from exc
    if (
        canonical_m6.get("digital_twin_ready") is not True
        or canonical_m6.get("production_activation") is not True
        or canonical_m6.get("state") != "released"
    ):
        raise DigitalTwinPhotorealReleaseError(
            "canonical M6 release is not an activating complete digital twin"
        )
    if str(canonical_m6.get("bodyrig_revision") or "").lower() != revision:
        raise DigitalTwinPhotorealReleaseError(
            "canonical M6 and Photoreal M6 use different BodyRig revisions"
        )

    m5_raw, m5_hint = _read_json_bytes(
        photoreal_m5_link_authority_dir_path / "authority.json",
        "Photoreal M5 link authority",
    )
    m5_link_id = str(m5_hint.get("link_id") or "")
    expected_m5_dir = photoreal_m5_link_dir(
        root,
        person_id=person_id,
        person_revision=person_revision,
        link_id=m5_link_id,
    ).resolve()
    if expected_m5_dir != photoreal_m5_link_authority_dir_path.resolve():
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M5 link directory is not the exact Person/link path"
        )
    try:
        photoreal_m5 = read_photoreal_m5_link(
            root,
            person_id=person_id,
            person_revision=person_revision,
            link_id=m5_link_id,
            composition_authority_dir_path=composition_authority_dir_path,
            acceptance_dir_path=acceptance_dir_path,
            photoreal_link_authority_dir_path=m4_photoreal_link_authority_dir_path,
        )
    except (DigitalTwinPhotorealM5LinkError, OSError, ValueError) as exc:
        raise DigitalTwinPhotorealReleaseError(
            f"Photoreal M5 link is invalid: {exc}"
        ) from exc
    if (
        photoreal_m5.get("photoreal_m5_ready") is not True
        or photoreal_m5.get("m6_photoreal_release_eligible") is not True
        or photoreal_m5.get("production_activation") is not False
    ):
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M5 does not authorize final Photoreal release"
        )
    if str(photoreal_m5.get("bodyrig_revision") or "").lower() != revision:
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M5 and canonical M6 use different BodyRig revisions"
        )

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
        if str(photoreal_m5.get(field) or "").lower() != str(
            canonical_m6.get(field) or ""
        ).lower():
            raise DigitalTwinPhotorealReleaseError(
                f"Photoreal M5 and canonical M6 differ on exact {field}"
            )
    for field in ("windows_realization_sha256", "quest_realization_sha256"):
        if _sha(photoreal_m5.get(field), f"Photoreal M5 {field}") != _sha(
            canonical_m6.get(field), f"canonical M6 {field}"
        ):
            raise DigitalTwinPhotorealReleaseError(
                f"Photoreal M5 and canonical M6 differ on {field}"
            )
    return canonical_m6, m6_raw, photoreal_m5, m5_raw


def build_photoreal_release(
    person_library: str | os.PathLike[str],
    *,
    canonical_m6_release_dir_path: str | os.PathLike[str],
    composition_authority_dir_path: str | os.PathLike[str],
    acceptance_dir_path: str | os.PathLike[str],
    photoreal_m5_link_authority_dir_path: str | os.PathLike[str],
    m4_photoreal_link_authority_dir_path: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    root = Path(person_library).expanduser().resolve()
    (
        canonical_m6,
        canonical_m6_raw,
        photoreal_m5,
        photoreal_m5_raw,
    ) = _validated_inputs(
        root,
        canonical_m6_release_dir_path=Path(canonical_m6_release_dir_path)
        .expanduser()
        .resolve(),
        composition_authority_dir_path=Path(composition_authority_dir_path)
        .expanduser()
        .resolve(),
        acceptance_dir_path=Path(acceptance_dir_path).expanduser().resolve(),
        photoreal_m5_link_authority_dir_path=Path(
            photoreal_m5_link_authority_dir_path
        )
        .expanduser()
        .resolve(),
        m4_photoreal_link_authority_dir_path=Path(
            m4_photoreal_link_authority_dir_path
        )
        .expanduser()
        .resolve(),
        bodyrig_revision=bodyrig_revision,
    )

    authority: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "release_id": "",
        "person_id": str(canonical_m6["person_id"]),
        "person_revision": str(canonical_m6["person_revision"]),
        "assembly_fingerprint": str(canonical_m6["assembly_fingerprint"]),
        "body_revision": str(canonical_m6["body_revision"]),
        "body_id": str(canonical_m6["body_id"]),
        "body_package_sha256": str(canonical_m6["body_package_sha256"]),
        "bodyrig_revision": str(canonical_m6["bodyrig_revision"]),
        "canonical_m6_release_id": str(canonical_m6["release_id"]),
        "canonical_m6_release_file_sha256": _sha256_bytes(canonical_m6_raw),
        "canonical_m6_release_content_sha256": _content_sha256(canonical_m6),
        "photoreal_m5_link_id": str(photoreal_m5["link_id"]),
        "photoreal_m5_link_file_sha256": _sha256_bytes(photoreal_m5_raw),
        "photoreal_m5_link_content_sha256": _content_sha256(photoreal_m5),
        "m4_photoreal_link_id": str(photoreal_m5["m4_photoreal_link_id"]),
        "windows_realization_sha256": str(canonical_m6["windows_realization_sha256"]),
        "quest_realization_sha256": str(canonical_m6["quest_realization_sha256"]),
        "visual_authority": VISUAL_AUTHORITY,
        "state": "released",
        "canonical_digital_twin_ready": True,
        "photoreal_digital_twin_ready": True,
        "finalized_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "production_activation": True,
    }
    authority["release_id"] = _release_id(authority)
    return validate_photoreal_release_structure(authority)


def write_photoreal_release(
    person_library: str | os.PathLike[str],
    *,
    canonical_m6_release_dir_path: str | os.PathLike[str],
    composition_authority_dir_path: str | os.PathLike[str],
    acceptance_dir_path: str | os.PathLike[str],
    photoreal_m5_link_authority_dir_path: str | os.PathLike[str],
    m4_photoreal_link_authority_dir_path: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    root = Path(person_library).expanduser().resolve()
    authority = build_photoreal_release(
        root,
        canonical_m6_release_dir_path=canonical_m6_release_dir_path,
        composition_authority_dir_path=composition_authority_dir_path,
        acceptance_dir_path=acceptance_dir_path,
        photoreal_m5_link_authority_dir_path=photoreal_m5_link_authority_dir_path,
        m4_photoreal_link_authority_dir_path=m4_photoreal_link_authority_dir_path,
        bodyrig_revision=bodyrig_revision,
    )
    target = photoreal_release_dir(
        root,
        person_id=str(authority["person_id"]),
        person_revision=str(authority["person_revision"]),
        release_id=str(authority["release_id"]),
    )
    if target.exists():
        raise DigitalTwinPhotorealReleaseError(
            "exact Photoreal M6 release already exists; create-only authority cannot be overwritten"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.parent / f".{authority['release_id']}.staging-{uuid.uuid4().hex}"
    try:
        stage.mkdir(parents=False, exist_ok=False)
        shutil.copyfile(
            Path(canonical_m6_release_dir_path).expanduser().resolve()
            / "authority.json",
            stage / "canonical-m6-authority.json",
        )
        shutil.copyfile(
            Path(photoreal_m5_link_authority_dir_path).expanduser().resolve()
            / "authority.json",
            stage / "photoreal-m5-link.json",
        )
        (stage / "authority.json").write_bytes(
            _canonical_json_bytes(authority) + b"\n"
        )
        os.replace(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return read_photoreal_release(
        root,
        person_id=str(authority["person_id"]),
        person_revision=str(authority["person_revision"]),
        release_id=str(authority["release_id"]),
        canonical_m6_release_dir_path=canonical_m6_release_dir_path,
        composition_authority_dir_path=composition_authority_dir_path,
        acceptance_dir_path=acceptance_dir_path,
        photoreal_m5_link_authority_dir_path=photoreal_m5_link_authority_dir_path,
        m4_photoreal_link_authority_dir_path=m4_photoreal_link_authority_dir_path,
    )


def read_photoreal_release(
    person_library: str | os.PathLike[str],
    *,
    person_id: str,
    person_revision: str,
    release_id: str,
    canonical_m6_release_dir_path: str | os.PathLike[str],
    composition_authority_dir_path: str | os.PathLike[str],
    acceptance_dir_path: str | os.PathLike[str],
    photoreal_m5_link_authority_dir_path: str | os.PathLike[str],
    m4_photoreal_link_authority_dir_path: str | os.PathLike[str],
) -> dict[str, Any]:
    root = Path(person_library).expanduser().resolve()
    directory = photoreal_release_dir(
        root,
        person_id=person_id,
        person_revision=person_revision,
        release_id=release_id,
    )
    if not directory.is_dir():
        raise DigitalTwinPhotorealReleaseError("Photoreal M6 release is missing")
    _raw, authority = _read_json_bytes(
        directory / "authority.json",
        "Photoreal M6 release authority",
    )
    value = validate_photoreal_release_structure(authority)
    if str(value.get("release_id") or "") != release_id:
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M6 release path does not match contained release id"
        )

    canonical_raw, _ = _read_json_bytes(
        directory / "canonical-m6-authority.json",
        "frozen canonical M6 authority",
    )
    if _sha256_bytes(canonical_raw) != str(
        value["canonical_m6_release_file_sha256"]
    ):
        raise DigitalTwinPhotorealReleaseError(
            "frozen canonical M6 authority bytes were modified"
        )
    m5_raw, _ = _read_json_bytes(
        directory / "photoreal-m5-link.json",
        "frozen Photoreal M5 link",
    )
    if _sha256_bytes(m5_raw) != str(value["photoreal_m5_link_file_sha256"]):
        raise DigitalTwinPhotorealReleaseError(
            "frozen Photoreal M5 link bytes were modified"
        )

    rebuilt = build_photoreal_release(
        root,
        canonical_m6_release_dir_path=canonical_m6_release_dir_path,
        composition_authority_dir_path=composition_authority_dir_path,
        acceptance_dir_path=acceptance_dir_path,
        photoreal_m5_link_authority_dir_path=photoreal_m5_link_authority_dir_path,
        m4_photoreal_link_authority_dir_path=m4_photoreal_link_authority_dir_path,
        bodyrig_revision=str(value["bodyrig_revision"]),
    )
    rebuilt["finalized_utc"] = value["finalized_utc"]
    if rebuilt != value:
        raise DigitalTwinPhotorealReleaseError(
            "Photoreal M6 release no longer matches exact canonical M6/Photoreal M5 evidence"
        )
    return value
