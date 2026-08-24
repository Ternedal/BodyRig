from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def _wav() -> bytes:
    return b"RIFF" + b"\x00" * 64


def test_audition_is_create_only_and_hash_binds_reply_and_audio(tmp_path: Path) -> None:
    receipt = write_audition(
        tmp_path,
        person_id=PERSON_ID,
        assembly_fingerprint=ASSEMBLY,
        model="qwen3:8b",
        prompt="Præsenter dig selv kort.",
        reply="Jeg er Anna. Kort nok.",
        audio=_wav(),
    )
    audition_id = receipt["audition_id"]
    assert receipt["format"] == "bodyrig-person-audition"
    assert receipt["version"] == 1
    assert receipt["complete"] is True
    assert receipt["assembly_fingerprint"] == ASSEMBLY
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


def test_audition_rejects_audio_tamper(tmp_path: Path) -> None:
    receipt = write_audition(
        tmp_path,
        person_id=PERSON_ID,
        assembly_fingerprint=ASSEMBLY,
        model="qwen3:8b",
        prompt="Hej",
        reply="Hej tilbage",
        audio=_wav(),
    )
    audio_path(tmp_path, PERSON_ID, receipt["audition_id"]).write_bytes(_wav() + b"tamper")
    with pytest.raises(PersonAuditionError, match="audio"):
        verify_audition(
            tmp_path,
            person_id=PERSON_ID,
            audition_id=receipt["audition_id"],
            assembly_fingerprint=ASSEMBLY,
        )


def test_audition_rejects_other_assembly(tmp_path: Path) -> None:
    receipt = write_audition(
        tmp_path,
        person_id=PERSON_ID,
        assembly_fingerprint=ASSEMBLY,
        model="qwen3:8b",
        prompt="Hej",
        reply="Hej tilbage",
        audio=_wav(),
    )
    with pytest.raises(PersonAuditionError, match="different person assembly"):
        verify_audition(
            tmp_path,
            person_id=PERSON_ID,
            audition_id=receipt["audition_id"],
            assembly_fingerprint="b" * 64,
        )


def test_receipt_is_strict_and_contains_no_prompt_reply_or_token(tmp_path: Path) -> None:
    receipt = write_audition(
        tmp_path,
        person_id=PERSON_ID,
        assembly_fingerprint=ASSEMBLY,
        model="qwen3:8b",
        prompt="secret prompt text",
        reply="secret reply text",
        audio=_wav(),
    )
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
