from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from bodyrig.guided_app import (
    GuidedPersonalityRequest,
    StashTranscriptApprovalRequest,
    _authoring_kwargs,
    personality_revision_traits,
    personality_stash_context,
    personality_stash_transcript_approval,
    personality_stash_transcript_candidates,
    personality_trait_catalog,
)
from bodyrig.person_profiles import create_profile
from bodyrig.personality_authoring import save_guided_personality
from bodyrig.personality_traits import (
    INNER_KEYS,
    OUTER_KEYS,
    build_trait_profile,
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


def test_guided_trait_catalog_exposes_exact_120_axes() -> None:
    catalog = personality_trait_catalog()

    assert catalog["trait_count"] == 120
    assert len(catalog["inner_ring"]) == 60
    assert len(catalog["outer_ring"]) == 60
    assert {item["id"] for item in catalog["inner_ring"]} == set(INNER_KEYS)
    assert {item["id"] for item in catalog["outer_ring"]} == set(OUTER_KEYS)
    assert catalog["grounding"] == "operator-authored"
    assert catalog["scale"]["neutral"] == 0.5


def test_guided_request_canonicalizes_partial_trait_input() -> None:
    request = GuidedPersonalityRequest(
        communication=_communication(),
        trait_profile={
            "inner_ring": {"curiosity": 0.9},
            "outer_ring": {"empathy": 0.85},
        },
    )

    kwargs = _authoring_kwargs(request)
    profile = kwargs["trait_profile"]

    assert set(profile["inner_ring"]) == set(INNER_KEYS)
    assert set(profile["outer_ring"]) == set(OUTER_KEYS)
    assert profile["inner_ring"]["curiosity"] == pytest.approx(0.9)
    assert profile["outer_ring"]["empathy"] == pytest.approx(0.85)
    assert profile["inner_ring"]["candor"] == pytest.approx(0.5)
    assert profile["outer_ring"]["joy"] == pytest.approx(0.5)
    assert profile["grounding"] == "operator-authored"


def test_guided_request_rejects_out_of_range_trait_value() -> None:
    with pytest.raises(ValidationError):
        GuidedPersonalityRequest(
            communication=_communication(),
            trait_profile={
                "inner_ring": {"curiosity": 1.1},
                "outer_ring": {},
            },
        )


def test_guided_personality_ui_is_catalog_driven_and_trait_complete() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(
        encoding="utf-8"
    )
    person = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    person_js = Path("bodyrig/ui/person_app.js").read_text(encoding="utf-8")

    for token in (
        "120-trait personality matrix",
        "60 Inner Ring + 60 Outer Ring",
        "traitSearch",
        "traitOnlyChanged",
        "traitReset",
        "innerTraits",
        "outerTraits",
        "/api/v1/personality/traits/catalog",
        "trait_profile: traitProfile()",
        "traitRevisionSelect",
        "loadTraitRevision",
        "/personality/revisions/",
        "/traits",
        "personality_revision",
        "0.50 = neutral",
        "operator-authored",
    ):
        assert token in html

    assert "catalog.trait_count!==120" in html
    assert 'result.trait_profile_sha256' in html
    assert 'traits?.active_trait_count' in html
    assert "Guided Personality · 120 traits" in person
    assert 'id="personalityManualHint"' in person
    assert "Redigér 120 traits" in person_js
    assert "trait_profile_sha256=" in person_js
    assert "personality_revision=" in person_js
    assert "structuredPersonalityMarkers" in person_js
    assert "manualPersonalityHasStructuredProvenance" in person_js
    assert "updateManualPersonalityEditorState" in person_js
    assert "Structured personality-kandidater skal redigeres via Guided Personality" in person_js

def test_guided_request_unknown_trait_normalizes_to_authoring_error() -> None:
    request = GuidedPersonalityRequest(
        communication=_communication(),
        trait_profile={
            "inner_ring": {"not_a_trait": 0.7},
            "outer_ring": {},
        },
    )

    from bodyrig.personality_authoring import PersonalityAuthoringError

    with pytest.raises(
        PersonalityAuthoringError,
        match="unknown inner-ring traits",
    ):
        _authoring_kwargs(request)

def test_trait_revision_api_returns_exact_persisted_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = create_profile(tmp_path, display_name="API Trait")
    traits = {
        "inner_ring": {"curiosity": 0.9},
        "outer_ring": {"empathy": 0.85},
    }
    saved = save_guided_personality(
        tmp_path,
        profile["person_id"],
        default_language="da",
        communication=_communication(),
        trait_profile=build_trait_profile(**traits),
    )

    monkeypatch.setattr(
        "bodyrig.guided_app.person_library",
        lambda: tmp_path,
    )
    result = personality_revision_traits(
        profile["person_id"],
        saved["saved_personality_revision"],
    )

    assert result["available"] is True
    assert result["revision_id"] == "personality-r0001"
    assert result["trait_profile"]["inner_ring"]["curiosity"] == pytest.approx(0.9)
    assert result["trait_profile"]["outer_ring"]["empathy"] == pytest.approx(0.85)
    assert len(result["trait_profile_sha256"]) == 64


def test_trait_revision_api_reports_legacy_revision_without_traits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = create_profile(tmp_path, display_name="API Legacy")
    saved = save_guided_personality(
        tmp_path,
        profile["person_id"],
        default_language="da",
        communication=_communication(),
    )
    monkeypatch.setattr(
        "bodyrig.guided_app.person_library",
        lambda: tmp_path,
    )

    result = personality_revision_traits(
        profile["person_id"],
        saved["saved_personality_revision"],
    )

    assert result == {
        "available": False,
        "revision_id": "personality-r0001",
        "trait_profile_sha256": None,
        "trait_profile": None,
    }

def test_personality_stash_context_api_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = {
        "person_id": "person-" + "2" * 32,
        "display_name": "Stash Context",
        "source": {
            "kind": "stash-performer",
            "performer_id": "42",
            "performer_name": "Target",
            "disambiguation": "",
        },
    }

    class _Client:
        def version(self) -> str:
            return "v0.31.1"

        def performer(self, performer_id: str) -> dict:
            return {
                "id": performer_id,
                "name": "Target",
                "disambiguation": "",
            }

        def scenes_for_performer(
            self,
            performer_id: str,
            *,
            limit: int = 200,
        ) -> list[dict]:
            return [
                {
                    "id": "scene-1",
                    "title": "Fixture",
                    "performers": [
                        {"id": performer_id, "name": "Target"},
                    ],
                    "tags": [{"name": "ContextTag"}],
                    "files": [],
                }
            ]

    monkeypatch.setattr(
        "bodyrig.guided_app._profile",
        lambda _person_id: profile,
    )
    monkeypatch.setattr(
        "bodyrig.guided_app._optional_stash_client",
        lambda: _Client(),
    )

    result = personality_stash_context(profile["person_id"])

    assert result["available"] is True
    assert result["scene_count_observed"] == 1
    assert result["top_tags"] == [{"name": "ContextTag", "count": 1}]
    assert result["authority"]["context_only"] is True
    assert result["authority"]["personality_trait_authority"] is False
    assert result["authority"]["personality_inference_authority"] is False
    assert result["authority"]["activation_authority"] is False


def test_guided_personality_ui_keeps_stash_outside_trait_authority() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(
        encoding="utf-8"
    )
    guided = Path("bodyrig/guided_app.py").read_text(encoding="utf-8")

    for token in (
        "Stash-kontekst · read-only",
        "stashContextRefresh",
        "stashContextSummary",
        "stashContextTags",
        "stashContextScenes",
        "/personality/stash-context",
        "Stash-data er kun authoring-kontekst",
        "må aldrig automatisk sætte de 120 personality-traits",
    ):
        assert token in html

    assert "renderStashContext(result)" in html
    assert "loadStashContext(personId)" in html
    assert "input.value=String(numeric)" not in html[
        html.index("function renderStashContext"):
        html.index("async function loadStashContext")
    ]
    assert '@app.get(' in guided
    assert '"/api/v1/people/{person_id}/personality/stash-context"' in guided
    assert "inspect_personality_stash_context" in guided

def _transcript_candidate_report() -> dict:
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


def _transcript_preview(report: dict | None = None) -> dict:
    return {
        "ok": True,
        "person_id": "person-" + "3" * 32,
        "body_revision": "body-r0001",
        "performer": {"id": "42", "name": "Target"},
        "source_manifest_sha256": "b" * 64,
        "source_media_count": 1,
        "transcript_count": 1 if report is not None else 0,
        "transcripts": (
            [
                {
                    "scene_id": "scene-7",
                    "name": "scene.en.srt",
                    "sha256": "a" * 64,
                }
            ]
            if report is not None
            else []
        ),
        "candidate_report": report,
        "candidate_count": report["candidate_count"] if report else 0,
        "suggested_exemplars": (
            list(report["suggested_exemplars"]) if report else []
        ),
        "operator_review_required": True,
        "speaker_identity_authority": False,
        "style_use_authority": False,
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def test_stash_transcript_candidate_api_is_preview_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _transcript_candidate_report()
    calls: list[tuple[str, str]] = []

    def _preview(root, person_id, *, body_revision):
        del root
        calls.append((person_id, body_revision))
        return _transcript_preview(report)

    monkeypatch.setattr(
        "bodyrig.guided_app.preview_source_personality_exemplars",
        _preview,
    )
    result = personality_stash_transcript_candidates(
        "person-" + "3" * 32,
        body_revision="body-r0001",
    )

    assert calls == [
        ("person-" + "3" * 32, "body-r0001"),
    ]
    assert result["candidate_report"] == report
    assert result["speaker_identity_authority"] is False
    assert result["style_use_authority"] is False
    assert result["personality_authority"] is False
    assert "approval" not in result


def test_stash_transcript_approval_revalidates_exact_source_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _transcript_candidate_report()
    calls = 0

    def _preview(root, person_id, *, body_revision):
        nonlocal calls
        del root
        assert person_id == "person-" + "3" * 32
        assert body_revision == "body-r0001"
        calls += 1
        return _transcript_preview(report)

    monkeypatch.setattr(
        "bodyrig.guided_app.preview_source_personality_exemplars",
        _preview,
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

    assert calls == 1
    assert result["candidate_report"] == report
    assert result["approval"]["approved_exemplars"] == report["candidates"]
    assert result["approval"]["operator_review"] == {
        "speaker_identity_confirmed": True,
        "style_use_approved": True,
    }
    assert result["personality_authority"] is False
    assert result["content_semantics"] == "style-only-not-biography-or-memory"


def test_stash_transcript_approval_rejects_stale_or_modified_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _transcript_candidate_report()
    provided = _transcript_candidate_report()
    provided["candidates"][0] = "Browser-modified utterance."
    provided["suggested_exemplars"] = [
        "Yeah, I mean, I would probably do that.",
    ]

    monkeypatch.setattr(
        "bodyrig.guided_app.preview_source_personality_exemplars",
        lambda root, person_id, *, body_revision: _transcript_preview(current),
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
    assert "source transcript candidate report changed" in str(exc.value.detail)


def test_stash_transcript_approval_requires_explicit_operator_confirmations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _transcript_candidate_report()
    monkeypatch.setattr(
        "bodyrig.guided_app.preview_source_personality_exemplars",
        lambda root, person_id, *, body_revision: _transcript_preview(report),
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


def test_guided_ui_requires_review_before_stash_transcript_style_use() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(
        encoding="utf-8"
    )

    for token in (
        "Find i Stash-kilder",
        "stashTranscriptLoad",
        "stashTranscriptCandidates",
        "stashTranscriptSpeakerConfirm",
        "stashTranscriptStyleConfirm",
        "stashTranscriptApprove",
        "/personality/stash-transcript-candidates",
        "/personality/stash-transcript-approval",
        "speaker_identity_confirmed",
        "style_use_approved",
        "styleEvidenceOrigin",
        "style_source: state.styleSource",
        "source_manifest_sha256:result.source_manifest_sha256",
        "onBodyRevisionChange",
        "transcriptSlotLimit",
        "approvedTranscriptCount",
        "samlet ${total}/12",
        "style-only evidence",
    ):
        assert token in html

    approval_block = html[
        html.index("async function approveStashTranscriptCandidates"):
        html.index("function onBodyRevisionChange")
    ]
    assert "state.styleReport=result.candidate_report" in approval_block
    assert "state.styleApproval=result.approval" in approval_block
    assert 'kind:"stash-source-transcript"' in approval_block
    assert "source_manifest_sha256:result.source_manifest_sha256" in approval_block
    assert "trait-" not in approval_block
    assert "input.value=" not in approval_block

    select_block = html[
        html.index("async function selectPerson"):
        html.index("function renderPreview")
    ]
    assert "loadStashTranscriptCandidates" not in select_block

    body_block = html[
        html.index("function onBodyRevisionChange"):
        html.index("function renderEvidenceStatus")
    ]
    assert 'state.styleEvidenceOrigin==="stash"' in body_block
    assert "clearEvidence()" in body_block

def test_guided_style_source_schema_requires_canonical_stash_binding() -> None:
    report = _transcript_candidate_report()
    request = GuidedPersonalityRequest(
        communication=_communication(),
        style_report=report,
        style_approval={
            "format": "bodyrig-personality-exemplar-approval",
            "version": 1,
            "candidate_report_sha256": "a" * 64,
            "selected_candidate_indexes": [0],
            "approved_exemplars": [report["candidates"][0]],
            "operator_review": {
                "speaker_identity_confirmed": True,
                "style_use_approved": True,
            },
            "personality_authority": False,
            "content_semantics": "style-only-not-biography-or-memory",
        },
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

