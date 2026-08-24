from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.execution_provenance import clear_runtime_provenance, record_runtime
from bodyrig.person_audition import (
    PersonAuditionError,
    audio_path,
    receipt_path,
    receipt_sha256,
    verify_audition,
    write_audition,
)

PERSON_ID = "person-0123456789abcdef0123456789abcdef"
ASSEMBLY = "a" * 64
RUNTIME = {
    "modelrig_service": "modelrig-server",
    "modelrig_version": "modelrig-test-1",
    "voicerig_service": "voicerig",
    "voicerig_version": "voicerig-test-1",
}


def _wav() -> bytes:
    return b"RIFF" + b"\x00" * 64


def _write(tmp_path: Path, **overrides):
    values = {
        "person_id": PERSON_ID,
        "assembly_fingerprint": ASSEMBLY,
        "model": "qwen3:8b",
        "prompt": "Præsenter dig selv kort.",
        "reply": "Jeg er Anna. Kort nok.",
        "audio": _wav(),
        **RUNTIME,
    }
    values.update(overrides)
    return write_audition(tmp_path, **values)


def test_audition_is_create_only_and_hash_binds_reply_audio_and_execution_runtime(tmp_path: Path) -> None:
    receipt = _write(tmp_path)
    audition_id = receipt["audition_id"]
    assert receipt["format"] == "bodyrig-person-audition"
    assert receipt["version"] == 1
    assert receipt["complete"] is True
    assert receipt["assembly_fingerprint"] == ASSEMBLY
    assert receipt["modelrig_service"] == "modelrig-server"
    assert receipt["modelrig_version"] == "modelrig-test-1"
    assert receipt["voicerig_service"] == "voicerig"
    assert receipt["voicerig_version"] == "voicerig-test-1"
    assert len(receipt["prompt_sha256"]) == 64
    assert len(receipt["reply_sha256"]) == 64
    assert len(receipt["audio_sha256"]) == 64
    assert receipt_path(tmp_path, PERSON_ID, audition_id).is_file()
    assert audio_path(tmp_path, PERSON_ID, audition_id).read_bytes() == _wav()
    assert len(receipt_sha256(tmp_path, person_id=PERSON_ID, audition_id=audition_id)) == 64
    assert verify_audition(
        tmp_path,
        person_id=PERSON_ID,
        audition_id=audition_id,
        assembly_fingerprint=ASSEMBLY,
    ) == receipt


def test_audition_can_consume_request_local_runtime_provenance(tmp_path: Path) -> None:
    clear_runtime_provenance()
    record_runtime("modelrig-server", "modelrig-live-2")
    record_runtime("voicerig", "voicerig-live-3")
    receipt = write_audition(
        tmp_path,
        person_id=PERSON_ID,
        assembly_fingerprint=ASSEMBLY,
        model="qwen3:8b",
        prompt="Hej",
        reply="Hej tilbage",
        audio=_wav(),
    )
    assert receipt["modelrig_version"] == "modelrig-live-2"
    assert receipt["voicerig_version"] == "voicerig-live-3"


def test_audition_fails_closed_without_complete_execution_runtime_provenance(tmp_path: Path) -> None:
    clear_runtime_provenance()
    record_runtime("modelrig-server", "modelrig-live-2")
    with pytest.raises(PersonAuditionError, match="runtime provenance is incomplete"):
        write_audition(
            tmp_path,
            person_id=PERSON_ID,
            assembly_fingerprint=ASSEMBLY,
            model="qwen3:8b",
            prompt="Hej",
            reply="Hej tilbage",
            audio=_wav(),
        )
    clear_runtime_provenance()


def test_audition_rejects_audio_tamper(tmp_path: Path) -> None:
    receipt = _write(tmp_path, prompt="Hej", reply="Hej tilbage")
    audio_path(tmp_path, PERSON_ID, receipt["audition_id"]).write_bytes(_wav() + b"tamper")
    with pytest.raises(PersonAuditionError, match="audio"):
        verify_audition(
            tmp_path,
            person_id=PERSON_ID,
            audition_id=receipt["audition_id"],
            assembly_fingerprint=ASSEMBLY,
        )


def test_audition_rejects_other_assembly(tmp_path: Path) -> None:
    receipt = _write(tmp_path, prompt="Hej", reply="Hej tilbage")
    with pytest.raises(PersonAuditionError, match="different person assembly"):
        verify_audition(
            tmp_path,
            person_id=PERSON_ID,
            audition_id=receipt["audition_id"],
            assembly_fingerprint="b" * 64,
        )


def test_receipt_is_strict_and_contains_no_prompt_reply_or_token(tmp_path: Path) -> None:
    receipt = _write(tmp_path, prompt="secret prompt text", reply="secret reply text")
    path = receipt_path(tmp_path, PERSON_ID, receipt["audition_id"])
    raw = path.read_text(encoding="utf-8")
    assert "secret prompt text" not in raw
    assert "secret reply text" not in raw
    assert "token" not in raw.lower()

    value = json.loads(raw)
    value["unknown"] = True
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(PersonAuditionError, match="fields"):
        verify_audition(
            tmp_path,
            person_id=PERSON_ID,
            audition_id=receipt["audition_id"],
            assembly_fingerprint=ASSEMBLY,
        )
