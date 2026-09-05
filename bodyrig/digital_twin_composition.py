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

from .hands_feet_nails_authority import HandsFeetNailsAuthorityError, _assembly_identity, _release_identity
from .hands_feet_nails_release_authority import (
    HandsFeetNailsReleaseAuthorityError,
    read_release_authority as read_hands_release_authority,
    release_authority_dir as hands_release_authority_dir,
    validate_release_authority_structure as validate_hands_release_structure,
)
from .models import BodyCue, SpeechTiming
from .motor import resolve_motor_state_v2
from .package import MRBodyError, validate_package
from .person_assembly import PersonAssemblyError, read_receipt as read_assembly_receipt, receipt_path as assembly_receipt_path
from .person_audition import (
    PersonAuditionError,
    receipt_path as audition_receipt_path,
    receipt_sha256 as audition_receipt_sha256,
    verify_audition,
)
from .wardrobe_release_authority import (
    WardrobeReleaseAuthorityError,
    read_release_authority as read_wardrobe_release_authority,
    release_authority_dir as wardrobe_release_authority_dir,
    validate_release_authority_structure as validate_wardrobe_release_structure,
)

FORMAT = "bodyrig-digital-twin-composition-authority"
VERSION = 1
POLICY_REVISION = "bodyrig-digital-twin-composition-authority-v1"
COMPOSITION_ID_RE = re.compile(r"^dtcompose-[0-9a-f]{32}$")
PERSON_ID_RE = re.compile(r"^person-[0-9a-f]{32}$")
PERSON_REVISION_RE = re.compile(r"^person-r[0-9]{4}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
PROBE_UTTERANCE_ID = "bodyrig-m4-composition-probe-v1"
REQUIRED_OBSERVED = {
    "motion": ("energy", "gesture_frequency", "gesture_amplitude", "head_motion", "turn_speed"),
    "expression": ("blink_rate_per_min", "gaze_strength", "head_tilt", "speech_motion"),
    "runtime": ("idle_strength", "gaze_smoothing", "gesture_intensity", "breathing_strength"),
}
OBSERVED_FIELDS = {
    "motion": ("energy", "gesture_frequency", "gesture_amplitude", "head_motion", "turn_speed", "walk_cadence_spm"),
    "expression": ("blink_rate_per_min", "gaze_strength", "head_tilt", "speech_motion"),
    "runtime": ("idle_strength", "gaze_smoothing", "gesture_intensity", "breathing_strength"),
}
TOP_FIELDS = {
    "format", "version", "policy_revision", "composition_id", "created_utc", "person_id", "person_revision",
    "assembly_fingerprint", "body_revision", "body_id", "body_package_sha256", "bodyrig_revision",
    "assembly_receipt_sha256", "assembly_receipt_canonical_sha256", "body_release_status_canonical_sha256",
    "audition_id", "audition_receipt_sha256", "audition_audio_sha256", "voice_revision", "voice_id",
    "voice_package_sha256", "personality_revision", "personality_instructions_sha256", "personality_style_notes_sha256",
    "hands_release_id", "hands_authority_sha256", "hands_authority_canonical_sha256", "hands_bodyrig_revision",
    "wardrobe_release_id", "wardrobe_authority_sha256", "wardrobe_authority_canonical_sha256", "wardrobe_bodyrig_revision",
    "bodyprint_sha256", "observed_embodiment_sha256", "observed_embodiment_fields", "embodiment_probe",
    "embodiment_probe_sha256", "motion_authority", "expression_authority", "voice_timing_authority",
    "presentation_authority", "state", "source_grounded", "composition_complete", "production_activation",
}


class DigitalTwinCompositionError(RuntimeError):
    pass


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise DigitalTwinCompositionError(f"{label} is not a canonical SHA-256")
    return text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    return _sha256_bytes(_canonical_json_bytes(value))


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DigitalTwinCompositionError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise DigitalTwinCompositionError(f"{label} must contain a JSON object")
    return value


def _body_package(bodies_root: str | os.PathLike[str], body_id: str) -> Path:
    path = Path(bodies_root).expanduser().resolve() / f"{body_id}.mrbody"
    if not path.is_file():
        raise DigitalTwinCompositionError("canonical installed body package is missing for M4 composition")
    return path


def _bodyprint_bytes(package: Path) -> bytes:
    try:
        with zipfile.ZipFile(package, "r") as archive:
            raw = archive.read("bodyprint.json")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise DigitalTwinCompositionError("could not read exact bodyprint.json from canonical body package") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DigitalTwinCompositionError("exact bodyprint.json is unreadable") from exc
    if not isinstance(value, dict):
        raise DigitalTwinCompositionError("exact bodyprint.json is not an object")
    return raw


def _expected_observed(bodyprint: Mapping[str, Any]) -> dict[str, float]:
    observed: dict[str, float] = {}
    missing: list[str] = []
    for section_name, required in REQUIRED_OBSERVED.items():
        section = bodyprint.get(section_name)
        if not isinstance(section, Mapping):
            missing.extend(f"{section_name}.{field}" for field in required)
            continue
        for field in required:
            value = section.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                missing.append(f"{section_name}.{field}")
    if missing:
        raise DigitalTwinCompositionError(
            "M4 composition requires actually observed BodyPrint embodiment fields; missing: " + ", ".join(missing)
        )
    for section_name, allowed in OBSERVED_FIELDS.items():
        section = bodyprint.get(section_name)
        if not isinstance(section, Mapping):
            continue
        for field in allowed:
            value = section.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            observed[field] = float(value)
    return observed


def build_embodiment_probe(*, body_id: str, bodyprint: Mapping[str, Any]) -> dict[str, Any]:
    expected_observed = _expected_observed(bodyprint)
    cue = BodyCue(
        utterance_id=PROBE_UTTERANCE_ID,
        body_id=body_id,
        emotion="neutral",
        intensity=0.72,
        energy=0.68,
        gesture="composition_probe",
        gaze="user",
        posture="upright",
        duration_ms=2400,
    )
    speech = SpeechTiming(
        utterance_id=PROBE_UTTERANCE_ID,
        state="update",
        elapsed_ms=800,
        viseme="AA",
        amplitude=0.64,
    )
    probe = resolve_motor_state_v2(body_id=body_id, bodyprint=bodyprint, cue=cue, speech=speech)
    validate_embodiment_probe(probe, body_id=body_id, bodyprint=bodyprint)
    if dict(probe["embodiment"]["observed"]) != expected_observed:
        raise DigitalTwinCompositionError("Motor State v2 embodiment receipt does not equal exact observed BodyPrint fields")
    return probe


def validate_embodiment_probe(value: Mapping[str, Any], *, body_id: str, bodyprint: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("type") != "bodyrig-motor-state" or value.get("version") != 2:
        raise DigitalTwinCompositionError("M4 embodiment probe is not canonical Motor State v2")
    if str(value.get("body_id") or "") != body_id or value.get("utterance_id") != PROBE_UTTERANCE_ID:
        raise DigitalTwinCompositionError("M4 embodiment probe body/utterance identity is invalid")
    motion = value.get("motion")
    expression = value.get("expression")
    gesture = value.get("gesture")
    gaze = value.get("gaze")
    posture = value.get("posture")
    speech = value.get("speech")
    embodiment = value.get("embodiment")
    if not isinstance(motion, Mapping) or set(motion) != {"energy", "head_motion"}:
        raise DigitalTwinCompositionError("M4 embodiment probe has no canonical motion realization")
    if not isinstance(expression, Mapping) or expression.get("emotion") != "neutral" or expression.get("intensity") != 0.72:
        raise DigitalTwinCompositionError("M4 embodiment probe has no canonical expression realization")
    if not isinstance(gesture, Mapping) or gesture.get("id") != "composition_probe":
        raise DigitalTwinCompositionError("M4 embodiment probe has no canonical gesture realization")
    if not isinstance(gaze, Mapping) or gaze.get("target") != "user":
        raise DigitalTwinCompositionError("M4 embodiment probe has no canonical gaze realization")
    if not isinstance(posture, Mapping) or posture.get("id") != "upright":
        raise DigitalTwinCompositionError("M4 embodiment probe has no canonical posture realization")
    if value.get("duration_ms") != 2400:
        raise DigitalTwinCompositionError("M4 embodiment probe duration is invalid")
    if not isinstance(speech, Mapping) or speech.get("state") != "update" or speech.get("elapsed_ms") != 800 or speech.get("viseme") != "AA":
        raise DigitalTwinCompositionError("M4 embodiment probe has no coherent speech timing/viseme realization")
    amplitude = speech.get("amplitude")
    if isinstance(amplitude, bool) or not isinstance(amplitude, (int, float)) or not 0.0 <= float(amplitude) <= 1.0:
        raise DigitalTwinCompositionError("M4 embodiment probe speech amplitude is invalid")
    if not isinstance(embodiment, Mapping) or embodiment.get("source") != "modelrig-bodyprint-v1":
        raise DigitalTwinCompositionError("M4 embodiment probe has no source-observed BodyPrint receipt")
    observed = embodiment.get("observed")
    if not isinstance(observed, Mapping):
        raise DigitalTwinCompositionError("M4 embodiment probe observed receipt is missing")
    required_flat = {field for fields in REQUIRED_OBSERVED.values() for field in fields}
    if not required_flat <= set(observed):
        raise DigitalTwinCompositionError("M4 embodiment probe omits required source-observed behavior fields")
    for field, item in observed.items():
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise DigitalTwinCompositionError(f"M4 observed embodiment field {field} is invalid")
    if bodyprint is not None and dict(observed) != _expected_observed(bodyprint):
        raise DigitalTwinCompositionError("M4 embodiment probe contains default/invented observations or misses exact BodyPrint observations")
    return dict(value)


def _composition_id(*, person_id: str, person_revision: str, assembly_sha: str, body_package_sha: str, hands_sha: str, wardrobe_sha: str, bodyprint_sha: str, probe_sha: str, bodyrig_revision: str) -> str:
    payload = {
        "person_id": person_id,
        "person_revision": person_revision,
        "assembly_receipt_sha256": assembly_sha,
        "body_package_sha256": body_package_sha,
        "hands_authority_sha256": hands_sha,
        "wardrobe_authority_sha256": wardrobe_sha,
        "bodyprint_sha256": bodyprint_sha,
        "embodiment_probe_sha256": probe_sha,
        "bodyrig_revision": bodyrig_revision,
    }
    return "dtcompose-" + hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()[:32]


def composition_dir(root: str | os.PathLike[str], person_id: str, person_revision: str, composition_id: str) -> Path:
    person = str(person_id or "").strip().lower()
    revision = str(person_revision or "").strip().lower()
    composition = str(composition_id or "").strip().lower()
    if not PERSON_ID_RE.fullmatch(person) or not PERSON_REVISION_RE.fullmatch(revision) or not COMPOSITION_ID_RE.fullmatch(composition):
        raise DigitalTwinCompositionError("M4 composition path identity is invalid")
    return Path(root).expanduser().resolve() / "digital-twin-compositions" / person / revision / composition


def validate_composition_structure(
    value: Mapping[str, Any], *, assembly_receipt: Mapping[str, Any], body_release_status: Mapping[str, Any],
    hands_authority: Mapping[str, Any], wardrobe_authority: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise DigitalTwinCompositionError("digital-twin composition authority fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise DigitalTwinCompositionError("digital-twin composition authority format/version/policy mismatch")
    try:
        assembly = _assembly_identity(assembly_receipt)
        body_release = _release_identity(body_release_status, assembly)
        hands = validate_hands_release_structure(hands_authority, assembly_receipt=assembly_receipt, body_release_status=body_release_status)
        wardrobe = validate_wardrobe_release_structure(wardrobe_authority, assembly_receipt=assembly_receipt, body_release_status=body_release_status)
    except (HandsFeetNailsAuthorityError, HandsFeetNailsReleaseAuthorityError, WardrobeReleaseAuthorityError) as exc:
        raise DigitalTwinCompositionError(f"M4 component authority is invalid: {exc}") from exc
    if body_release_status.get("production_ready") is not True or body_release_status.get("production_activation") is not True:
        raise DigitalTwinCompositionError("M4 composition requires the exact physically activated Person body release")
    exact = {
        "person_id": assembly["person_id"], "person_revision": assembly["person_revision"],
        "assembly_fingerprint": assembly["assembly_fingerprint"], "body_revision": assembly["body_revision"],
        "body_id": assembly["body_id"], "body_package_sha256": body_release["package_sha256"],
        "hands_release_id": hands["release_id"], "hands_bodyrig_revision": hands["bodyrig_revision"],
        "wardrobe_release_id": wardrobe["release_id"], "wardrobe_bodyrig_revision": wardrobe["bodyrig_revision"],
    }
    for field, expected in exact.items():
        if str(value.get(field) or "").lower() != str(expected).lower():
            raise DigitalTwinCompositionError(f"digital-twin composition no longer matches exact {field}")
    revision = str(value.get("bodyrig_revision") or "").lower()
    composition_id = str(value.get("composition_id") or "").lower()
    if not SHA40_RE.fullmatch(revision) or not COMPOSITION_ID_RE.fullmatch(composition_id):
        raise DigitalTwinCompositionError("digital-twin composition id/revision is invalid")
    if _sha(value.get("assembly_receipt_canonical_sha256"), "assembly canonical SHA-256") != canonical_json_sha256(assembly_receipt):
        raise DigitalTwinCompositionError("digital-twin composition assembly semantic hash differs from supplied Person Revision")
    if _sha(value.get("body_release_status_canonical_sha256"), "body release status SHA-256") != canonical_json_sha256(body_release_status):
        raise DigitalTwinCompositionError("digital-twin composition body-release status differs from supplied authority")
    if _sha(value.get("hands_authority_canonical_sha256"), "M2 canonical SHA-256") != canonical_json_sha256(hands_authority):
        raise DigitalTwinCompositionError("digital-twin composition M2 semantic hash differs from supplied finalized authority")
    if _sha(value.get("wardrobe_authority_canonical_sha256"), "M3 canonical SHA-256") != canonical_json_sha256(wardrobe_authority):
        raise DigitalTwinCompositionError("digital-twin composition M3 semantic hash differs from supplied finalized authority")
    for field in (
        "assembly_receipt_sha256", "audition_receipt_sha256", "audition_audio_sha256", "voice_package_sha256",
        "personality_instructions_sha256", "personality_style_notes_sha256", "hands_authority_sha256",
        "wardrobe_authority_sha256", "bodyprint_sha256", "observed_embodiment_sha256", "embodiment_probe_sha256",
    ):
        _sha(value.get(field), field)
    body = assembly_receipt.get("body") if isinstance(assembly_receipt.get("body"), Mapping) else {}
    voice = assembly_receipt.get("voice") if isinstance(assembly_receipt.get("voice"), Mapping) else {}
    personality = assembly_receipt.get("personality") if isinstance(assembly_receipt.get("personality"), Mapping) else {}
    audition = assembly_receipt.get("audition") if isinstance(assembly_receipt.get("audition"), Mapping) else {}
    expected_text = {
        "audition_id": audition.get("audition_id"), "audition_receipt_sha256": audition.get("receipt_sha256"),
        "voice_revision": voice.get("revision_id"), "voice_id": voice.get("voice_id"), "voice_package_sha256": voice.get("package_sha256"),
        "personality_revision": personality.get("revision_id"), "personality_instructions_sha256": personality.get("instructions_sha256"),
        "personality_style_notes_sha256": personality.get("style_notes_sha256"),
    }
    for field, expected in expected_text.items():
        if str(value.get(field) or "").lower() != str(expected or "").lower():
            raise DigitalTwinCompositionError(f"digital-twin composition no longer matches assembly {field}")
    probe = value.get("embodiment_probe")
    if not isinstance(probe, Mapping):
        raise DigitalTwinCompositionError("digital-twin composition embodiment probe is missing")
    validate_embodiment_probe(probe, body_id=assembly["body_id"])
    if _sha(value.get("embodiment_probe_sha256"), "embodiment probe SHA-256") != canonical_json_sha256(probe):
        raise DigitalTwinCompositionError("digital-twin composition embodiment probe hash is invalid")
    observed = probe["embodiment"]["observed"]
    if _sha(value.get("observed_embodiment_sha256"), "observed embodiment SHA-256") != canonical_json_sha256(observed):
        raise DigitalTwinCompositionError("digital-twin composition observed embodiment hash is invalid")
    fields = value.get("observed_embodiment_fields")
    expected_fields = sorted(str(field) for field in observed)
    if not isinstance(fields, list) or fields != expected_fields:
        raise DigitalTwinCompositionError("digital-twin composition observed field inventory is invalid")
    for flag in ("motion_authority", "expression_authority", "voice_timing_authority", "presentation_authority", "composition_complete"):
        if value.get(flag) is not True:
            raise DigitalTwinCompositionError(f"digital-twin composition did not establish {flag}")
    if value.get("state") != "complete" or value.get("source_grounded") is not True or value.get("production_activation") is not False:
        raise DigitalTwinCompositionError("digital-twin composition must be complete, source-grounded and non-activating")
    expected_id = _composition_id(
        person_id=assembly["person_id"], person_revision=assembly["person_revision"],
        assembly_sha=_sha(value["assembly_receipt_sha256"], "assembly receipt SHA-256"),
        body_package_sha=body_release["package_sha256"],
        hands_sha=_sha(value["hands_authority_sha256"], "M2 authority SHA-256"),
        wardrobe_sha=_sha(value["wardrobe_authority_sha256"], "M3 authority SHA-256"),
        bodyprint_sha=_sha(value["bodyprint_sha256"], "BodyPrint SHA-256"),
        probe_sha=_sha(value["embodiment_probe_sha256"], "embodiment probe SHA-256"),
        bodyrig_revision=revision,
    )
    if composition_id != expected_id:
        raise DigitalTwinCompositionError("digital-twin composition id no longer matches exact evidence identity")
    if str(body.get("revision_id") or "") != assembly["body_revision"]:
        raise DigitalTwinCompositionError("assembly body revision changed during composition validation")
    return dict(value)


def write_composition_authority(
    root: str | os.PathLike[str], bodies_root: str | os.PathLike[str], *, person_id: str, person_revision: str,
    body_release_status: Mapping[str, Any], hands_release_id: str, wardrobe_release_id: str, bodyrig_revision: str,
) -> dict[str, Any]:
    people_root = Path(root).expanduser().resolve()
    person = str(person_id or "").strip().lower()
    person_revision = str(person_revision or "").strip().lower()
    revision = str(bodyrig_revision or "").strip().lower()
    if not PERSON_ID_RE.fullmatch(person) or not PERSON_REVISION_RE.fullmatch(person_revision) or not SHA40_RE.fullmatch(revision):
        raise DigitalTwinCompositionError("M4 Person/revision/checkout identity is invalid")
    try:
        assembly_receipt = read_assembly_receipt(people_root, person_id=person, person_revision=person_revision)
        assembly = _assembly_identity(assembly_receipt)
        body_release = _release_identity(body_release_status, assembly)
    except (PersonAssemblyError, HandsFeetNailsAuthorityError) as exc:
        raise DigitalTwinCompositionError(f"M4 assembly/body authority failed: {exc}") from exc
    if body_release_status.get("production_ready") is not True or body_release_status.get("production_activation") is not True:
        raise DigitalTwinCompositionError("M4 composition requires a physically activated body release")
    assembly_path = assembly_receipt_path(people_root, person, person_revision)
    assembly_sha = _sha256_file(assembly_path)

    audition_info = assembly_receipt.get("audition")
    if not isinstance(audition_info, Mapping):
        raise DigitalTwinCompositionError("M4 assembly has no audition binding")
    audition_id = str(audition_info.get("audition_id") or "")
    try:
        audition = verify_audition(people_root, person_id=person, audition_id=audition_id, assembly_fingerprint=assembly["assembly_fingerprint"])
        audition_sha = audition_receipt_sha256(people_root, person_id=person, audition_id=audition_id)
    except PersonAuditionError as exc:
        raise DigitalTwinCompositionError(f"M4 audition authority failed: {exc}") from exc
    if audition_sha != str(audition_info.get("receipt_sha256") or ""):
        raise DigitalTwinCompositionError("M4 canonical audition receipt hash differs from assembly binding")

    try:
        hands = read_hands_release_authority(
            people_root, assembly_receipt=assembly_receipt, body_release_status=body_release_status, release_id=hands_release_id,
        )
        wardrobe = read_wardrobe_release_authority(
            people_root, assembly_receipt=assembly_receipt, body_release_status=body_release_status, release_id=wardrobe_release_id,
        )
    except (HandsFeetNailsReleaseAuthorityError, WardrobeReleaseAuthorityError) as exc:
        raise DigitalTwinCompositionError(f"M4 finalized presentation authority failed: {exc}") from exc
    hands_path = hands_release_authority_dir(people_root, person, person_revision, hands_release_id) / "authority.json"
    wardrobe_path = wardrobe_release_authority_dir(people_root, person, person_revision, wardrobe_release_id) / "authority.json"
    hands_sha = _sha256_file(hands_path)
    wardrobe_sha = _sha256_file(wardrobe_path)

    package = _body_package(bodies_root, assembly["body_id"])
    package_sha = _sha256_file(package)
    if package_sha != body_release["package_sha256"]:
        raise DigitalTwinCompositionError("canonical installed body package SHA differs from Person body release")
    try:
        validated = validate_package(package)
    except MRBodyError as exc:
        raise DigitalTwinCompositionError(f"M4 body package is invalid: {exc}") from exc
    if str(validated.manifest.get("id") or "") != assembly["body_id"]:
        raise DigitalTwinCompositionError("M4 body package id differs from Person assembly")
    bodyprint_raw = _bodyprint_bytes(package)
    bodyprint_sha = _sha256_bytes(bodyprint_raw)
    try:
        raw_bodyprint = json.loads(bodyprint_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DigitalTwinCompositionError("M4 BodyPrint bytes are invalid JSON") from exc
    if raw_bodyprint != validated.bodyprint:
        raise DigitalTwinCompositionError("M4 validated BodyPrint differs from exact package bytes")
    probe = build_embodiment_probe(body_id=assembly["body_id"], bodyprint=validated.bodyprint)
    probe_sha = canonical_json_sha256(probe)
    observed = dict(probe["embodiment"]["observed"])

    composition_id = _composition_id(
        person_id=person, person_revision=person_revision, assembly_sha=assembly_sha, body_package_sha=package_sha,
        hands_sha=hands_sha, wardrobe_sha=wardrobe_sha, bodyprint_sha=bodyprint_sha, probe_sha=probe_sha, bodyrig_revision=revision,
    )
    target = composition_dir(people_root, person, person_revision, composition_id)
    if target.exists():
        raise DigitalTwinCompositionError("refusing to overwrite existing digital-twin composition authority")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    stage.mkdir(parents=False, exist_ok=False)
    try:
        shutil.copyfile(assembly_path, stage / "assembly-receipt.json")
        shutil.copyfile(audition_receipt_path(people_root, person, audition_id), stage / "audition-receipt.json")
        shutil.copyfile(hands_path, stage / "hands-authority.json")
        shutil.copyfile(wardrobe_path, stage / "wardrobe-authority.json")
        (stage / "bodyprint.json").write_bytes(bodyprint_raw)
        (stage / "body-release-status.json").write_bytes(_canonical_json_bytes(body_release_status) + b"\n")
        (stage / "embodiment-probe.json").write_bytes(_canonical_json_bytes(probe) + b"\n")
        voice = assembly_receipt["voice"]
        personality = assembly_receipt["personality"]
        receipt = {
            "format": FORMAT, "version": VERSION, "policy_revision": POLICY_REVISION, "composition_id": composition_id,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "person_id": person, "person_revision": person_revision, "assembly_fingerprint": assembly["assembly_fingerprint"],
            "body_revision": assembly["body_revision"], "body_id": assembly["body_id"], "body_package_sha256": package_sha,
            "bodyrig_revision": revision, "assembly_receipt_sha256": assembly_sha,
            "assembly_receipt_canonical_sha256": canonical_json_sha256(assembly_receipt),
            "body_release_status_canonical_sha256": canonical_json_sha256(body_release_status),
            "audition_id": audition_id, "audition_receipt_sha256": audition_sha, "audition_audio_sha256": str(audition["audio_sha256"]),
            "voice_revision": str(voice["revision_id"]), "voice_id": str(voice["voice_id"]),
            "voice_package_sha256": str(voice["package_sha256"]), "personality_revision": str(personality["revision_id"]),
            "personality_instructions_sha256": str(personality["instructions_sha256"]),
            "personality_style_notes_sha256": str(personality["style_notes_sha256"]),
            "hands_release_id": str(hands["release_id"]), "hands_authority_sha256": hands_sha,
            "hands_authority_canonical_sha256": canonical_json_sha256(hands), "hands_bodyrig_revision": str(hands["bodyrig_revision"]),
            "wardrobe_release_id": str(wardrobe["release_id"]), "wardrobe_authority_sha256": wardrobe_sha,
            "wardrobe_authority_canonical_sha256": canonical_json_sha256(wardrobe), "wardrobe_bodyrig_revision": str(wardrobe["bodyrig_revision"]),
            "bodyprint_sha256": bodyprint_sha, "observed_embodiment_sha256": canonical_json_sha256(observed),
            "observed_embodiment_fields": sorted(observed), "embodiment_probe": probe, "embodiment_probe_sha256": probe_sha,
            "motion_authority": True, "expression_authority": True, "voice_timing_authority": True,
            "presentation_authority": True, "state": "complete", "source_grounded": True,
            "composition_complete": True, "production_activation": False,
        }
        validate_composition_structure(
            receipt, assembly_receipt=assembly_receipt, body_release_status=body_release_status,
            hands_authority=hands, wardrobe_authority=wardrobe,
        )
        (stage / "authority.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8", newline="\n",
        )
        os.replace(stage, target)
        return read_composition_authority(
            people_root, bodies_root, person_id=person, person_revision=person_revision,
            composition_id=composition_id, body_release_status=body_release_status,
        )
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def read_composition_authority(
    root: str | os.PathLike[str], bodies_root: str | os.PathLike[str], *, person_id: str, person_revision: str,
    composition_id: str, body_release_status: Mapping[str, Any],
) -> dict[str, Any]:
    people_root = Path(root).expanduser().resolve()
    assembly_receipt = read_assembly_receipt(people_root, person_id=person_id, person_revision=person_revision)
    target = composition_dir(people_root, person_id, person_revision, composition_id)
    authority_path = target / "authority.json"
    value = _read_json(authority_path, "digital-twin composition authority")
    hands_id = str(value.get("hands_release_id") or "")
    wardrobe_id = str(value.get("wardrobe_release_id") or "")
    try:
        hands = read_hands_release_authority(people_root, assembly_receipt=assembly_receipt, body_release_status=body_release_status, release_id=hands_id)
        wardrobe = read_wardrobe_release_authority(people_root, assembly_receipt=assembly_receipt, body_release_status=body_release_status, release_id=wardrobe_id)
    except (HandsFeetNailsReleaseAuthorityError, WardrobeReleaseAuthorityError) as exc:
        raise DigitalTwinCompositionError(f"M4 presentation authority failed during readback: {exc}") from exc
    value = validate_composition_structure(
        value, assembly_receipt=assembly_receipt, body_release_status=body_release_status,
        hands_authority=hands, wardrobe_authority=wardrobe,
    )
    assembly_path = assembly_receipt_path(people_root, person_id, person_revision)
    if _sha256_file(assembly_path) != value["assembly_receipt_sha256"] or _sha256_file(target / "assembly-receipt.json") != value["assembly_receipt_sha256"]:
        raise DigitalTwinCompositionError("M4 assembly receipt bytes changed after composition")
    audition_id = str(value["audition_id"])
    try:
        audition = verify_audition(people_root, person_id=person_id, audition_id=audition_id, assembly_fingerprint=str(value["assembly_fingerprint"]))
        current_audition_sha = audition_receipt_sha256(people_root, person_id=person_id, audition_id=audition_id)
    except PersonAuditionError as exc:
        raise DigitalTwinCompositionError(f"M4 audition/WAV changed after composition: {exc}") from exc
    if current_audition_sha != value["audition_receipt_sha256"] or _sha256_file(target / "audition-receipt.json") != value["audition_receipt_sha256"]:
        raise DigitalTwinCompositionError("M4 audition receipt bytes changed after composition")
    if str(audition["audio_sha256"]) != value["audition_audio_sha256"]:
        raise DigitalTwinCompositionError("M4 audition audio identity changed after composition")
    hands_path = hands_release_authority_dir(people_root, person_id, person_revision, hands_id) / "authority.json"
    wardrobe_path = wardrobe_release_authority_dir(people_root, person_id, person_revision, wardrobe_id) / "authority.json"
    if _sha256_file(hands_path) != value["hands_authority_sha256"] or _sha256_file(target / "hands-authority.json") != value["hands_authority_sha256"]:
        raise DigitalTwinCompositionError("M4 finalized M2 bytes changed after composition")
    if _sha256_file(wardrobe_path) != value["wardrobe_authority_sha256"] or _sha256_file(target / "wardrobe-authority.json") != value["wardrobe_authority_sha256"]:
        raise DigitalTwinCompositionError("M4 finalized M3 bytes changed after composition")
    package = _body_package(bodies_root, str(value["body_id"]))
    if _sha256_file(package) != value["body_package_sha256"]:
        raise DigitalTwinCompositionError("M4 canonical body package changed after composition")
    try:
        validated = validate_package(package)
    except MRBodyError as exc:
        raise DigitalTwinCompositionError(f"M4 body package became invalid: {exc}") from exc
    bodyprint_raw = _bodyprint_bytes(package)
    if _sha256_bytes(bodyprint_raw) != value["bodyprint_sha256"] or _sha256_file(target / "bodyprint.json") != value["bodyprint_sha256"]:
        raise DigitalTwinCompositionError("M4 BodyPrint bytes changed after composition")
    expected_probe = build_embodiment_probe(body_id=str(value["body_id"]), bodyprint=validated.bodyprint)
    if canonical_json_sha256(expected_probe) != value["embodiment_probe_sha256"] or expected_probe != value["embodiment_probe"]:
        raise DigitalTwinCompositionError("M4 embodiment realization no longer matches exact BodyPrint")
    frozen_probe = _read_json(target / "embodiment-probe.json", "frozen M4 embodiment probe")
    if frozen_probe != expected_probe:
        raise DigitalTwinCompositionError("frozen M4 embodiment probe changed after composition")
    frozen_status = _read_json(target / "body-release-status.json", "frozen M4 body release status")
    if canonical_json_sha256(frozen_status) != value["body_release_status_canonical_sha256"] or frozen_status != dict(body_release_status):
        raise DigitalTwinCompositionError("M4 frozen body-release status changed after composition")
    return value
