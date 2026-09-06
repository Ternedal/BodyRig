from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.embodiment_authority as embodiment
from bodyrig.motor import _observed_embodiment


PERSON_ID = "person-0123456789abcdef0123456789abcdef"
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
BODY_ID = "body-0123456789abcdef0123456789abcdef"
VOICE_ID = "voice-0123456789abcdef0123456789abcdef"
AUDITION_ID = "audition-0123456789abcdef0123456789abcdef"
ASSEMBLY_SHA = "a" * 64
VOICE_SHA = "b" * 64
BODYRIG_REVISION = "1" * 40
UTTERANCE_ID = "utterance-001"
BODYPRINT = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "motion": {"energy": 0.7, "head_motion": 0.8, "gesture_amplitude": 0.6},
    "expression": {"gaze_strength": 0.75, "speech_motion": 0.8},
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _package(tmp_path: Path, bodyprint: dict = BODYPRINT) -> Path:
    package = tmp_path / "person.mrbody"
    raw = json.dumps(bodyprint, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bodyprint.json", raw)
    return package


def _audition(tmp_path: Path) -> Path:
    return _json(
        tmp_path / "audition.json",
        {
            "format": "bodyrig-person-audition",
            "version": 1,
            "audition_id": AUDITION_ID,
            "person_id": PERSON_ID,
            "created_utc": "2026-09-06T06:00:00Z",
            "assembly_fingerprint": ASSEMBLY_SHA,
            "modelrig_service": "modelrig-server",
            "modelrig_version": "modelrig-test-1",
            "model": "fixture-model",
            "voicerig_service": "voicerig",
            "voicerig_version": "voicerig-test-1",
            "prompt_sha256": "c" * 64,
            "reply_sha256": "d" * 64,
            "audio_sha256": "e" * 64,
            "complete": True,
        },
    )


def _assembly(tmp_path: Path, *, audition_sha: str, package_sha: str) -> tuple[Path, dict]:
    value = {
        "format": "bodyrig-person-assembly-receipt",
        "version": 2,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body": {"revision_id": BODY_REVISION, "body_id": BODY_ID, "package_sha256": package_sha},
        "voice": {"revision_id": "voice-r0001", "voice_id": VOICE_ID, "voice_package": "voice-a.mrvoice", "package_sha256": VOICE_SHA},
        "personality": {
            "revision_id": "personality-r0001",
            "instructions_sha256": "f" * 64,
            "default_language": "da-DK",
            "style_notes_sha256": "0" * 64,
        },
        "audition": {"audition_id": AUDITION_ID, "receipt_sha256": audition_sha},
    }
    return _json(tmp_path / "assembly.json", value), value


def _body_release(package_sha: str) -> dict:
    return {
        "format": "bodyrig-person-release-status",
        "version": 1,
        "person_id": PERSON_ID,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "package_sha256": package_sha,
        "production_ready": True,
        "production_activation": True,
    }


def _timing(tmp_path: Path) -> Path:
    return _json(
        tmp_path / "timing.json",
        {
            "format": "bodyrig-speech-timing-evidence",
            "version": 1,
            "utterance_id": UTTERANCE_ID,
            "source": "voicerig-runtime",
            "events": [
                {"state": "start", "elapsed_ms": 0, "viseme": None, "amplitude": 0.1},
                {"state": "update", "elapsed_ms": 500, "viseme": "A", "amplitude": 0.4},
                {"state": "stop", "elapsed_ms": 1000, "viseme": None, "amplitude": 0.0},
            ],
            "complete": True,
            "human_review_required": True,
            "production_activation": False,
        },
    )


def _motor(tmp_path: Path, *, bodyprint: dict = BODYPRINT, realized_amplitude: float = 0.52) -> Path:
    return _json(
        tmp_path / "motor.json",
        {
            "type": "bodyrig-motor-state",
            "version": 2,
            "body_id": BODY_ID,
            "utterance_id": UTTERANCE_ID,
            "motion": {"energy": 0.7, "head_motion": 0.8},
            "expression": {"emotion": "neutral", "intensity": 0.4},
            "speech": {"state": "update", "elapsed_ms": 500, "viseme": "A", "amplitude": realized_amplitude},
            "embodiment": {"source": "modelrig-bodyprint-v1", "observed": _observed_embodiment(bodyprint)},
        },
    )


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, bodyprint: dict = BODYPRINT) -> dict:
    package = _package(tmp_path, bodyprint)
    package_sha = _sha(package)
    audition_path = _audition(tmp_path)
    assembly_path, assembly_value = _assembly(tmp_path, audition_sha=_sha(audition_path), package_sha=package_sha)
    monkeypatch.setattr(
        embodiment,
        "validate_package",
        lambda _path: SimpleNamespace(manifest={"id": BODY_ID}, bodyprint=dict(bodyprint)),
    )
    return {
        "package": package,
        "package_sha": package_sha,
        "audition": audition_path,
        "assembly_path": assembly_path,
        "assembly": assembly_value,
        "release": _body_release(package_sha),
        "timing": _timing(tmp_path),
        "motor": _motor(tmp_path, bodyprint=bodyprint),
    }


def _write(tmp_path: Path, fixture: dict, **overrides) -> dict:
    args = {
        "assembly_receipt_path": fixture["assembly_path"],
        "body_release_status": fixture["release"],
        "package_path": fixture["package"],
        "motor_state_path": fixture["motor"],
        "speech_timing_path": fixture["timing"],
        "audition_receipt_path": fixture["audition"],
        "bodyrig_revision": BODYRIG_REVISION,
        "quality_note": "Motion, expression and speech timing were reviewed together on the same Person revision.",
        "motion_review_passed": True,
        "expression_review_passed": True,
        "voice_timing_review_passed": True,
    }
    args.update(overrides)
    return embodiment.write_authority(tmp_path / "library", **args)


def test_finalize_and_readback_bind_same_person_bodyprint_motor_timing_and_audition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    receipt = _write(tmp_path, fixture)

    assert receipt["state"] == "complete"
    assert receipt["operator_supplied"] is True
    assert receipt["motion_authority"] is True
    assert receipt["expression_authority"] is True
    assert receipt["voice_timing_authority"] is True
    assert receipt["production_activation"] is False
    assert receipt["observed_motion_fields"] == ["energy", "gesture_amplitude", "head_motion"]
    assert receipt["observed_expression_fields"] == ["gaze_strength", "speech_motion"]
    assert receipt["speech_event_count"] == 3

    reread = embodiment.read_authority(
        tmp_path / "library",
        assembly_receipt=fixture["assembly"],
        body_release_status=fixture["release"],
        authority_id=receipt["authority_id"],
    )
    assert reread == receipt


def test_motor_amplitude_must_equal_bodyrig_realization_of_raw_voicerig_amplitude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    fixture["motor"] = _motor(tmp_path, realized_amplitude=0.4)
    with pytest.raises(embodiment.EmbodimentAuthorityError, match="deterministic BodyRig realization"):
        _write(tmp_path, fixture)


def test_m4_refuses_to_infer_missing_observed_expression(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bodyprint = {"format": "modelrig-bodyprint", "version": 1, "motion": {"energy": 0.7}}
    fixture = _fixture(tmp_path, monkeypatch, bodyprint=bodyprint)
    with pytest.raises(embodiment.EmbodimentAuthorityError, match="no observed personal expression fields"):
        _write(tmp_path, fixture)


def test_all_operator_review_checks_must_be_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    with pytest.raises(embodiment.EmbodimentAuthorityError, match="must explicitly PASS"):
        _write(tmp_path, fixture, voice_timing_review_passed=False)


def test_frozen_motor_tamper_revokes_finalized_m4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    receipt = _write(tmp_path, fixture)
    target = embodiment.authority_dir(tmp_path / "library", PERSON_ID, PERSON_REVISION, receipt["authority_id"])
    (target / "motor-state.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(embodiment.EmbodimentAuthorityError, match="motor-state.json"):
        embodiment.read_authority(
            tmp_path / "library",
            assembly_receipt=fixture["assembly"],
            body_release_status=fixture["release"],
            authority_id=receipt["authority_id"],
        )


def test_frozen_timing_tamper_revokes_finalized_m4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    receipt = _write(tmp_path, fixture)
    target = embodiment.authority_dir(tmp_path / "library", PERSON_ID, PERSON_REVISION, receipt["authority_id"])
    timing_path = target / "speech-timing.json"
    value = json.loads(timing_path.read_text(encoding="utf-8"))
    value["events"][1]["elapsed_ms"] = 501
    _json(timing_path, value)

    with pytest.raises(embodiment.EmbodimentAuthorityError, match="speech-timing.json"):
        embodiment.read_authority(
            tmp_path / "library",
            assembly_receipt=fixture["assembly"],
            body_release_status=fixture["release"],
            authority_id=receipt["authority_id"],
        )


def test_finalized_m4_is_create_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _write(tmp_path, fixture)
    with pytest.raises(embodiment.EmbodimentAuthorityError, match="refusing to overwrite"):
        _write(tmp_path, fixture)
