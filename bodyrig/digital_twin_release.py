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

from .acceptance_status import AcceptanceStatusError, inspect_acceptance_dir
from .digital_twin_composition_authority import _content_sha256
from .digital_twin_platform_acceptance import (
    DigitalTwinPlatformAcceptanceError,
    _composition_bundle,
    build_platform_input,
    inspect_digital_twin_platform_acceptance,
    platform_evidence_dir,
)
from .reference_acceptance_policy import apply_reference_policy

FORMAT = "bodyrig-digital-twin-release"
VERSION = 1
POLICY_REVISION = "bodyrig-digital-twin-release-v1"
RELEASE_ID_RE = re.compile(r"^dtrelease-[0-9a-f]{32}$")
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
    "bodyprint_sha256",
    "bodyrig_revision",
    "composition_authority_id",
    "composition_authority_sha256",
    "composition_authority_content_sha256",
    "gate_a_sha256",
    "body_physical_release_sha256",
    "windows_platform_input_sha256",
    "windows_realization_sha256",
    "windows_renderer_attestation_sha256",
    "quest_platform_input_sha256",
    "quest_realization_sha256",
    "quest_renderer_attestation_sha256",
    "finalized_utc",
    "state",
    "digital_twin_ready",
    "production_activation",
}


class DigitalTwinReleaseError(RuntimeError):
    pass


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise DigitalTwinReleaseError(f"Could not hash evidence file: {path}") from exc
    return digest.hexdigest()


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise DigitalTwinReleaseError(f"{label} is not a canonical SHA-256")
    return text


def _read_json_bytes(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DigitalTwinReleaseError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise DigitalTwinReleaseError(f"{label} must be a JSON object: {path}")
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
            "bodyprint_sha256",
            "bodyrig_revision",
            "composition_authority_id",
            "composition_authority_sha256",
            "composition_authority_content_sha256",
            "gate_a_sha256",
            "body_physical_release_sha256",
            "windows_platform_input_sha256",
            "windows_realization_sha256",
            "windows_renderer_attestation_sha256",
            "quest_platform_input_sha256",
            "quest_realization_sha256",
            "quest_renderer_attestation_sha256",
        )
    }
    return "dtrelease-" + hashlib.sha256(_canonical_json_bytes(evidence)).hexdigest()[:32]


def validate_release_authority_structure(
    value: Mapping[str, Any],
    *,
    composition_authority: Mapping[str, Any],
    platform_acceptance_status: Mapping[str, Any],
    body_release_status: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise DigitalTwinReleaseError("digital-twin final release fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise DigitalTwinReleaseError("digital-twin final release format/version/policy mismatch")

    if composition_authority.get("format") != "bodyrig-digital-twin-composition-authority" or composition_authority.get("version") != 1:
        raise DigitalTwinReleaseError("M6 requires finalized M4 composition authority")
    exact_identity = {
        "person_id": composition_authority.get("person_id"),
        "person_revision": composition_authority.get("person_revision"),
        "assembly_fingerprint": composition_authority.get("assembly_fingerprint"),
        "body_revision": composition_authority.get("body_revision"),
        "body_id": composition_authority.get("body_id"),
        "body_package_sha256": composition_authority.get("body_package_sha256"),
        "bodyprint_sha256": composition_authority.get("bodyprint_sha256"),
        "bodyrig_revision": composition_authority.get("bodyrig_revision"),
        "composition_authority_id": composition_authority.get("authority_id"),
    }
    for field, expected in exact_identity.items():
        if str(value.get(field) or "").lower() != str(expected or "").lower():
            raise DigitalTwinReleaseError(f"M6 release no longer matches exact {field}")

    revision = str(value.get("bodyrig_revision") or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise DigitalTwinReleaseError("M6 BodyRig revision is invalid")
    for field in TOP_FIELDS:
        if field.endswith("_sha256"):
            _sha(value.get(field), f"M6 {field}")

    if _sha(value.get("composition_authority_content_sha256"), "M4 authority content SHA-256") != _content_sha256(composition_authority):
        raise DigitalTwinReleaseError("M6 release no longer matches M4 authority content")

    if body_release_status.get("production_ready") is not True or body_release_status.get("production_activation") is not True:
        raise DigitalTwinReleaseError("body physical release is not production-ready/activated")
    if str(body_release_status.get("person_id") or "") != str(value.get("person_id") or ""):
        raise DigitalTwinReleaseError("body release person id differs from M6 release")
    if str(body_release_status.get("body_revision") or "") != str(value.get("body_revision") or ""):
        raise DigitalTwinReleaseError("body release revision differs from M6 release")
    if str(body_release_status.get("body_id") or "") != str(value.get("body_id") or ""):
        raise DigitalTwinReleaseError("body release body id differs from M6 release")
    if _sha(body_release_status.get("package_sha256"), "body release package SHA-256") != str(value["body_package_sha256"]):
        raise DigitalTwinReleaseError("body release package differs from M6 release")

    if platform_acceptance_status.get("format") != "bodyrig-digital-twin-platform-status" or platform_acceptance_status.get("version") != 1:
        raise DigitalTwinReleaseError("M6 requires canonical M5 platform status")
    if (
        platform_acceptance_status.get("m5_ready") is not True
        or platform_acceptance_status.get("digital_twin_ready") is not False
        or platform_acceptance_status.get("production_activation") is not False
    ):
        raise DigitalTwinReleaseError("M5 platform status is not complete and non-activating")
    platforms = platform_acceptance_status.get("platforms")
    if not isinstance(platforms, Mapping):
        raise DigitalTwinReleaseError("M5 platform status lacks exact platform evidence")
    for platform, release_field in (
        ("windows-unity-univrm", "windows_realization_sha256"),
        ("android-quest-class", "quest_realization_sha256"),
    ):
        gate = platforms.get(platform)
        if not isinstance(gate, Mapping) or gate.get("ready") is not True or gate.get("state") != "complete":
            raise DigitalTwinReleaseError(f"M5 {platform} realization is not complete")
        if _sha(gate.get("realization_sha256"), f"M5 {platform} realization SHA-256") != str(value[release_field]):
            raise DigitalTwinReleaseError(f"M6 release no longer matches M5 {platform} realization")

    release_id = str(value.get("release_id") or "").strip().lower()
    if not RELEASE_ID_RE.fullmatch(release_id) or release_id != _release_id(value):
        raise DigitalTwinReleaseError("M6 release id no longer matches exact bound evidence")
    if not isinstance(value.get("finalized_utc"), str) or not str(value["finalized_utc"]).endswith("Z"):
        raise DigitalTwinReleaseError("M6 finalized timestamp is invalid")
    if value.get("state") != "released" or value.get("digital_twin_ready") is not True or value.get("production_activation") is not True:
        raise DigitalTwinReleaseError("M6 authority is not an activating full digital-twin release")
    return dict(value)


def release_dir(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    person_revision: str,
    release_id: str,
) -> Path:
    for label, item in (("person id", person_id), ("person revision", person_revision), ("release id", release_id)):
        text = str(item or "")
        if not text or Path(text).name != text or "/" in text or "\\" in text:
            raise DigitalTwinReleaseError(f"{label} is not a safe path component")
    if not RELEASE_ID_RE.fullmatch(release_id):
        raise DigitalTwinReleaseError("digital-twin release id is invalid")
    return (
        Path(root).expanduser().resolve()
        / "digital-twin-releases"
        / person_id
        / person_revision
        / release_id
    )


def _chain_evidence(
    *,
    composition_authority_dir: Path,
    acceptance_dir: Path,
    expected_bodyrig_revision: str | None = None,
) -> dict[str, Any]:
    acceptance = acceptance_dir.expanduser().resolve()
    composition_dir = composition_authority_dir.expanduser().resolve()
    if not acceptance.is_dir():
        raise DigitalTwinReleaseError(f"physical acceptance directory is missing: {acceptance}")
    try:
        physical = apply_reference_policy(inspect_acceptance_dir(acceptance))
    except AcceptanceStatusError as exc:
        raise DigitalTwinReleaseError(f"canonical body physical release is invalid: {exc}") from exc
    if physical.state != "complete" or physical.gate != "release":
        raise DigitalTwinReleaseError("canonical body physical release has not reached activating final release")

    body_id = str(physical.body_id or "")
    revision = str(physical.bodyrig_revision or "").strip().lower()
    if not body_id or not REVISION_RE.fullmatch(revision):
        raise DigitalTwinReleaseError("canonical body physical release lacks exact body/revision identity")
    if expected_bodyrig_revision is not None and revision != str(expected_bodyrig_revision).strip().lower():
        raise DigitalTwinReleaseError("operator checkout revision differs from canonical body physical release")
    package_path = acceptance / f"{body_id}.mrbody"
    if not package_path.is_file():
        raise DigitalTwinReleaseError("canonical accepted .mrbody is missing")

    try:
        composition, composition_raw, _probe, _probe_raw = _composition_bundle(
            composition_dir,
            package_path=package_path,
        )
        m5_status = inspect_digital_twin_platform_acceptance(
            composition_authority_dir=composition_dir,
            acceptance_dir=acceptance,
        )
    except DigitalTwinPlatformAcceptanceError as exc:
        raise DigitalTwinReleaseError(str(exc)) from exc
    if m5_status.get("m5_ready") is not True:
        raise DigitalTwinReleaseError("M5 Windows/Quest digital-twin realization is not complete")
    if str(composition.get("bodyrig_revision") or "").lower() != revision:
        raise DigitalTwinReleaseError("M4 composition and canonical physical release use different BodyRig revisions")
    if str(composition.get("body_id") or "") != body_id:
        raise DigitalTwinReleaseError("M4 composition body differs from canonical physical release")

    gate_a_path = acceptance / "bodyrig-acceptance.json"
    physical_release_path = acceptance / "bodyrig-release-acceptance.json"
    gate_a_raw, _gate_a = _read_json_bytes(gate_a_path, "Gate A acceptance")
    physical_release_raw, physical_release_value = _read_json_bytes(physical_release_path, "canonical body final release")
    if physical_release_value.get("production_activation") is not True or physical_release_value.get("release_gate_pass") is not True:
        raise DigitalTwinReleaseError("canonical body final release artifact is not activating PASS")

    platform_values: dict[str, dict[str, Any]] = {}
    for platform, prefix in (("windows-unity-univrm", "windows"), ("android-quest-class", "quest")):
        try:
            expected_input, _motor_raw = build_platform_input(
                composition_authority_dir=composition_dir,
                acceptance_dir=acceptance,
                platform=platform,
            )
        except DigitalTwinPlatformAcceptanceError as exc:
            raise DigitalTwinReleaseError(str(exc)) from exc
        evidence = platform_evidence_dir(acceptance, platform)
        input_path = evidence / "platform-input.json"
        realization_path = evidence / "realization.json"
        input_raw, input_value = _read_json_bytes(input_path, f"M5 {platform} platform input")
        realization_raw, realization_value = _read_json_bytes(realization_path, f"M5 {platform} realization")
        if input_raw != _canonical_json_bytes(expected_input) or input_value != expected_input:
            raise DigitalTwinReleaseError(f"M5 {platform} platform input no longer matches recomputed authority")
        expected_realization_sha = _sha(
            (m5_status.get("platforms") or {}).get(platform, {}).get("realization_sha256"),
            f"M5 {platform} realization SHA-256",
        )
        if _sha256_bytes(realization_raw) != expected_realization_sha:
            raise DigitalTwinReleaseError(f"M5 {platform} realization bytes no longer match M5 status")
        if str(realization_value.get("bodyrig_revision") or "").lower() != revision:
            raise DigitalTwinReleaseError(f"M5 {platform} realization revision differs from canonical release revision")
        if str(realization_value.get("body_id") or "") != body_id:
            raise DigitalTwinReleaseError(f"M5 {platform} realization body differs from canonical release body")
        if realization_value.get("production_activation") is not False:
            raise DigitalTwinReleaseError(f"M5 {platform} realization must remain non-activating")
        platform_values[prefix] = {
            "input_raw": input_raw,
            "input": input_value,
            "realization_raw": realization_raw,
            "realization": realization_value,
        }

    return {
        "composition": composition,
        "composition_raw": composition_raw,
        "m5_status": m5_status,
        "revision": revision,
        "body_id": body_id,
        "package_sha256": _sha256_file(package_path),
        "gate_a_raw": gate_a_raw,
        "physical_release_raw": physical_release_raw,
        "physical_release": physical_release_value,
        "windows": platform_values["windows"],
        "quest": platform_values["quest"],
    }


def _authority_from_chain(chain: Mapping[str, Any]) -> dict[str, Any]:
    composition = chain["composition"]
    windows = chain["windows"]
    quest = chain["quest"]
    authority: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "release_id": "",
        "person_id": str(composition["person_id"]),
        "person_revision": str(composition["person_revision"]),
        "assembly_fingerprint": str(composition["assembly_fingerprint"]),
        "body_revision": str(composition["body_revision"]),
        "body_id": str(composition["body_id"]),
        "body_package_sha256": str(composition["body_package_sha256"]),
        "bodyprint_sha256": str(composition["bodyprint_sha256"]),
        "bodyrig_revision": str(chain["revision"]),
        "composition_authority_id": str(composition["authority_id"]),
        "composition_authority_sha256": _sha256_bytes(chain["composition_raw"]),
        "composition_authority_content_sha256": _content_sha256(composition),
        "gate_a_sha256": _sha256_bytes(chain["gate_a_raw"]),
        "body_physical_release_sha256": _sha256_bytes(chain["physical_release_raw"]),
        "windows_platform_input_sha256": _sha256_bytes(windows["input_raw"]),
        "windows_realization_sha256": _sha256_bytes(windows["realization_raw"]),
        "windows_renderer_attestation_sha256": str(windows["input"]["renderer_attestation_sha256"]),
        "quest_platform_input_sha256": _sha256_bytes(quest["input_raw"]),
        "quest_realization_sha256": _sha256_bytes(quest["realization_raw"]),
        "quest_renderer_attestation_sha256": str(quest["input"]["renderer_attestation_sha256"]),
        "finalized_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "state": "released",
        "digital_twin_ready": True,
        "production_activation": True,
    }
    if str(chain["package_sha256"]) != authority["body_package_sha256"]:
        raise DigitalTwinReleaseError("canonical accepted package bytes differ from M4 composition package")
    authority["release_id"] = _release_id(authority)
    return authority


def write_release(
    root: str | os.PathLike[str],
    *,
    composition_authority_dir: str | os.PathLike[str],
    acceptance_dir: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    revision = str(bodyrig_revision or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise DigitalTwinReleaseError("BodyRig revision must be an exact 40-character commit SHA")
    composition_dir = Path(composition_authority_dir).expanduser().resolve()
    acceptance = Path(acceptance_dir).expanduser().resolve()
    chain = _chain_evidence(
        composition_authority_dir=composition_dir,
        acceptance_dir=acceptance,
        expected_bodyrig_revision=revision,
    )
    authority = _authority_from_chain(chain)

    body_release_status = {
        "person_id": authority["person_id"],
        "body_revision": authority["body_revision"],
        "body_id": authority["body_id"],
        "package_sha256": authority["body_package_sha256"],
        "production_ready": True,
        "production_activation": True,
    }
    validate_release_authority_structure(
        authority,
        composition_authority=chain["composition"],
        platform_acceptance_status=chain["m5_status"],
        body_release_status=body_release_status,
    )

    target = release_dir(
        root,
        person_id=authority["person_id"],
        person_revision=authority["person_revision"],
        release_id=authority["release_id"],
    )
    if target.exists():
        raise DigitalTwinReleaseError("exact M6 digital-twin release already exists; create-only authority cannot be overwritten")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.parent / f".{authority['release_id']}.staging-{uuid.uuid4().hex}"
    try:
        stage.mkdir(parents=False, exist_ok=False)
        (stage / "composition-authority.json").write_bytes(chain["composition_raw"])
        (stage / "gate-a.json").write_bytes(chain["gate_a_raw"])
        (stage / "body-physical-release.json").write_bytes(chain["physical_release_raw"])
        (stage / "windows-platform-input.json").write_bytes(chain["windows"]["input_raw"])
        (stage / "windows-realization.json").write_bytes(chain["windows"]["realization_raw"])
        (stage / "quest-platform-input.json").write_bytes(chain["quest"]["input_raw"])
        (stage / "quest-realization.json").write_bytes(chain["quest"]["realization_raw"])
        (stage / "authority.json").write_bytes(_canonical_json_bytes(authority) + b"\n")
        os.replace(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return read_release(
        root,
        person_id=authority["person_id"],
        person_revision=authority["person_revision"],
        release_id=authority["release_id"],
        composition_authority_dir=composition_dir,
        acceptance_dir=acceptance,
    )


def read_release(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    person_revision: str,
    release_id: str,
    composition_authority_dir: str | os.PathLike[str],
    acceptance_dir: str | os.PathLike[str],
) -> dict[str, Any]:
    directory = release_dir(root, person_id=person_id, person_revision=person_revision, release_id=release_id)
    if not directory.is_dir():
        raise DigitalTwinReleaseError("canonical M6 digital-twin release is missing")
    _, authority = _read_json_bytes(directory / "authority.json", "M6 authority")

    frozen_specs = (
        ("composition-authority.json", "composition_authority_sha256"),
        ("gate-a.json", "gate_a_sha256"),
        ("body-physical-release.json", "body_physical_release_sha256"),
        ("windows-platform-input.json", "windows_platform_input_sha256"),
        ("windows-realization.json", "windows_realization_sha256"),
        ("quest-platform-input.json", "quest_platform_input_sha256"),
        ("quest-realization.json", "quest_realization_sha256"),
    )
    for filename, field in frozen_specs:
        path = directory / filename
        if _sha256_file(path) != _sha(authority.get(field), f"M6 {field}"):
            raise DigitalTwinReleaseError(f"frozen M6 evidence bytes were modified: {filename}")

    chain = _chain_evidence(
        composition_authority_dir=Path(composition_authority_dir),
        acceptance_dir=Path(acceptance_dir),
        expected_bodyrig_revision=str(authority.get("bodyrig_revision") or ""),
    )
    expected = _authority_from_chain(chain)
    expected["finalized_utc"] = authority.get("finalized_utc")
    if _release_id(expected) != str(authority.get("release_id") or ""):
        raise DigitalTwinReleaseError("live M4/M5/body evidence no longer matches the canonical M6 release")
    for field in TOP_FIELDS - {"finalized_utc"}:
        if authority.get(field) != expected.get(field):
            raise DigitalTwinReleaseError(f"live release chain drifted from M6 field {field}")
    if str(authority.get("release_id") or "") != release_id:
        raise DigitalTwinReleaseError("M6 release path does not match contained release id")

    body_release_status = {
        "person_id": authority["person_id"],
        "body_revision": authority["body_revision"],
        "body_id": authority["body_id"],
        "package_sha256": authority["body_package_sha256"],
        "production_ready": True,
        "production_activation": True,
    }
    validate_release_authority_structure(
        authority,
        composition_authority=chain["composition"],
        platform_acceptance_status=chain["m5_status"],
        body_release_status=body_release_status,
    )
    return authority
