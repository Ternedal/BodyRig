from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from bodyrig.guided_app import (
    GuidedPersonalityRequest,
    StashTranscriptApprovalRequest,
    _authoring_kwargs,
    personality_stash_transcript_approval,
    personality_stash_transcript_candidates,
)


def _communication() -> dict[str, float]:
    return {
        "directness": 0.5,
        "warmth": 0.5,
        "playfulness": 0.5,
        "formality": 0.5,
        "verbosity": 0.5,
        "initiative": 0.5,
    }


def _report() -> dict:
    return {
        "format": "bodyrig-personality-exemplar-candidates",
        "version": 1,
        "source_count": 1,
        "source_sha256": ["a" * 64],
        "candidate_count": 2,
        "candidates": [
            "Well, that is actually pretty funny.",
            "Yeah, I mean, I would probably do that.",
        ],
        "suggested_exemplars": [
            "Well, that is actually pretty funny.",
        ],
        "operator_review_required": True,
        "speaker_identity_authority": False,
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def _preview(report: dict | None = None) -> dict:
    return {
        "ok": True,
        "person_id": "person-" + "3" * 32,
        "body_revision": "body-r0001",
        "performer": {"id": "42", "name": "Target"},
        "source_manifest_sha256": "b" * 64,
        "source_media_count": 1,
        "transcript_count": 1 if report is not None else 0,
        "transcripts": (
            [{"scene_id": "scene-7", "name": "scene.en.srt", "sha256": "a" * 64}]
            if report is not None
            else []
        ),
        "candidate_report": report,
        "candidate_count": report["candidate_count"] if report else 0,
        "suggested_exemplars": list(report["suggested_exemplars"]) if report else [],
        "operator_review_required": True,
        "speaker_identity_authority": False,
        "style_use_authority": False,
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def test_stash_transcript_candidate_api_is_preview_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report()
    monkeypatch.setattr(
        "bodyrig.guided_app.preview_source_personality_exemplars",
        lambda root, person_id, *, body_revision: _preview(report),
    )

    result = personality_stash_transcript_candidates(
        "person-" + "3" * 32,
        body_revision="body-r0001",
    )

    assert result["candidate_report"] == report
    assert result["speaker_identity_authority"] is False
    assert result["style_use_authority"] is False
    assert result["personality_authority"] is False
    assert "approval" not in result


def test_stash_transcript_approval_revalidates_exact_source_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report()
    monkeypatch.setattr(
        "bodyrig.guided_app.preview_source_personality_exemplars",
        lambda root, person_id, *, body_revision: _preview(report),
    )
    request = StashTranscriptApprovalRequest(
        candidate_report=report,
        selected_candidate_indexes=[0, 1],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )

    result = personality_stash_transcript_approval(
        "person-" + "3" * 32,
        request,
        body_revision="body-r0001",
    )

    assert result["approval"]["approved_exemplars"] == report["candidates"]
    assert result["approval"]["operator_review"] == {
        "speaker_identity_confirmed": True,
        "style_use_approved": True,
    }
    assert result["source_manifest_sha256"] == "b" * 64
    assert result["personality_authority"] is False


def test_stash_transcript_approval_rejects_modified_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _report()
    provided = _report()
    provided["candidates"][0] = "Browser-modified utterance."
    provided["suggested_exemplars"] = [provided["candidates"][1]]
    monkeypatch.setattr(
        "bodyrig.guided_app.preview_source_personality_exemplars",
        lambda root, person_id, *, body_revision: _preview(current),
    )
    request = StashTranscriptApprovalRequest(
        candidate_report=provided,
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )

    with pytest.raises(HTTPException) as exc:
        personality_stash_transcript_approval(
            "person-" + "3" * 32,
            request,
            body_revision="body-r0001",
        )

    assert exc.value.status_code == 409
    assert "candidate report changed" in str(exc.value.detail)


def test_stash_transcript_approval_requires_speaker_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report()
    monkeypatch.setattr(
        "bodyrig.guided_app.preview_source_personality_exemplars",
        lambda root, person_id, *, body_revision: _preview(report),
    )
    request = StashTranscriptApprovalRequest(
        candidate_report=report,
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=False,
        style_use_approved=True,
    )

    with pytest.raises(HTTPException) as exc:
        personality_stash_transcript_approval(
            "person-" + "3" * 32,
            request,
            body_revision="body-r0001",
        )

    assert exc.value.status_code == 409
    assert "speaker identity" in str(exc.value.detail)


def test_guided_style_source_schema_is_exact_and_preserved() -> None:
    request = GuidedPersonalityRequest(
        communication=_communication(),
        style_source={
            "kind": "stash-source-transcript",
            "body_revision": "body-r0001",
            "source_manifest_sha256": "b" * 64,
        },
        body_revision="body-r0001",
    )

    kwargs = _authoring_kwargs(request)
    assert kwargs["style_source"] == {
        "kind": "stash-source-transcript",
        "body_revision": "body-r0001",
        "source_manifest_sha256": "b" * 64,
    }

    with pytest.raises(ValidationError):
        GuidedPersonalityRequest(
            communication=_communication(),
            style_source={
                "kind": "stash-source-transcript",
                "body_revision": "body-r0001",
                "source_manifest_sha256": "not-a-sha",
            },
        )


def test_guided_ui_requires_review_before_source_transcript_style_use() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")

    for token in (
        "Reviewed Stash transcript style",
        'id="stashTranscriptLoad"',
        'id="stashTranscriptCandidates"',
        'id="stashTranscriptSpeakerConfirm"',
        'id="stashTranscriptStyleConfirm"',
        'id="stashTranscriptApprove"',
        "/personality/stash-transcript-candidates",
        "/personality/stash-transcript-approval",
        "speaker_identity_confirmed",
        "style_use_approved",
        "style_source: state.styleSource",
        'kind:"stash-source-transcript"',
        "source_manifest_sha256:result.source_manifest_sha256",
        "transcriptSlotLimit",
        "samlet ${total}/12",
        "transcriptBound=hasSourceBoundTranscriptStyle()",
        "onBodyRevisionChange",
    ):
        assert token in html

    approval = html[
        html.index("async function approveStashTranscriptCandidates"):
        html.index("function renderEvidenceStatus")
    ]
    assert "state.styleReport=result.candidate_report" in approval
    assert "state.styleApproval=result.approval" in approval
    assert 'state.styleEvidenceOrigin="stash"' in approval
    assert '$("stackBaseline").checked=false' in approval
