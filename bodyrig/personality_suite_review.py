from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .person_assembly import PersonAssemblyError, build_assembly
from .person_audition import PersonAuditionError, receipt_sha256, verify_audition
from .person_profiles import PersonProfileError, load_profile
from .personality_audition_suite import PersonalityAuditionSuiteError, build_audition_suite

FORMAT = "bodyrig-personality-suite-review"
VERSION = 1
REVIEW_ID_RE = re.compile(r"^suite-review-[0-9a-f]{32}$")
PERSON_ID_RE = re.compile(r"^person-[0-9a-f]{32}$")
AUDITION_ID_RE = re.compile(r"^audition-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PersonalitySuiteReviewError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _sha256_bytes(raw)


def suite_definition_sha256(default_language: str) -> str:
    try:
        suite = build_audition_suite(default_language)
    except PersonalityAuditionSuiteError as exc:
        raise PersonalitySuiteReviewError(str(exc)) from exc
    return _canonical_sha256(suite)


def _review_root(root: str | os.PathLike[str], person_id: str) -> Path:
    if not isinstance(person_id, str) or not PERSON_ID_RE.fullmatch(person_id):
        raise PersonalitySuiteReviewError("person_id is invalid")
    return Path(root).expanduser().resolve() / "personality-suite-reviews" / person_id


def review_path(root: str | os.PathLike[str], person_id: str, review_id: str) -> Path:
    if not isinstance(review_id, str) or not REVIEW_ID_RE.fullmatch(review_id):
        raise PersonalitySuiteReviewError("review_id is invalid")
    return _review_root(root, person_id) / f"{review_id}.json"


def _timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise PersonalitySuiteReviewError("created_utc is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PersonalitySuiteReviewError("created_utc is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PersonalitySuiteReviewError("created_utc must include timezone")
    return value


def _text(value: Any, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise PersonalitySuiteReviewError(f"{field} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or any(ord(ch) < 32 for ch in result):
        raise PersonalitySuiteReviewError(f"{field} is invalid")
    return result


def _sha(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise PersonalitySuiteReviewError(f"{field} must be lowercase SHA-256")
    return value


def _validate_probe_result(value: Any) -> dict[str, str]:
    fields = {
        "probe_id",
        "audition_id",
        "prompt_sha256",
        "audition_receipt_sha256",
        "reply_sha256",
        "audio_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PersonalitySuiteReviewError("probe result fields must match v1 exactly")
    audition_id = value.get("audition_id")
    if not isinstance(audition_id, str) or not AUDITION_ID_RE.fullmatch(audition_id):
        raise PersonalitySuiteReviewError("probe audition_id is invalid")
    return {
        "probe_id": _text(value.get("probe_id"), field="probe_id", maximum=80),
        "audition_id": audition_id,
        "prompt_sha256": _sha(value.get("prompt_sha256"), field="prompt_sha256"),
        "audition_receipt_sha256": _sha(value.get("audition_receipt_sha256"), field="audition_receipt_sha256"),
        "reply_sha256": _sha(value.get("reply_sha256"), field="reply_sha256"),
        "audio_sha256": _sha(value.get("audio_sha256"), field="audio_sha256"),
    }


def validate_suite_review(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    fields = {
        "format",
        "version",
        "review_id",
        "person_id",
        "created_utc",
        "body_revision",
        "voice_revision",
        "personality_revision",
        "assembly_fingerprint",
        "modelrig_version",
        "model",
        "voicerig_version",
        "default_language",
        "suite_definition_sha256",
        "probe_results",
        "human_review_required",
        "activation_authority",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PersonalitySuiteReviewError("suite review fields must match v1 exactly")
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise PersonalitySuiteReviewError("unsupported suite review format/version")
    review_id = value.get("review_id")
    person_id = value.get("person_id")
    if not isinstance(review_id, str) or not REVIEW_ID_RE.fullmatch(review_id):
        raise PersonalitySuiteReviewError("review_id is invalid")
    if not isinstance(person_id, str) or not PERSON_ID_RE.fullmatch(person_id):
        raise PersonalitySuiteReviewError("person_id is invalid")
    raw_results = value.get("probe_results")
    if not isinstance(raw_results, list) or len(raw_results) != 6:
        raise PersonalitySuiteReviewError("suite review must contain exactly six probe results")
    probe_results = [_validate_probe_result(item) for item in raw_results]
    probe_ids = [item["probe_id"] for item in probe_results]
    audition_ids = [item["audition_id"] for item in probe_results]
    if len(probe_ids) != len(set(probe_ids)):
        raise PersonalitySuiteReviewError("suite review probe ids must be unique")
    if len(audition_ids) != len(set(audition_ids)):
        raise PersonalitySuiteReviewError("suite review audition ids must be unique")
    if value.get("human_review_required") is not True:
        raise PersonalitySuiteReviewError("suite review must require human review")
    if value.get("activation_authority") is not False:
        raise PersonalitySuiteReviewError("suite review cannot be activation authority")
    return {
        "format": FORMAT,
        "version": VERSION,
        "review_id": review_id,
        "person_id": person_id,
        "created_utc": _timestamp(value.get("created_utc")),
        "body_revision": _text(value.get("body_revision"), field="body_revision", maximum=24),
        "voice_revision": _text(value.get("voice_revision"), field="voice_revision", maximum=24),
        "personality_revision": _text(value.get("personality_revision"), field="personality_revision", maximum=24),
        "assembly_fingerprint": _sha(value.get("assembly_fingerprint"), field="assembly_fingerprint"),
        "modelrig_version": _text(value.get("modelrig_version"), field="modelrig_version", maximum=160),
        "model": _text(value.get("model"), field="model", maximum=256),
        "voicerig_version": _text(value.get("voicerig_version"), field="voicerig_version", maximum=160),
        "default_language": _text(value.get("default_language"), field="default_language", maximum=16),
        "suite_definition_sha256": _sha(value.get("suite_definition_sha256"), field="suite_definition_sha256"),
        "probe_results": probe_results,
        "human_review_required": True,
        "activation_authority": False,
    }


def _assembly(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    voice_revision: str,
    personality_revision: str,
) -> dict[str, Any]:
    try:
        profile = load_profile(root, person_id)
        return build_assembly(
            profile,
            body_revision=body_revision,
            voice_revision=voice_revision,
            personality_revision=personality_revision,
        )
    except (PersonProfileError, PersonAssemblyError) as exc:
        raise PersonalitySuiteReviewError(str(exc)) from exc


def seal_suite_review(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    body_revision: str,
    voice_revision: str,
    personality_revision: str,
    assembly_fingerprint: str,
    model: str,
    default_language: str,
    audition_ids: Mapping[str, str],
) -> dict[str, Any]:
    assembly = _assembly(
        root,
        person_id,
        body_revision=body_revision,
        voice_revision=voice_revision,
        personality_revision=personality_revision,
    )
    expected_fingerprint = str(assembly["assembly_fingerprint"])
    if assembly_fingerprint != expected_fingerprint:
        raise PersonalitySuiteReviewError("suite assembly fingerprint does not match selected component revisions")
    personality_language = str(assembly["personality"]["default_language"])
    if default_language != personality_language:
        raise PersonalitySuiteReviewError("suite language does not match selected personality revision")
    try:
        suite = build_audition_suite(default_language)
    except PersonalityAuditionSuiteError as exc:
        raise PersonalitySuiteReviewError(str(exc)) from exc
    expected_ids = [probe["id"] for probe in suite["probes"]]
    if not isinstance(audition_ids, Mapping) or set(audition_ids) != set(expected_ids):
        raise PersonalitySuiteReviewError("audition_ids must contain the exact suite probe ids")
    ordered_auditions = [audition_ids[probe_id] for probe_id in expected_ids]
    if len(ordered_auditions) != len(set(ordered_auditions)):
        raise PersonalitySuiteReviewError("each suite probe must use a distinct audition")

    probe_results: list[dict[str, str]] = []
    modelrig_version: str | None = None
    voicerig_version: str | None = None
    for probe in suite["probes"]:
        probe_id = str(probe["id"])
        audition_id = audition_ids[probe_id]
        if not isinstance(audition_id, str) or not AUDITION_ID_RE.fullmatch(audition_id):
            raise PersonalitySuiteReviewError(f"audition id for {probe_id} is invalid")
        try:
            receipt = verify_audition(
                root,
                person_id=person_id,
                audition_id=audition_id,
                assembly_fingerprint=expected_fingerprint,
            )
        except PersonAuditionError as exc:
            raise PersonalitySuiteReviewError(f"{probe_id}: {exc}") from exc
        if receipt["model"] != model:
            raise PersonalitySuiteReviewError(f"{probe_id}: audition used a different ModelRig model")
        current_modelrig_version = str(receipt["modelrig_version"])
        current_voicerig_version = str(receipt["voicerig_version"])
        if modelrig_version is None:
            modelrig_version = current_modelrig_version
        elif current_modelrig_version != modelrig_version:
            raise PersonalitySuiteReviewError(f"{probe_id}: ModelRig runtime version changed during suite")
        if voicerig_version is None:
            voicerig_version = current_voicerig_version
        elif current_voicerig_version != voicerig_version:
            raise PersonalitySuiteReviewError(f"{probe_id}: VoiceRig runtime version changed during suite")
        expected_prompt_sha = _sha256_text(str(probe["prompt"]))
        if receipt["prompt_sha256"] != expected_prompt_sha:
            raise PersonalitySuiteReviewError(f"{probe_id}: audition prompt does not match the suite definition")
        try:
            receipt_sha = receipt_sha256(root, person_id=person_id, audition_id=audition_id)
        except PersonAuditionError as exc:
            raise PersonalitySuiteReviewError(f"{probe_id}: {exc}") from exc
        probe_results.append({
            "probe_id": probe_id,
            "audition_id": audition_id,
            "prompt_sha256": expected_prompt_sha,
            "audition_receipt_sha256": receipt_sha,
            "reply_sha256": str(receipt["reply_sha256"]),
            "audio_sha256": str(receipt["audio_sha256"]),
        })
    if modelrig_version is None or voicerig_version is None:
        raise PersonalitySuiteReviewError("suite execution runtime provenance is incomplete")

    review = validate_suite_review({
        "format": FORMAT,
        "version": VERSION,
        "review_id": f"suite-review-{uuid.uuid4().hex}",
        "person_id": person_id,
        "created_utc": _now(),
        "body_revision": body_revision,
        "voice_revision": voice_revision,
        "personality_revision": personality_revision,
        "assembly_fingerprint": expected_fingerprint,
        "modelrig_version": modelrig_version,
        "model": model,
        "voicerig_version": voicerig_version,
        "default_language": default_language,
        "suite_definition_sha256": _canonical_sha256(suite),
        "probe_results": probe_results,
        "human_review_required": True,
        "activation_authority": False,
    })
    path = review_path(root, person_id, review["review_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(review, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
    except FileExistsError as exc:
        raise PersonalitySuiteReviewError("suite review evidence already exists") from exc
    return review


def read_suite_review(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    review_id: str,
) -> dict[str, Any]:
    path = review_path(root, person_id, review_id)
    if not path.is_file():
        raise PersonalitySuiteReviewError("suite review not found")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonalitySuiteReviewError("suite review is invalid JSON") from exc
    review = validate_suite_review(value)
    if review["person_id"] != person_id or review["review_id"] != review_id:
        raise PersonalitySuiteReviewError("suite review identity mismatch")
    return review


def verify_suite_review(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    review_id: str,
) -> dict[str, Any]:
    review = read_suite_review(root, person_id=person_id, review_id=review_id)
    assembly = _assembly(
        root,
        person_id,
        body_revision=review["body_revision"],
        voice_revision=review["voice_revision"],
        personality_revision=review["personality_revision"],
    )
    if assembly["assembly_fingerprint"] != review["assembly_fingerprint"]:
        raise PersonalitySuiteReviewError("suite review assembly no longer matches selected component revisions")
    try:
        suite = build_audition_suite(review["default_language"])
    except PersonalityAuditionSuiteError as exc:
        raise PersonalitySuiteReviewError(str(exc)) from exc
    if _canonical_sha256(suite) != review["suite_definition_sha256"]:
        raise PersonalitySuiteReviewError("suite definition no longer matches review evidence")
    probes = {probe["id"]: probe for probe in suite["probes"]}
    if set(probes) != {item["probe_id"] for item in review["probe_results"]}:
        raise PersonalitySuiteReviewError("suite review probe set no longer matches suite definition")

    for item in review["probe_results"]:
        probe = probes[item["probe_id"]]
        expected_prompt_sha = _sha256_text(str(probe["prompt"]))
        if item["prompt_sha256"] != expected_prompt_sha:
            raise PersonalitySuiteReviewError(f"{item['probe_id']}: stored prompt hash is invalid")
        try:
            receipt = verify_audition(
                root,
                person_id=person_id,
                audition_id=item["audition_id"],
                assembly_fingerprint=review["assembly_fingerprint"],
            )
            current_receipt_sha = receipt_sha256(root, person_id=person_id, audition_id=item["audition_id"])
        except PersonAuditionError as exc:
            raise PersonalitySuiteReviewError(f"{item['probe_id']}: {exc}") from exc
        if receipt["modelrig_version"] != review["modelrig_version"]:
            raise PersonalitySuiteReviewError(f"{item['probe_id']}: ModelRig runtime version changed")
        if receipt["model"] != review["model"]:
            raise PersonalitySuiteReviewError(f"{item['probe_id']}: ModelRig model changed")
        if receipt["voicerig_version"] != review["voicerig_version"]:
            raise PersonalitySuiteReviewError(f"{item['probe_id']}: VoiceRig runtime version changed")
        if receipt["prompt_sha256"] != expected_prompt_sha:
            raise PersonalitySuiteReviewError(f"{item['probe_id']}: audition prompt no longer matches suite")
        if current_receipt_sha != item["audition_receipt_sha256"]:
            raise PersonalitySuiteReviewError(f"{item['probe_id']}: audition receipt bytes changed")
        if receipt["reply_sha256"] != item["reply_sha256"] or receipt["audio_sha256"] != item["audio_sha256"]:
            raise PersonalitySuiteReviewError(f"{item['probe_id']}: audition output hashes changed")
    return review


def suite_review_sha256(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    review_id: str,
) -> str:
    path = review_path(root, person_id, review_id)
    if not path.is_file():
        raise PersonalitySuiteReviewError("suite review not found")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise PersonalitySuiteReviewError("suite review could not be hashed") from exc
    return digest.hexdigest()
