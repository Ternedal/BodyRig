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
from .motor import _observed_embodiment
from .package import MRBodyError, validate_package

FORMAT = "bodyrig-person-embodiment-authority"
VERSION = 1
POLICY_REVISION = "bodyrig-person-embodiment-authority-v1"
AUTHORITY_ID_RE = re.compile(r"^embodiment-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
UTTERANCE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
MOTION_FIELDS = {
    "energy", "gesture_frequency", "gesture_amplitude", "head_motion", "turn_speed", "walk_cadence_spm"
}
EXPRESSION_FIELDS = {"blink_rate_per_min", "gaze_strength", "head_tilt", "speech_motion"}
TOP_FIELDS = {
    "format", "version", "policy_revision", "authority_id", "person_id", "person_revision",
    "assembly_fingerprint", "assembly_receipt_sha256", "body_revision", "body_id", "body_package_sha256",
    "bodyprint_sha256", "voice_revision", "voice_id", "voice_package_sha256", "personality_revision",
    "audition_id", "audition_receipt_sha256", "audition_audio_sha256", "modelrig_version", "voicerig_version",
    "bodyrig_revision", "utterance_id", "motor_state_sha256", "speech_timing_sha256", "motor_state_version",
    "speech_event_count", "observed_motion_fields", "observed_expression_fields", "articulation_signal_observed",
    "reviewed_utc", "quality_note", "state", "operator_supplied", "motion_authority", "expression_authority",
    "voice_timing_authority", "production_activation",
}
EVIDENCE_FILES = {
    "assembly-receipt.json": "assembly_receipt_sha256",
    "bodyprint.json": "bodyprint_sha256",
    "motor-state.json": "motor_state_sha256",
    "speech-timing.json": "speech_timing_sha256",
    "audition-receipt.json": "audition_receipt_sha256",
}


class EmbodimentAuthorityError(RuntimeError):
    pass


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise EmbodimentAuthorityError(f"{label} is not a canonical SHA-256")
    return text


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EmbodimentAuthorityError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise EmbodimentAuthorityError(f"{label} must be a JSON object")
    return value


def _quality_note(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) < 12 or len(text) > 2000:
        raise EmbodimentAuthorityError("embodiment quality note must be a meaningful 12-2000 character operator note")
    if re.fullmatch(r"<[^>]+>", text):
        raise EmbodimentAuthorityError("embodiment quality note cannot be a generated placeholder")
    return text


def _assembly_details(receipt: Mapping[str, Any]) -> dict[str, str]:
    try:
        base = _assembly_identity(receipt)
    except HandsFeetNailsAuthorityError as exc:
        raise EmbodimentAuthorityError(str(exc)) from exc
    voice = receipt.get("voice") if isinstance(receipt.get("voice"), Mapping) else {}
    personality = receipt.get("personality") if isinstance(receipt.get("personality"), Mapping) else {}
    audition = receipt.get("audition") if isinstance(receipt.get("audition"), Mapping) else {}
    voice_revision = str(voice.get("revision_id") or "").strip().lower()
    voice_id = str(voice.get("voice_id") or "").strip().lower()
    personality_revision = str(personality.get("revision_id") or "").strip().lower()
    audition_id = str(audition.get("audition_id") or "").strip().lower()
    if not voice_revision or not voice_id or not personality_revision or not audition_id:
        raise EmbodimentAuthorityError("Person assembly is missing VoiceRig/personality/audition identity")
    return {
        **base,
        "voice_revision": voice_revision,
        "voice_id": voice_id,
        "voice_package_sha256": _sha(voice.get("package_sha256"), "VoiceRig package SHA-256"),
        "personality_revision": personality_revision,
        "audition_id": audition_id,
        "audition_receipt_sha256": _sha(audition.get("receipt_sha256"), "audition receipt SHA-256"),
    }


def _body_release(status: Mapping[str, Any], assembly: Mapping[str, str]) -> dict[str, str]:
    try:
        return _release_identity(status, assembly)
    except HandsFeetNailsAuthorityError as exc:
        raise EmbodimentAuthorityError(str(exc)) from exc


def _package_bodyprint(package_path: str | os.PathLike[str], *, body_id: str, package_sha256: str) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    if not package.is_file() or package.suffix.lower() != ".mrbody":
        raise EmbodimentAuthorityError("embodiment authority requires the exact .mrbody package")
    if _sha256_file(package) != package_sha256:
        raise EmbodimentAuthorityError("embodiment package bytes do not match Person body release")
    try:
        validated = validate_package(package)
    except (OSError, MRBodyError) as exc:
        raise EmbodimentAuthorityError(f"embodiment body package is invalid: {exc}") from exc
    if str(validated.manifest.get("id") or "") != body_id:
        raise EmbodimentAuthorityError("embodiment package body id differs from Person assembly")
    try:
        with zipfile.ZipFile(package, "r") as archive:
            raw = archive.read("bodyprint.json")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise EmbodimentAuthorityError("embodiment package bodyprint bytes are unavailable") from exc
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EmbodimentAuthorityError("embodiment package bodyprint bytes are invalid JSON") from exc
    if parsed != validated.bodyprint:
        raise EmbodimentAuthorityError("validated BodyPrint no longer matches exact package bytes")
    observed = _observed_embodiment(validated.bodyprint)
    motion_fields = sorted(set(observed) & MOTION_FIELDS)
    expression_fields = sorted(set(observed) & EXPRESSION_FIELDS)
    if not motion_fields:
        raise EmbodimentAuthorityError("BodyPrint contains no observed personal motion fields; M4 cannot infer them")
    if not expression_fields:
        raise EmbodimentAuthorityError("BodyPrint contains no observed personal expression fields; M4 cannot infer them")
    return {
        "raw": raw,
        "sha256": _sha256_bytes(raw),
        "bodyprint": dict(validated.bodyprint),
        "observed": observed,
        "motion_fields": motion_fields,
        "expression_fields": expression_fields,
    }


def _audition(path: str | os.PathLike[str], *, assembly: Mapping[str, str]) -> dict[str, Any]:
    receipt_path = Path(path).expanduser().resolve()
    if not receipt_path.is_file():
        raise EmbodimentAuthorityError("Person audition receipt is missing")
    actual_sha = _sha256_file(receipt_path)
    if actual_sha != assembly["audition_receipt_sha256"]:
        raise EmbodimentAuthorityError("Person audition receipt bytes no longer match assembly authority")
    value = _read_json(receipt_path, "Person audition receipt")
    if value.get("format") != "bodyrig-person-audition" or value.get("version") != 1 or value.get("complete") is not True:
        raise EmbodimentAuthorityError("Person audition receipt is not canonical complete v1 evidence")
    if str(value.get("person_id") or "").lower() != assembly["person_id"] or str(value.get("audition_id") or "").lower() != assembly["audition_id"]:
        raise EmbodimentAuthorityError("Person audition receipt belongs to a different Person/audition")
    if _sha(value.get("assembly_fingerprint"), "audition assembly fingerprint") != assembly["assembly_fingerprint"]:
        raise EmbodimentAuthorityError("Person audition receipt belongs to a different assembly")
    if value.get("modelrig_service") != "modelrig-server" or value.get("voicerig_service") != "voicerig":
        raise EmbodimentAuthorityError("Person audition runtime services are not canonical")
    modelrig_version = str(value.get("modelrig_version") or "").strip()
    voicerig_version = str(value.get("voicerig_version") or "").strip()
    if not modelrig_version or not voicerig_version:
        raise EmbodimentAuthorityError("Person audition runtime provenance is incomplete")
    return {
        "path": receipt_path,
        "sha256": actual_sha,
        "audio_sha256": _sha(value.get("audio_sha256"), "audition audio SHA-256"),
        "modelrig_version": modelrig_version,
        "voicerig_version": voicerig_version,
    }


def _timing(path: str | os.PathLike[str]) -> dict[str, Any]:
    timing_path = Path(path).expanduser().resolve()
    if not timing_path.is_file():
        raise EmbodimentAuthorityError("speech timing evidence is missing")
    value = _read_json(timing_path, "speech timing evidence")
    expected = {"format", "version", "utterance_id", "source", "events", "complete", "human_review_required", "production_activation"}
    if set(value) != expected or value.get("format") != "bodyrig-speech-timing-evidence" or value.get("version") != 1:
        raise EmbodimentAuthorityError("speech timing evidence fields/format are not canonical v1")
    utterance_id = str(value.get("utterance_id") or "")
    if not UTTERANCE_RE.fullmatch(utterance_id):
        raise EmbodimentAuthorityError("speech timing utterance id is invalid")
    if value.get("source") != "voicerig-runtime" or value.get("complete") is not True or value.get("human_review_required") is not True or value.get("production_activation") is not False:
        raise EmbodimentAuthorityError("speech timing evidence crossed the review-only VoiceRig boundary")
    events = value.get("events")
    if not isinstance(events, list) or len(events) < 2 or len(events) > 10000:
        raise EmbodimentAuthorityError("speech timing evidence requires a bounded start/update/stop timeline")
    normalized: list[dict[str, Any]] = []
    previous = -1
    articulation = False
    for index, event in enumerate(events):
        if not isinstance(event, Mapping) or set(event) != {"state", "elapsed_ms", "viseme", "amplitude"}:
            raise EmbodimentAuthorityError("speech timing event fields are not canonical")
        state = event.get("state")
        elapsed = event.get("elapsed_ms")
        if state not in {"start", "update", "stop"} or isinstance(elapsed, bool) or not isinstance(elapsed, int) or not 0 <= elapsed <= 3_600_000:
            raise EmbodimentAuthorityError("speech timing event state/elapsed_ms is invalid")
        if elapsed < previous:
            raise EmbodimentAuthorityError("speech timing elapsed_ms must be monotonic")
        previous = elapsed
        viseme = event.get("viseme")
        amplitude = event.get("amplitude")
        if viseme is not None and (not isinstance(viseme, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", viseme)):
            raise EmbodimentAuthorityError("speech timing viseme is invalid")
        if amplitude is not None and (isinstance(amplitude, bool) or not isinstance(amplitude, (int, float)) or not 0.0 <= float(amplitude) <= 1.0):
            raise EmbodimentAuthorityError("speech timing amplitude is invalid")
        articulation = articulation or viseme is not None or amplitude is not None
        normalized.append({"state": state, "elapsed_ms": elapsed, "viseme": viseme, "amplitude": None if amplitude is None else float(amplitude)})
    if normalized[0]["state"] != "start" or normalized[0]["elapsed_ms"] != 0:
        raise EmbodimentAuthorityError("speech timing must begin with start at elapsed_ms=0")
    if normalized[-1]["state"] != "stop" or normalized[-1]["elapsed_ms"] <= 0:
        raise EmbodimentAuthorityError("speech timing must end with a positive stop event")
    if any(event["state"] != "update" for event in normalized[1:-1]):
        raise EmbodimentAuthorityError("speech timing intermediate events must be updates")
    if not articulation:
        raise EmbodimentAuthorityError("speech timing has no viseme/amplitude articulation signal")
    return {"path": timing_path, "value": value, "sha256": _sha256_file(timing_path), "utterance_id": utterance_id, "events": normalized, "articulation": True}


def _motor(path: str | os.PathLike[str], *, body_id: str, expected_observed: Mapping[str, float], timing: Mapping[str, Any]) -> dict[str, Any]:
    motor_path = Path(path).expanduser().resolve()
    if not motor_path.is_file():
        raise EmbodimentAuthorityError("Motor State v2 evidence is missing")
    value = _read_json(motor_path, "Motor State v2 evidence")
    allowed = {"type", "version", "body_id", "utterance_id", "motion", "expression", "gesture", "gaze", "posture", "duration_ms", "speech", "embodiment"}
    if set(value) - allowed or value.get("type") != "bodyrig-motor-state" or value.get("version") != 2:
        raise EmbodimentAuthorityError("embodiment authority requires canonical Motor State v2")
    if str(value.get("body_id") or "") != body_id or str(value.get("utterance_id") or "") != timing["utterance_id"]:
        raise EmbodimentAuthorityError("Motor State belongs to a different body/utterance")
    motion = value.get("motion")
    expression = value.get("expression")
    embodiment = value.get("embodiment")
    speech = value.get("speech")
    if not isinstance(motion, Mapping) or set(motion) != {"energy", "head_motion"}:
        raise EmbodimentAuthorityError("Motor State has no canonical motion realization")
    if not isinstance(expression, Mapping) or set(expression) != {"emotion", "intensity"}:
        raise EmbodimentAuthorityError("Motor State has no explicit expression realization")
    if not isinstance(embodiment, Mapping) or set(embodiment) != {"source", "observed"} or embodiment.get("source") != "modelrig-bodyprint-v1":
        raise EmbodimentAuthorityError("Motor State has no BodyPrint-observed embodiment receipt")
    observed = embodiment.get("observed")
    if not isinstance(observed, Mapping) or dict(observed) != dict(expected_observed):
        raise EmbodimentAuthorityError("Motor State observed embodiment differs from exact package BodyPrint")
    if not isinstance(speech, Mapping) or not {"state", "elapsed_ms"} <= set(speech) or set(speech) - {"state", "elapsed_ms", "viseme", "amplitude"}:
        raise EmbodimentAuthorityError("Motor State has no canonical speech realization")
    motor_event = {
        "state": speech.get("state"),
        "elapsed_ms": speech.get("elapsed_ms"),
        "viseme": speech.get("viseme"),
        "amplitude": None if speech.get("amplitude") is None else float(speech.get("amplitude")),
    }
    if motor_event not in timing["events"]:
        raise EmbodimentAuthorityError("Motor State speech realization is not present in exact VoiceRig timing evidence")
    return {"path": motor_path, "value": value, "sha256": _sha256_file(motor_path)}


def _authority_id(*, assembly_fingerprint: str, body_package_sha256: str, bodyprint_sha256: str, motor_state_sha256: str, speech_timing_sha256: str, audition_receipt_sha256: str, bodyrig_revision: str) -> str:
    payload = {
        "assembly_fingerprint": assembly_fingerprint,
        "body_package_sha256": body_package_sha256,
        "bodyprint_sha256": bodyprint_sha256,
        "motor_state_sha256": motor_state_sha256,
        "speech_timing_sha256": speech_timing_sha256,
        "audition_receipt_sha256": audition_receipt_sha256,
        "bodyrig_revision": bodyrig_revision,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "embodiment-" + hashlib.sha256(raw).hexdigest()[:32]


def authority_dir(root: str | os.PathLike[str], person_id: str, person_revision: str, authority_id: str) -> Path:
    identity = str(authority_id or "").strip().lower()
    if not AUTHORITY_ID_RE.fullmatch(identity):
        raise EmbodimentAuthorityError("embodiment authority id is invalid")
    return Path(root).expanduser().resolve() / "embodiment-authorities" / str(person_id) / str(person_revision) / identity


def validate_authority_structure(value: Mapping[str, Any], *, assembly_receipt: Mapping[str, Any], body_release_status: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise EmbodimentAuthorityError("finalized embodiment authority fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise EmbodimentAuthorityError("finalized embodiment authority format/version/policy mismatch")
    assembly = _assembly_details(assembly_receipt)
    release = _body_release(body_release_status, assembly)
    exact = {
        "person_id": assembly["person_id"], "person_revision": assembly["person_revision"],
        "assembly_fingerprint": assembly["assembly_fingerprint"], "body_revision": assembly["body_revision"],
        "body_id": assembly["body_id"], "body_package_sha256": release["package_sha256"],
        "voice_revision": assembly["voice_revision"], "voice_id": assembly["voice_id"],
        "voice_package_sha256": assembly["voice_package_sha256"], "personality_revision": assembly["personality_revision"],
        "audition_id": assembly["audition_id"], "audition_receipt_sha256": assembly["audition_receipt_sha256"],
    }
    for field, expected in exact.items():
        if str(value.get(field) or "").lower() != str(expected).lower():
            raise EmbodimentAuthorityError(f"finalized embodiment authority no longer matches exact {field}")
    authority_id = str(value.get("authority_id") or "").strip().lower()
    revision = str(value.get("bodyrig_revision") or "").strip().lower()
    utterance_id = str(value.get("utterance_id") or "")
    if not AUTHORITY_ID_RE.fullmatch(authority_id) or not SHA40_RE.fullmatch(revision) or not UTTERANCE_RE.fullmatch(utterance_id):
        raise EmbodimentAuthorityError("finalized embodiment authority id/revision/utterance is invalid")
    for field in ("assembly_receipt_sha256", "body_package_sha256", "bodyprint_sha256", "voice_package_sha256", "audition_receipt_sha256", "audition_audio_sha256", "motor_state_sha256", "speech_timing_sha256"):
        _sha(value.get(field), field)
    motion_fields = value.get("observed_motion_fields")
    expression_fields = value.get("observed_expression_fields")
    if not isinstance(motion_fields, list) or not motion_fields or motion_fields != sorted(set(motion_fields)) or not set(motion_fields) <= MOTION_FIELDS:
        raise EmbodimentAuthorityError("finalized embodiment observed motion fields are invalid")
    if not isinstance(expression_fields, list) or not expression_fields or expression_fields != sorted(set(expression_fields)) or not set(expression_fields) <= EXPRESSION_FIELDS:
        raise EmbodimentAuthorityError("finalized embodiment observed expression fields are invalid")
    count = value.get("speech_event_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 2 or count > 10000:
        raise EmbodimentAuthorityError("finalized embodiment speech event count is invalid")
    if value.get("motor_state_version") != 2 or value.get("articulation_signal_observed") is not True:
        raise EmbodimentAuthorityError("finalized embodiment has no canonical Motor State/timing evidence")
    for field in ("modelrig_version", "voicerig_version"):
        if not isinstance(value.get(field), str) or not str(value[field]).strip():
            raise EmbodimentAuthorityError(f"finalized embodiment {field} is missing")
    _quality_note(value.get("quality_note"))
    if value.get("state") != "complete" or value.get("operator_supplied") is not True or value.get("motion_authority") is not True or value.get("expression_authority") is not True or value.get("voice_timing_authority") is not True or value.get("production_activation") is not False:
        raise EmbodimentAuthorityError("finalized embodiment authority is not complete non-activating operator authority")
    expected_id = _authority_id(
        assembly_fingerprint=assembly["assembly_fingerprint"],
        body_package_sha256=release["package_sha256"],
        bodyprint_sha256=_sha(value["bodyprint_sha256"], "bodyprint SHA-256"),
        motor_state_sha256=_sha(value["motor_state_sha256"], "Motor State SHA-256"),
        speech_timing_sha256=_sha(value["speech_timing_sha256"], "speech timing SHA-256"),
        audition_receipt_sha256=assembly["audition_receipt_sha256"],
        bodyrig_revision=revision,
    )
    if authority_id != expected_id:
        raise EmbodimentAuthorityError("finalized embodiment authority id no longer matches exact evidence identity")
    return dict(value)


def write_authority(
    root: str | os.PathLike[str],
    *,
    assembly_receipt_path: str | os.PathLike[str],
    body_release_status: Mapping[str, Any],
    package_path: str | os.PathLike[str],
    motor_state_path: str | os.PathLike[str],
    speech_timing_path: str | os.PathLike[str],
    audition_receipt_path: str | os.PathLike[str],
    bodyrig_revision: str,
    quality_note: str,
    motion_review_passed: bool,
    expression_review_passed: bool,
    voice_timing_review_passed: bool,
) -> dict[str, Any]:
    if motion_review_passed is not True or expression_review_passed is not True or voice_timing_review_passed is not True:
        raise EmbodimentAuthorityError("all M4 operator review checks must explicitly PASS")
    revision = str(bodyrig_revision or "").strip().lower()
    if not SHA40_RE.fullmatch(revision):
        raise EmbodimentAuthorityError("BodyRig revision is invalid")
    note = _quality_note(quality_note)
    assembly_path = Path(assembly_receipt_path).expanduser().resolve()
    if not assembly_path.is_file():
        raise EmbodimentAuthorityError("Person assembly receipt is missing")
    assembly_receipt = _read_json(assembly_path, "Person assembly receipt")
    assembly = _assembly_details(assembly_receipt)
    release = _body_release(body_release_status, assembly)
    package = _package_bodyprint(package_path, body_id=assembly["body_id"], package_sha256=release["package_sha256"])
    audition = _audition(audition_receipt_path, assembly=assembly)
    timing = _timing(speech_timing_path)
    motor = _motor(motor_state_path, body_id=assembly["body_id"], expected_observed=package["observed"], timing=timing)
    assembly_sha = _sha256_file(assembly_path)
    authority_id = _authority_id(
        assembly_fingerprint=assembly["assembly_fingerprint"],
        body_package_sha256=release["package_sha256"],
        bodyprint_sha256=package["sha256"],
        motor_state_sha256=motor["sha256"],
        speech_timing_sha256=timing["sha256"],
        audition_receipt_sha256=audition["sha256"],
        bodyrig_revision=revision,
    )
    target = authority_dir(root, assembly["person_id"], assembly["person_revision"], authority_id)
    if target.exists():
        raise EmbodimentAuthorityError("refusing to overwrite existing finalized embodiment authority")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    stage.mkdir(parents=False, exist_ok=False)
    try:
        shutil.copyfile(assembly_path, stage / "assembly-receipt.json")
        (stage / "bodyprint.json").write_bytes(package["raw"])
        shutil.copyfile(motor["path"], stage / "motor-state.json")
        shutil.copyfile(timing["path"], stage / "speech-timing.json")
        shutil.copyfile(audition["path"], stage / "audition-receipt.json")
        payload = {
            "format": FORMAT,
            "version": VERSION,
            "policy_revision": POLICY_REVISION,
            "authority_id": authority_id,
            "person_id": assembly["person_id"],
            "person_revision": assembly["person_revision"],
            "assembly_fingerprint": assembly["assembly_fingerprint"],
            "assembly_receipt_sha256": assembly_sha,
            "body_revision": assembly["body_revision"],
            "body_id": assembly["body_id"],
            "body_package_sha256": release["package_sha256"],
            "bodyprint_sha256": package["sha256"],
            "voice_revision": assembly["voice_revision"],
            "voice_id": assembly["voice_id"],
            "voice_package_sha256": assembly["voice_package_sha256"],
            "personality_revision": assembly["personality_revision"],
            "audition_id": assembly["audition_id"],
            "audition_receipt_sha256": audition["sha256"],
            "audition_audio_sha256": audition["audio_sha256"],
            "modelrig_version": audition["modelrig_version"],
            "voicerig_version": audition["voicerig_version"],
            "bodyrig_revision": revision,
            "utterance_id": timing["utterance_id"],
            "motor_state_sha256": motor["sha256"],
            "speech_timing_sha256": timing["sha256"],
            "motor_state_version": 2,
            "speech_event_count": len(timing["events"]),
            "observed_motion_fields": package["motion_fields"],
            "observed_expression_fields": package["expression_fields"],
            "articulation_signal_observed": True,
            "reviewed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "quality_note": note,
            "state": "complete",
            "operator_supplied": True,
            "motion_authority": True,
            "expression_authority": True,
            "voice_timing_authority": True,
            "production_activation": False,
        }
        validate_authority_structure(payload, assembly_receipt=assembly_receipt, body_release_status=body_release_status)
        (stage / "authority.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        os.replace(stage, target)
        return read_authority(root, assembly_receipt=assembly_receipt, body_release_status=body_release_status, authority_id=authority_id)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def read_authority(root: str | os.PathLike[str], *, assembly_receipt: Mapping[str, Any], body_release_status: Mapping[str, Any], authority_id: str) -> dict[str, Any]:
    assembly = _assembly_details(assembly_receipt)
    target = authority_dir(root, assembly["person_id"], assembly["person_revision"], authority_id)
    authority_path = target / "authority.json"
    if not authority_path.is_file():
        raise EmbodimentAuthorityError("finalized embodiment authority is missing")
    value = validate_authority_structure(_read_json(authority_path, "finalized embodiment authority"), assembly_receipt=assembly_receipt, body_release_status=body_release_status)
    for filename, field in EVIDENCE_FILES.items():
        path = target / filename
        if not path.is_file() or _sha256_file(path) != value[field]:
            raise EmbodimentAuthorityError(f"frozen embodiment evidence changed after finalization: {filename}")
    frozen_assembly = _read_json(target / "assembly-receipt.json", "frozen Person assembly receipt")
    if frozen_assembly != dict(assembly_receipt):
        raise EmbodimentAuthorityError("frozen Person assembly receipt no longer matches current Person Revision")
    bodyprint = _read_json(target / "bodyprint.json", "frozen package BodyPrint")
    observed = _observed_embodiment(bodyprint)
    motion_fields = sorted(set(observed) & MOTION_FIELDS)
    expression_fields = sorted(set(observed) & EXPRESSION_FIELDS)
    if motion_fields != value["observed_motion_fields"] or expression_fields != value["observed_expression_fields"]:
        raise EmbodimentAuthorityError("frozen BodyPrint observed embodiment no longer matches finalized authority")
    timing = _timing(target / "speech-timing.json")
    if timing["sha256"] != value["speech_timing_sha256"] or timing["utterance_id"] != value["utterance_id"] or len(timing["events"]) != value["speech_event_count"]:
        raise EmbodimentAuthorityError("frozen speech timing no longer matches finalized authority")
    motor = _motor(target / "motor-state.json", body_id=assembly["body_id"], expected_observed=observed, timing=timing)
    if motor["sha256"] != value["motor_state_sha256"]:
        raise EmbodimentAuthorityError("frozen Motor State no longer matches finalized authority")
    audition = _audition(target / "audition-receipt.json", assembly=assembly)
    if audition["audio_sha256"] != value["audition_audio_sha256"] or audition["modelrig_version"] != value["modelrig_version"] or audition["voicerig_version"] != value["voicerig_version"]:
        raise EmbodimentAuthorityError("frozen audition runtime/audio lineage no longer matches finalized authority")
    return value
