from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.personality_exemplars import (
    PersonalityExemplarError,
    build_exemplar_candidates,
    parse_transcript_text,
    write_create_only,
)


def test_parse_srt_strips_timestamps_indices_and_tags() -> None:
    text = """1
00:00:01,000 --> 00:00:03,000
<i>Ja ja</i>, det skal nok gå.

2
00:00:04,000 --> 00:00:06,000
Det er altså ikke verdens undergang.
"""

    assert parse_transcript_text(text) == [
        "Ja ja , det skal nok gå.",
        "Det er altså ikke verdens undergang.",
    ]


def test_parse_vtt_and_plain_text() -> None:
    vtt = """WEBVTT

00:00:01.000 --> 00:00:02.000
Det var da typisk.

00:00:03.000 --> 00:00:04.000
Nå, videre.
"""
    assert parse_transcript_text(vtt) == ["Det var da typisk.", "Nå, videre."]

    plain = "Første sætning. Anden sætning! Tredje?"
    assert parse_transcript_text(plain) == [
        "Første sætning.",
        "Anden sætning!",
        "Tredje?",
    ]


def test_build_candidates_is_path_free_review_required_and_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "one.srt"
    second = tmp_path / "two.txt"
    first.write_text(
        """1
00:00:01,000 --> 00:00:02,000
Ja ja, det går nok.

2
00:00:03,000 --> 00:00:04,000
Det var da typisk.
""",
        encoding="utf-8",
    )
    second.write_text("Nå, videre.\nDet går nok.\nVi finder ud af det.", encoding="utf-8")

    left = build_exemplar_candidates([first, second], suggested_limit=3)
    right = build_exemplar_candidates([first, second], suggested_limit=3)

    assert left == right
    assert left["operator_review_required"] is True
    assert left["personality_authority"] is False
    assert left["content_semantics"] == "style-only-not-biography-or-memory"
    assert left["source_count"] == 2
    assert len(left["source_sha256"]) == 2
    assert str(first) not in json.dumps(left)
    assert str(second) not in json.dumps(left)
    assert len(left["suggested_exemplars"]) == 3
    assert len(left["candidates"]) == 5


def test_create_only_report_refuses_reuse(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    value = {
        "format": "bodyrig-personality-exemplar-candidates",
        "version": 1,
    }

    write_create_only(target, value)
    with pytest.raises(PersonalityExemplarError, match="already exists"):
        write_create_only(target, value)


def test_empty_or_non_utf8_sources_fail_closed(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("\n\n", encoding="utf-8")
    with pytest.raises(PersonalityExemplarError, match="no usable utterances"):
        build_exemplar_candidates([empty])

    binary = tmp_path / "bad.txt"
    binary.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(PersonalityExemplarError, match="UTF-8"):
        build_exemplar_candidates([binary])


def test_suggested_limit_is_bounded(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Hello there.", encoding="utf-8")

    with pytest.raises(PersonalityExemplarError, match="suggested_limit"):
        build_exemplar_candidates([source], suggested_limit=13)
