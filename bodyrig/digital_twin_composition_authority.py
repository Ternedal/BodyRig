from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .hands_feet_nails_authority import (
    HandsFeetNailsAuthorityError,
    _assembly_identity,
    _release_identity,
)
from .hands_feet_nails_release_authority import (
    HandsFeetNailsReleaseAuthorityError,
    validate_release_authority_structure as validate_hands_nails_release_authority,
)
from .models import BodyCue, SpeechTiming
from .motor import resolve_motor_state_v2
from .package import MRBodyError, validate_bodyprint, validate_package
from .wardrobe_release_authority import (
    WardrobeReleaseAuthorityError,
    validate_release_authority_structure as validate_wardrobe_release_authority,
)

FORMAT = "bodyrig-digital-twin-composition-authority"
VERSION = 1
POLICY_REVISION = "bodyrig-digital-twin-composition-authority-v1"
PROBE_FORMAT = "bodyrig-digital-twin-embodiment-probe"
PROBE_VERSION = 1
AUTHORITY_ID_RE = re.compile(r"^dtcomp-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")

COMPONENT_FIELDS = {
    "release_id",
    "review_id",
    "source_capture_id",
    "authority_sha256",
    "authority_content_sha256",
}
TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "authority_id",
    "person_id",
    "person_revision",
    "assembly_fingerprint",
    "body_revision",
    "body_id",
    "body_package_sha256",
    "bodyprint_sha256",
    "bodyrig_revision",
    "assembly_receipt_sha256",
    "assembly_receipt_content_sha256",
    "body_release_status_sha256",
    "body_release_status_content_sha256",
    "audition_receipt_sha256",
    "hands_feet_nails",
    "wardrobe",
    "embodiment_probe_sha256",
    "finalized_utc",
    "state",
    "source_observed_embodiment",
    "production_activation",
}


class DigitalTwinCompositionAuthorityError(RuntimeError):
    pass


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise DigitalTwinCompositionAuthorityError(f"{label} is not a canonical SHA-256")
    return text


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _content_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json_bytes(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DigitalTwinCompositionAuthorityError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise DigitalTwinCompositionAuthorityError(f"{label} must be a JSON object")
    return raw, value


def _component_identity(value: Mapping[str, Any], raw: bytes) -> dict[str, str]:
    return {
        "release_id": str(value["release_id"]),
        "review_id": str(value["review_id"]),
        "source_capture_id": str(value["source_capture_id"]),
        "authority_sha256": _sha256_bytes(raw),
        "authority_content_sha256": _content_sha256(value),
    }


def build_embodiment_probe(*, body_id: str, bodyprint: Mapping[str, Any]) -> dict[str, Any]:
    """Build the fixed renderer-neutral M4 Motor State v2 probe.

    The performed state intentionally exercises the full semantic motor surface.
    Only Motor State v2's explicit ``embodiment.observed`` receipt is treated as
    source-observed BodyPrint evidence; neutral/default execution values are not.
    """

    try:
        observed_bodyprint = validate_bodyprint(dict(bodyprint))
    except MRBodyError as exc:
        raise DigitalTwinCompositionAuthorityError(f"BodyPrint is invalid: {exc}") from exc

    cue = BodyCue(
        utterance_id="bodyrig-m4-embodiment-probe",
        body_id=body_id,
        emotion="neutral",
        intensity=0.65,
        energy=0.55,
        gesture="present",
        gaze="user",
        posture="neutral",
        duration_ms=1200,
    )
    speech = SpeechTiming(
        utterance_id=cue.utterance_id,
        state="update",
        elapsed_ms=600,
        viseme="AA",
        amplitude=0.5,
    )
    motor_state = resolve_motor_state_v2(
        body_id=body_id,
        bodyprint=observed_bodyprint,
        cue=cue,
        speech=speech,
    )

    required_motor_fields = ("motion", "expression", "gesture", "gaze", "posture", "speech")
    if motor_state.get("type") != "bodyrig-motor-state" or motor_state.get("version") != 2:
        raise DigitalTwinCompositionAuthorityError("embodiment probe did not produce Motor State v2")
    if any(field not in motor_state for field in required_motor_fields):
        raise DigitalTwinCompositionAuthorityError("embodiment probe did not exercise the full motor surface")
    speech_state = motor_state.get("speech")
    if not isinstance(speech_state, Mapping):
        raise DigitalTwinCompositionAuthorityError("embodiment probe speech timing is missing")
    if motor_state.get("utterance_id") != cue.utterance_id:
        raise DigitalTwinCompositionAuthorityError("embodiment probe utterance identity is incoherent")
    if speech_state.get("viseme") != speech.viseme or "amplitude" not in speech_state:
        raise DigitalTwinCompositionAuthorityError("embodiment probe viseme/amplitude timing is incoherent")

    embodiment = motor_state.get("embodiment")
    observed = embodiment.get("observed") if isinstance(embodiment, Mapping) else None
    if not isinstance(observed, Mapping) or not observed:
        raise DigitalTwinCompositionAuthorityError(
            "BodyPrint has no source-observed motion/expression/runtime values for M4 embodiment authority"
        )

    return {
        "format": PROBE_FORMAT,
        "version": PROBE_VERSION,
        "body_id": body_id,
        "cue": cue.model_dump(exclude_none=True),
        "speech": speech.model_dump(exclude_none=True),
        "motor_state": motor_state,
        "source_observed": True,
        "production_activation": False,
    }


def _authority_id(value: Mapping[str, Any]) -> str:
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
            "assembly_receipt_sha256",
            "assembly_receipt_content_sha256",
            "body_release_status_sha256",
            "body_release_status_content_sha256",
            "audition_receipt_sha256",
            "hands_feet_nails",
            "wardrobe",
            "embodiment_probe_sha256",
        )
    }
    return "dtcomp-" + hashlib.sha256(_canonical_json_bytes(evidence)).hexdigest()[:32]


def _validate_component_binding(
    binding: Any,
    *,
    value: Mapping[str, Any],
    label: str,
) -> dict[str, str]:
    if not isinstance(binding, Mapping) or set(binding) != COMPONENT_FIELDS:
        raise DigitalTwinCompositionAuthorityError(f"{label} composition binding fields are not canonical")
    expected = {
        "release_id": str(value["release_id"]),
        "review_id": str(value["review_id"]),
        "source_capture_id": str(value["source_capture_id"]),
        "authority_content_sha256": _content_sha256(value),
    }
    actual = {
        "release_id": str(binding.get("release_id") or ""),
        "review_id": str(binding.get("review_id") or ""),
        "source_capture_id": str(binding.get("source_capture_id") or ""),
        "authority_content_sha256": _sha(binding.get("authority_content_sha256"), f"{label} authority content SHA-256"),
    }
    _sha(binding.get("authority_sha256"), f"{label} exact authority SHA-256")
    if actual != expected:
        raise DigitalTwinCompositionAuthorityError(f"{label} composition binding no longer matches exact finalized authority identity")
    return dict(binding)


def validate_composition_authority_structure(
    value: Mapping[str, Any],
    *,
    assembly_receipt: Mapping[str, Any],
    body_release_status: Mapping[str, Any],
    hands_nails_authority: Mapping[str, Any],
    wardrobe_authority: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise DigitalTwinCompositionAuthorityError("digital-twin composition authority fields are not canonical")
    version = value.get("version")
    if value.get("format") != FORMAT or isinstance(version, bool) or version != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise DigitalTwinCompositionAuthorityError("digital-twin composition authority format/version/policy mismatch")

    try:
        assembly = _assembly_identity(assembly_receipt)
        release = _release_identity(body_release_status, assembly)
        hands = validate_hands_nails_release_authority(
            hands_nails_authority,
            assembly_receipt=assembly_receipt,
            body_release_status=body_release_status,
        )
        wardrobe = validate_wardrobe_release_authority(
            wardrobe_authority,
            assembly_receipt=assembly_receipt,
            body_release_status=body_release_status,
        )
    except (HandsFeetNailsAuthorityError, HandsFeetNailsReleaseAuthorityError, WardrobeReleaseAuthorityError) as exc:
        raise DigitalTwinCompositionAuthorityError(str(exc)) from exc

    exact_identity = {
        "person_id": assembly["person_id"],
        "person_revision": assembly["person_revision"],
        "assembly_fingerprint": assembly["assembly_fingerprint"],
        "body_revision": assembly["body_revision"],
        "body_id": assembly["body_id"],
        "body_package_sha256": release["package_sha256"],
    }
    for field, expected in exact_identity.items():
        if str(value.get(field) or "").lower() != str(expected).lower():
            raise DigitalTwinCompositionAuthorityError(f"digital-twin composition no longer matches exact {field}")

    revision = str(value.get("bodyrig_revision") or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise DigitalTwinCompositionAuthorityError("digital-twin composition BodyRig revision is invalid")
    if str(hands.get("bodyrig_revision") or "").lower() != revision or str(wardrobe.get("bodyrig_revision") or "").lower() != revision:
        raise DigitalTwinCompositionAuthorityError("M2/M3 authorities were not finalized by the same BodyRig revision as M4")

    if _sha(value.get("assembly_receipt_content_sha256"), "assembly receipt content SHA-256") != _content_sha256(assembly_receipt):
        raise DigitalTwinCompositionAuthorityError("composition no longer matches Person assembly content")
    _sha(value.get("assembly_receipt_sha256"), "exact assembly receipt SHA-256")
    if _sha(value.get("body_release_status_content_sha256"), "body release content SHA-256") != _content_sha256(body_release_status):
        raise DigitalTwinCompositionAuthorityError("composition no longer matches body release status content")
    _sha(value.get("body_release_status_sha256"), "exact body release status SHA-256")

    audition = assembly_receipt.get("audition")
    audition_sha = _sha(audition.get("receipt_sha256") if isinstance(audition, Mapping) else None, "assembly audition receipt SHA-256")
    if _sha(value.get("audition_receipt_sha256"), "composition audition receipt SHA-256") != audition_sha:
        raise DigitalTwinCompositionAuthorityError("composition no longer matches the assembly-bound ModelRig/VoiceRig audition receipt")

    _validate_component_binding(value.get("hands_feet_nails"), value=hands, label="M2 hands/feet/nails")
    _validate_component_binding(value.get("wardrobe"), value=wardrobe, label="M3 wardrobe")
    _sha(value.get("bodyprint_sha256"), "BodyPrint SHA-256")
    _sha(value.get("embodiment_probe_sha256"), "embodiment probe SHA-256")

    authority_id = str(value.get("authority_id") or "").strip().lower()
    if not AUTHORITY_ID_RE.fullmatch(authority_id) or authority_id != _authority_id(value):
        raise DigitalTwinCompositionAuthorityError("digital-twin composition authority id no longer matches bound evidence")
    if not isinstance(value.get("finalized_utc"), str) or not str(value["finalized_utc"]).endswith("Z"):
        raise DigitalTwinCompositionAuthorityError("digital-twin composition finalized timestamp is invalid")
    if value.get("state") != "complete" or value.get("source_observed_embodiment") is not True:
        raise DigitalTwinCompositionAuthorityError("digital-twin composition is not finalized source-observed M4 authority")
    if value.get("production_activation") is not False:
        raise DigitalTwinCompositionAuthorityError("M4 composition authority cannot activate production")
    return dict(value)


def composition_authority_dir(
    root: str | os.PathLike[str],
    person_id: str,
    person_revision: str,
    authority_id: str,
) -> Path:
    for label, item in (("person id", person_id), ("person revision", person_revision), ("authority id", authority_id)):
        text = str(item or "")
        if not text or Path(text).name != text or "/" in text or "\\" in text:
            raise DigitalTwinCompositionAuthorityError(f"{label} is not a safe path component")
    if not AUTHORITY_ID_RE.fullmatch(authority_id):
        raise DigitalTwinCompositionAuthorityError("digital-twin composition authority id is invalid")
    return (
        Path(root).expanduser().resolve()
        / "digital-twin-composition-authorities"
        / person_id
        / person_revision
        / authority_id
    )


def _bodyprint_from_package(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        validated = validate_package(path)
        with zipfile.ZipFile(path, "r") as archive:
            raw = archive.read("bodyprint.json")
    except (MRBodyError, OSError, zipfile.BadZipFile, KeyError) as exc:
        raise DigitalTwinCompositionAuthorityError(f"body package is invalid: {exc}") from exc
    return validated.bodyprint, raw


def write_composition_authority(
    root: str | os.PathLike[str],
    *,
    assembly_receipt_path: str | os.PathLike[str],
    body_release_status_path: str | os.PathLike[str],
    hands_nails_authority_path: str | os.PathLike[str],
    wardrobe_authority_path: str | os.PathLike[str],
    body_package_path: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    revision = str(bodyrig_revision or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise DigitalTwinCompositionAuthorityError("BodyRig revision must be an exact 40-character commit SHA")

    assembly_path = Path(assembly_receipt_path).expanduser().resolve()
    release_path = Path(body_release_status_path).expanduser().resolve()
    hands_path = Path(hands_nails_authority_path).expanduser().resolve()
    wardrobe_path = Path(wardrobe_authority_path).expanduser().resolve()
    package_path = Path(body_package_path).expanduser().resolve()
    assembly_raw, assembly_receipt = _read_json_bytes(assembly_path, "Person assembly receipt")
    release_raw, body_release_status = _read_json_bytes(release_path, "body release status")
    hands_raw, hands_nails_authority = _read_json_bytes(hands_path, "M2 hands/feet/nails authority")
    wardrobe_raw, wardrobe_authority = _read_json_bytes(wardrobe_path, "M3 wardrobe authority")

    try:
        assembly = _assembly_identity(assembly_receipt)
        release = _release_identity(body_release_status, assembly)
        hands = validate_hands_nails_release_authority(
            hands_nails_authority,
            assembly_receipt=assembly_receipt,
            body_release_status=body_release_status,
        )
        wardrobe = validate_wardrobe_release_authority(
            wardrobe_authority,
            assembly_receipt=assembly_receipt,
            body_release_status=body_release_status,
        )
    except (HandsFeetNailsAuthorityError, HandsFeetNailsReleaseAuthorityError, WardrobeReleaseAuthorityError) as exc:
        raise DigitalTwinCompositionAuthorityError(str(exc)) from exc

    if str(hands.get("bodyrig_revision") or "").lower() != revision or str(wardrobe.get("bodyrig_revision") or "").lower() != revision:
        raise DigitalTwinCompositionAuthorityError("M2 and M3 must be finalized by the exact checkout used for M4")

    bodyprint, bodyprint_raw = _bodyprint_from_package(package_path)
    package_sha = _sha256_file(package_path)
    if package_sha != release["package_sha256"]:
        raise DigitalTwinCompositionAuthorityError("exact .mrbody package bytes do not match the promoted body release")
    validated = validate_package(package_path)
    if str(validated.manifest.get("id") or "").lower() != assembly["body_id"]:
        raise DigitalTwinCompositionAuthorityError("body package id does not match the exact Person assembly body")

    probe = build_embodiment_probe(body_id=assembly["body_id"], bodyprint=bodyprint)
    probe_raw = _canonical_json_bytes(probe)
    audition = assembly_receipt.get("audition")
    audition_sha = _sha(audition.get("receipt_sha256") if isinstance(audition, Mapping) else None, "assembly audition receipt SHA-256")

    authority: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "authority_id": "",
        "person_id": assembly["person_id"],
        "person_revision": assembly["person_revision"],
        "assembly_fingerprint": assembly["assembly_fingerprint"],
        "body_revision": assembly["body_revision"],
        "body_id": assembly["body_id"],
        "body_package_sha256": package_sha,
        "bodyprint_sha256": _sha256_bytes(bodyprint_raw),
        "bodyrig_revision": revision,
        "assembly_receipt_sha256": _sha256_bytes(assembly_raw),
        "assembly_receipt_content_sha256": _content_sha256(assembly_receipt),
        "body_release_status_sha256": _sha256_bytes(release_raw),
        "body_release_status_content_sha256": _content_sha256(body_release_status),
        "audition_receipt_sha256": audition_sha,
        "hands_feet_nails": _component_identity(hands, hands_raw),
        "wardrobe": _component_identity(wardrobe, wardrobe_raw),
        "embodiment_probe_sha256": _sha256_bytes(probe_raw),
        "finalized_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "state": "complete",
        "source_observed_embodiment": True,
        "production_activation": False,
    }
    authority["authority_id"] = _authority_id(authority)
    validate_composition_authority_structure(
        authority,
        assembly_receipt=assembly_receipt,
        body_release_status=body_release_status,
        hands_nails_authority=hands,
        wardrobe_authority=wardrobe,
    )

    target = composition_authority_dir(
        root,
        authority["person_id"],
        authority["person_revision"],
        authority["authority_id"],
    )
    if target.exists():
        raise DigitalTwinCompositionAuthorityError("exact M4 composition authority already exists; create-only evidence cannot be overwritten")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.parent / f".{authority['authority_id']}.staging-{uuid.uuid4().hex}"
    try:
        stage.mkdir(parents=False, exist_ok=False)
        (stage / "person-assembly-receipt.json").write_bytes(assembly_raw)
        (stage / "body-release-status.json").write_bytes(release_raw)
        (stage / "hands-feet-nails-authority.json").write_bytes(hands_raw)
        (stage / "wardrobe-authority.json").write_bytes(wardrobe_raw)
        (stage / "bodyprint.json").write_bytes(bodyprint_raw)
        (stage / "embodiment-probe.json").write_bytes(probe_raw)
        (stage / "authority.json").write_bytes(_canonical_json_bytes(authority) + b"\n")
        os.replace(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return read_composition_authority(
        root,
        person_id=authority["person_id"],
        person_revision=authority["person_revision"],
        authority_id=authority["authority_id"],
    )


def read_composition_authority(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    person_revision: str,
    authority_id: str,
    body_package_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    directory = composition_authority_dir(root, person_id, person_revision, authority_id)
    if not directory.is_dir():
        raise DigitalTwinCompositionAuthorityError("digital-twin composition authority is missing")

    _, authority = _read_json_bytes(directory / "authority.json", "M4 authority")
    assembly_raw, assembly = _read_json_bytes(directory / "person-assembly-receipt.json", "frozen Person assembly receipt")
    release_raw, release = _read_json_bytes(directory / "body-release-status.json", "frozen body release status")
    hands_raw, hands = _read_json_bytes(directory / "hands-feet-nails-authority.json", "frozen M2 authority")
    wardrobe_raw, wardrobe = _read_json_bytes(directory / "wardrobe-authority.json", "frozen M3 authority")
    bodyprint_raw, bodyprint = _read_json_bytes(directory / "bodyprint.json", "frozen BodyPrint")
    probe_raw, probe = _read_json_bytes(directory / "embodiment-probe.json", "frozen embodiment probe")

    hands_binding = authority.get("hands_feet_nails")
    wardrobe_binding = authority.get("wardrobe")
    if not isinstance(hands_binding, Mapping) or not isinstance(wardrobe_binding, Mapping):
        raise DigitalTwinCompositionAuthorityError("M4 component bindings are missing or invalid")
    if _sha256_bytes(assembly_raw) != _sha(authority.get("assembly_receipt_sha256"), "exact assembly receipt SHA-256"):
        raise DigitalTwinCompositionAuthorityError("frozen Person assembly receipt bytes were modified")
    if _sha256_bytes(release_raw) != _sha(authority.get("body_release_status_sha256"), "exact body release status SHA-256"):
        raise DigitalTwinCompositionAuthorityError("frozen body release status bytes were modified")
    if _sha256_bytes(hands_raw) != _sha(hands_binding.get("authority_sha256"), "exact M2 authority SHA-256"):
        raise DigitalTwinCompositionAuthorityError("frozen M2 authority bytes were modified")
    if _sha256_bytes(wardrobe_raw) != _sha(wardrobe_binding.get("authority_sha256"), "exact M3 authority SHA-256"):
        raise DigitalTwinCompositionAuthorityError("frozen M3 authority bytes were modified")
    if _sha256_bytes(bodyprint_raw) != _sha(authority.get("bodyprint_sha256"), "BodyPrint SHA-256"):
        raise DigitalTwinCompositionAuthorityError("frozen BodyPrint bytes were modified")
    if _sha256_bytes(probe_raw) != _sha(authority.get("embodiment_probe_sha256"), "embodiment probe SHA-256"):
        raise DigitalTwinCompositionAuthorityError("frozen embodiment probe bytes were modified")

    try:
        validated_bodyprint = validate_bodyprint(bodyprint)
    except MRBodyError as exc:
        raise DigitalTwinCompositionAuthorityError(f"frozen BodyPrint is invalid: {exc}") from exc
    expected_probe = build_embodiment_probe(body_id=str(authority.get("body_id") or ""), bodyprint=validated_bodyprint)
    if probe != expected_probe or probe_raw != _canonical_json_bytes(expected_probe):
        raise DigitalTwinCompositionAuthorityError("embodiment probe is not the exact deterministic Motor State v2 M4 probe")

    validate_composition_authority_structure(
        authority,
        assembly_receipt=assembly,
        body_release_status=release,
        hands_nails_authority=hands,
        wardrobe_authority=wardrobe,
    )
    if str(authority.get("authority_id") or "") != authority_id:
        raise DigitalTwinCompositionAuthorityError("authority path does not match contained M4 authority id")

    if body_package_path is not None:
        package_path = Path(body_package_path).expanduser().resolve()
        bodyprint_live, bodyprint_live_raw = _bodyprint_from_package(package_path)
        if _sha256_file(package_path) != str(authority["body_package_sha256"]):
            raise DigitalTwinCompositionAuthorityError("live body package no longer matches M4 authority")
        if _sha256_bytes(bodyprint_live_raw) != str(authority["bodyprint_sha256"]) or bodyprint_live != bodyprint:
            raise DigitalTwinCompositionAuthorityError("live BodyPrint no longer matches M4 authority")

    return authority
