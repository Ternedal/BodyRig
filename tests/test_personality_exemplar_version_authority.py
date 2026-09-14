from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bodyrig import personality_exemplar_approval as exemplar


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)


def _candidate(version: Any) -> dict[str, Any]:
    return {
        "format": exemplar.CANDIDATE_FORMAT,
        "version": version,
        "source_count": 1,
        "source_sha256": ["a" * 64],
        "candidate_count": 2,
        "candidates": ["Calm concise reply", "Warm playful reply"],
        "suggested_exemplars": ["Calm concise reply"],
        "operator_review_required": True,
        "speaker_identity_authority": False,
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def _approval(version: Any) -> dict[str, Any]:
    value = exemplar.build_approval(
        _candidate(1),
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )
    value["version"] = version
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_persisted_candidate_report_rejects_boolean_non_numeric_and_wrong_v1(tmp_path: Path, version: Any) -> None:
    path = tmp_path / "candidate.json"
    _write(path, _candidate(version))

    with pytest.raises(
        exemplar.PersonalityExemplarApprovalError,
        match="unsupported candidate report format/version",
    ):
        exemplar.load_candidate_report(path)


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_persisted_candidate_report_preserves_numeric_v1_and_review_only_semantics(tmp_path: Path, version: Any) -> None:
    path = tmp_path / "candidate.json"
    _write(path, _candidate(version))

    value = exemplar.load_candidate_report(path)

    assert value["version"] == exemplar.CANDIDATE_VERSION
    assert value["operator_review_required"] is True
    assert value["speaker_identity_authority"] is False
    assert value["personality_authority"] is False
    assert value["content_semantics"] == "style-only-not-biography-or-memory"


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_persisted_approval_rejects_boolean_non_numeric_and_wrong_v1(tmp_path: Path, version: Any) -> None:
    path = tmp_path / "approval.json"
    _write(path, _approval(version))

    with pytest.raises(
        exemplar.PersonalityExemplarApprovalError,
        match="unsupported approval format/version",
    ):
        exemplar.load_approval(path)


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_persisted_approval_preserves_numeric_v1_and_review_authority(tmp_path: Path, version: Any) -> None:
    path = tmp_path / "approval.json"
    _write(path, _approval(version))

    value = exemplar.load_approval(path)

    assert value["version"] == exemplar.APPROVAL_VERSION
    assert value["operator_review"] == {
        "speaker_identity_confirmed": True,
        "style_use_approved": True,
    }
    assert value["personality_authority"] is False
    assert value["content_semantics"] == "style-only-not-biography-or-memory"
