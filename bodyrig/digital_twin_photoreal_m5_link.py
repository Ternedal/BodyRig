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

from .digital_twin_photoreal_link import (
    DigitalTwinPhotorealLinkError,
    photoreal_link_dir,
    read_photoreal_link,
)
from .digital_twin_platform_acceptance import (
    DigitalTwinPlatformAcceptanceError,
    inspect_digital_twin_platform_acceptance,
    platform_evidence_dir,
)

FORMAT = "bodyrig-digital-twin-photoreal-m5-link"
VERSION = 1
POLICY_REVISION = "bodyrig-digital-twin-photoreal-m5-link-v1"
VISUAL_AUTHORITY = "photoreal-v2-p3"
LINK_ID_RE = re.compile(r"^dtphotom5-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")

PLATFORMS = ("windows-unity-univrm", "android-quest-class")

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
    "m4_photoreal_link_id",
    "m4_photoreal_link_file_sha256",
    "m4_photoreal_link_content_sha256",
    "windows_platform_input_sha256",
    "windows_realization_sha256",
    "quest_platform_input_sha256",
    "quest_realization_sha256",
    "windows_device_model",
    "quest_device_model",
    "visual_authority",
    "photoreal_m5_ready",
    "m6_photoreal_release_eligible",
    "finalized_utc",
    "production_activation",
}


class DigitalTwinPhotorealM5LinkError(RuntimeError):
    pass


def _v1(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 1


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise DigitalTwinPhotorealM5LinkError(f"{label} is not a canonical SHA-256")
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
        raise DigitalTwinPhotorealM5LinkError(
            "Photoreal M5 link cannot be canonically serialized"
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
        raise DigitalTwinPhotorealM5LinkError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise DigitalTwinPhotorealM5LinkError(f"{label} must be a JSON object")
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
            "m4_photoreal_link_id",
            "m4_photoreal_link_file_sha256",
            "m4_photoreal_link_content_sha256",
            "windows_platform_input_sha256",
            "windows_realization_sha256",
            "quest_platform_input_sha256",
            "quest_realization_sha256",
            "windows_device_model",
            "quest_device_model",
            "visual_authority",
        )
    }
    return "dtphotom5-" + hashlib.sha256(_canonical_json_bytes(evidence)).hexdigest()[:32]


def photoreal_m5_link_dir(
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
            raise DigitalTwinPhotorealM5LinkError(f"{label} is not a safe path component")
    if not LINK_ID_RE.fullmatch(link_id):
        raise DigitalTwinPhotorealM5LinkError("Photoreal M5 link id is invalid")
    return (
        Path(root).expanduser().resolve()
        / "digital-twin-photoreal-m5-links"
        / person_id
        / person_revision
        / link_id
    )


def validate_photoreal_m5_link_structure(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise DigitalTwinPhotorealM5LinkError("Photoreal M5 link fields are not canonical")
    if (
        value.get("format") != FORMAT
        or not _v1(value.get("version"))
        or value.get("policy_revision") != POLICY_REVISION
    ):
        raise DigitalTwinPhotorealM5LinkError(
            "Photoreal M5 link format/version/policy mismatch"
        )
    for field in (
        "assembly_fingerprint",
        "body_package_sha256",
        "m4_photoreal_link_file_sha256",
        "m4_photoreal_link_content_sha256",
        "windows_platform_input_sha256",
        "windows_realization_sha256",
        "quest_platform_input_sha256",
        "quest_realization_sha256",
    ):
        _sha(value.get(field), field.replace("_", " "))
    revision = str(value.get("bodyrig_revision") or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise DigitalTwinPhotorealM5LinkError("Photoreal M5 BodyRig revision is invalid")

    for field in (
        "person_id",
        "person_revision",
        "body_revision",
        "body_id",
        "composition_authority_id",
        "m4_photoreal_link_id",
        "windows_device_model",
        "quest_device_model",
    ):
        if not isinstance(value.get(field), str) or not str(value[field]).strip():
            raise DigitalTwinPhotorealM5LinkError(
                f"Photoreal M5 link {field} is invalid"
            )
    if value.get("visual_authority") != VISUAL_AUTHORITY:
        raise DigitalTwinPhotorealM5LinkError(
            "Photoreal M5 visual authority is not canonical"
        )
    if value.get("photoreal_m5_ready") is not True:
        raise DigitalTwinPhotorealM5LinkError("Photoreal M5 authority is not complete")
    if value.get("m6_photoreal_release_eligible") is not True:
        raise DigitalTwinPhotorealM5LinkError(
            "Photoreal M5 authority does not authorize M6 integration"
        )
    if value.get("production_activation") is not False:
        raise DigitalTwinPhotorealM5LinkError(
            "Photoreal M5 link cannot activate production"
        )
    link_id = str(value.get("link_id") or "").strip().lower()
    if not LINK_ID_RE.fullmatch(link_id) or link_id != _link_id(value):
        raise DigitalTwinPhotorealM5LinkError(
            "Photoreal M5 link id no longer matches exact evidence"
        )
    if not isinstance(value.get("finalized_utc"), str) or not str(
        value["finalized_utc"]
    ).endswith("Z"):
        raise DigitalTwinPhotorealM5LinkError(
            "Photoreal M5 finalized timestamp is invalid"
        )
    return dict(value)


def _validated_inputs(
    root: Path,
    *,
    composition_authority_dir_path: Path,
    acceptance_dir_path: Path,
    photoreal_link_authority_dir_path: Path,
    bodyrig_revision: str,
) -> tuple[
    dict[str, Any],
    bytes,
    dict[str, Any],
    dict[str, tuple[bytes, dict[str, Any], bytes, dict[str, Any]]],
]:
    revision = str(bodyrig_revision or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise DigitalTwinPhotorealM5LinkError(
            "BodyRig revision must be an exact 40-character commit SHA"
        )

    link_raw, link_hint = _read_json_bytes(
        photoreal_link_authority_dir_path / "authority.json",
        "M4 Photoreal link authority",
    )
    person_id = str(link_hint.get("person_id") or "")
    person_revision = str(link_hint.get("person_revision") or "")
    link_id = str(link_hint.get("link_id") or "")
    expected_link_dir = photoreal_link_dir(
        root,
        person_id=person_id,
        person_revision=person_revision,
        link_id=link_id,
    ).resolve()
    if expected_link_dir != photoreal_link_authority_dir_path.resolve():
        raise DigitalTwinPhotorealM5LinkError(
            "M4 Photoreal link directory is not the canonical Person/link path"
        )

    try:
        m4_link = read_photoreal_link(
            root,
            person_id=person_id,
            person_revision=person_revision,
            link_id=link_id,
            composition_authority_dir_path=composition_authority_dir_path,
        )
    except (DigitalTwinPhotorealLinkError, OSError, ValueError) as exc:
        raise DigitalTwinPhotorealM5LinkError(
            f"M4 Photoreal link is invalid: {exc}"
        ) from exc
    if str(m4_link.get("bodyrig_revision") or "").lower() != revision:
        raise DigitalTwinPhotorealM5LinkError(
            "M4 Photoreal link and M5 were not finalized from the same BodyRig revision"
        )
    if m4_link.get("m5_photoreal_integration_eligible") is not True:
        raise DigitalTwinPhotorealM5LinkError(
            "M4 Photoreal link does not authorize M5 integration"
        )

    try:
        m5_status = inspect_digital_twin_platform_acceptance(
            composition_authority_dir=composition_authority_dir_path,
            acceptance_dir=acceptance_dir_path,
        )
    except (DigitalTwinPlatformAcceptanceError, OSError, ValueError) as exc:
        raise DigitalTwinPhotorealM5LinkError(
            f"M5 platform acceptance is invalid: {exc}"
        ) from exc
    if (
        m5_status.get("m5_ready") is not True
        or m5_status.get("digital_twin_ready") is not False
        or m5_status.get("production_activation") is not False
    ):
        raise DigitalTwinPhotorealM5LinkError(
            "M5 platform acceptance is not complete and non-activating"
        )

    evidence: dict[
        str, tuple[bytes, dict[str, Any], bytes, dict[str, Any]]
    ] = {}
    for platform in PLATFORMS:
        status = (m5_status.get("platforms") or {}).get(platform)
        if (
            not isinstance(status, Mapping)
            or status.get("ready") is not True
            or status.get("state") != "complete"
        ):
            raise DigitalTwinPhotorealM5LinkError(
                f"M5 {platform} realization is not complete"
            )
        directory = platform_evidence_dir(acceptance_dir_path, platform)
        input_raw, platform_input = _read_json_bytes(
            directory / "platform-input.json",
            f"M5 {platform} platform input",
        )
        realization_raw, realization = _read_json_bytes(
            directory / "realization.json",
            f"M5 {platform} realization",
        )
        if str(platform_input.get("bodyrig_revision") or "").lower() != revision:
            raise DigitalTwinPhotorealM5LinkError(
                f"M5 {platform} input revision differs from Photoreal authority"
            )
        if str(platform_input.get("body_id") or "") != str(m4_link.get("body_id") or ""):
            raise DigitalTwinPhotorealM5LinkError(
                f"M5 {platform} body differs from Photoreal authority"
            )
        if str(platform_input.get("composition_authority_id") or "") != str(
            m4_link.get("composition_authority_id") or ""
        ):
            raise DigitalTwinPhotorealM5LinkError(
                f"M5 {platform} composition differs from Photoreal authority"
            )
        if str(status.get("realization_sha256") or "").lower() != _sha256_bytes(
            realization_raw
        ):
            raise DigitalTwinPhotorealM5LinkError(
                f"M5 {platform} realization digest differs from canonical status"
            )
        evidence[platform] = (
            input_raw,
            platform_input,
            realization_raw,
            realization,
        )

    return m4_link, link_raw, m5_status, evidence


def build_photoreal_m5_link(
    person_library: str | os.PathLike[str],
    *,
    composition_authority_dir_path: str | os.PathLike[str],
    acceptance_dir_path: str | os.PathLike[str],
    photoreal_link_authority_dir_path: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    root = Path(person_library).expanduser().resolve()
    composition_dir = Path(composition_authority_dir_path).expanduser().resolve()
    acceptance = Path(acceptance_dir_path).expanduser().resolve()
    photoreal_link = Path(photoreal_link_authority_dir_path).expanduser().resolve()
    m4_link, m4_link_raw, m5_status, evidence = _validated_inputs(
        root,
        composition_authority_dir_path=composition_dir,
        acceptance_dir_path=acceptance,
        photoreal_link_authority_dir_path=photoreal_link,
        bodyrig_revision=bodyrig_revision,
    )

    windows_input_raw, _windows_input, windows_realization_raw, windows_realization = evidence[
        "windows-unity-univrm"
    ]
    quest_input_raw, _quest_input, quest_realization_raw, quest_realization = evidence[
        "android-quest-class"
    ]

    authority: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "link_id": "",
        "person_id": str(m4_link["person_id"]),
        "person_revision": str(m4_link["person_revision"]),
        "assembly_fingerprint": str(m4_link["assembly_fingerprint"]),
        "body_revision": str(m4_link["body_revision"]),
        "body_id": str(m4_link["body_id"]),
        "body_package_sha256": str(m4_link["body_package_sha256"]),
        "bodyrig_revision": str(m4_link["bodyrig_revision"]),
        "composition_authority_id": str(m4_link["composition_authority_id"]),
        "m4_photoreal_link_id": str(m4_link["link_id"]),
        "m4_photoreal_link_file_sha256": _sha256_bytes(m4_link_raw),
        "m4_photoreal_link_content_sha256": _content_sha256(m4_link),
        "windows_platform_input_sha256": _sha256_bytes(windows_input_raw),
        "windows_realization_sha256": _sha256_bytes(windows_realization_raw),
        "quest_platform_input_sha256": _sha256_bytes(quest_input_raw),
        "quest_realization_sha256": _sha256_bytes(quest_realization_raw),
        "windows_device_model": str(windows_realization.get("device_model") or ""),
        "quest_device_model": str(quest_realization.get("device_model") or ""),
        "visual_authority": VISUAL_AUTHORITY,
        "photoreal_m5_ready": True,
        "m6_photoreal_release_eligible": True,
        "finalized_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "production_activation": False,
    }
    authority["link_id"] = _link_id(authority)
    return validate_photoreal_m5_link_structure(authority)


def write_photoreal_m5_link(
    person_library: str | os.PathLike[str],
    *,
    composition_authority_dir_path: str | os.PathLike[str],
    acceptance_dir_path: str | os.PathLike[str],
    photoreal_link_authority_dir_path: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    root = Path(person_library).expanduser().resolve()
    authority = build_photoreal_m5_link(
        root,
        composition_authority_dir_path=composition_authority_dir_path,
        acceptance_dir_path=acceptance_dir_path,
        photoreal_link_authority_dir_path=photoreal_link_authority_dir_path,
        bodyrig_revision=bodyrig_revision,
    )
    target = photoreal_m5_link_dir(
        root,
        person_id=str(authority["person_id"]),
        person_revision=str(authority["person_revision"]),
        link_id=str(authority["link_id"]),
    )
    if target.exists():
        raise DigitalTwinPhotorealM5LinkError(
            "exact Photoreal M5 link already exists; create-only authority cannot be overwritten"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.parent / f".{authority['link_id']}.staging-{uuid.uuid4().hex}"
    acceptance = Path(acceptance_dir_path).expanduser().resolve()
    try:
        stage.mkdir(parents=False, exist_ok=False)
        shutil.copyfile(
            Path(photoreal_link_authority_dir_path).expanduser().resolve()
            / "authority.json",
            stage / "m4-photoreal-link.json",
        )
        for platform, prefix in (
            ("windows-unity-univrm", "windows"),
            ("android-quest-class", "quest"),
        ):
            evidence_dir = platform_evidence_dir(acceptance, platform)
            shutil.copyfile(
                evidence_dir / "platform-input.json",
                stage / f"{prefix}-platform-input.json",
            )
            shutil.copyfile(
                evidence_dir / "realization.json",
                stage / f"{prefix}-realization.json",
            )
        (stage / "authority.json").write_bytes(
            _canonical_json_bytes(authority) + b"\n"
        )
        os.replace(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return read_photoreal_m5_link(
        root,
        person_id=str(authority["person_id"]),
        person_revision=str(authority["person_revision"]),
        link_id=str(authority["link_id"]),
        composition_authority_dir_path=composition_authority_dir_path,
        acceptance_dir_path=acceptance_dir_path,
        photoreal_link_authority_dir_path=photoreal_link_authority_dir_path,
    )


def read_photoreal_m5_link(
    person_library: str | os.PathLike[str],
    *,
    person_id: str,
    person_revision: str,
    link_id: str,
    composition_authority_dir_path: str | os.PathLike[str],
    acceptance_dir_path: str | os.PathLike[str],
    photoreal_link_authority_dir_path: str | os.PathLike[str],
) -> dict[str, Any]:
    root = Path(person_library).expanduser().resolve()
    directory = photoreal_m5_link_dir(
        root,
        person_id=person_id,
        person_revision=person_revision,
        link_id=link_id,
    )
    if not directory.is_dir():
        raise DigitalTwinPhotorealM5LinkError("Photoreal M5 link authority is missing")

    _authority_raw, authority = _read_json_bytes(
        directory / "authority.json",
        "Photoreal M5 link authority",
    )
    value = validate_photoreal_m5_link_structure(authority)
    if str(value.get("link_id") or "") != link_id:
        raise DigitalTwinPhotorealM5LinkError(
            "Photoreal M5 link path does not match contained link id"
        )

    frozen_m4_raw, _frozen_m4 = _read_json_bytes(
        directory / "m4-photoreal-link.json",
        "frozen M4 Photoreal link",
    )
    if _sha256_bytes(frozen_m4_raw) != str(value["m4_photoreal_link_file_sha256"]):
        raise DigitalTwinPhotorealM5LinkError(
            "frozen M4 Photoreal link bytes were modified"
        )

    for prefix, input_field, realization_field in (
        ("windows", "windows_platform_input_sha256", "windows_realization_sha256"),
        ("quest", "quest_platform_input_sha256", "quest_realization_sha256"),
    ):
        input_raw, _ = _read_json_bytes(
            directory / f"{prefix}-platform-input.json",
            f"frozen {prefix} M5 platform input",
        )
        realization_raw, _ = _read_json_bytes(
            directory / f"{prefix}-realization.json",
            f"frozen {prefix} M5 realization",
        )
        if _sha256_bytes(input_raw) != str(value[input_field]):
            raise DigitalTwinPhotorealM5LinkError(
                f"frozen {prefix} M5 platform input bytes were modified"
            )
        if _sha256_bytes(realization_raw) != str(value[realization_field]):
            raise DigitalTwinPhotorealM5LinkError(
                f"frozen {prefix} M5 realization bytes were modified"
            )

    rebuilt = build_photoreal_m5_link(
        root,
        composition_authority_dir_path=composition_authority_dir_path,
        acceptance_dir_path=acceptance_dir_path,
        photoreal_link_authority_dir_path=photoreal_link_authority_dir_path,
        bodyrig_revision=str(value["bodyrig_revision"]),
    )
    rebuilt["finalized_utc"] = value["finalized_utc"]
    if rebuilt != value:
        raise DigitalTwinPhotorealM5LinkError(
            "Photoreal M5 link no longer matches exact M4/Photoreal/M5 evidence"
        )
    return value
