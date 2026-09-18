from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.personality_authoring as authoring
from bodyrig.person_profiles import create_profile
from bodyrig.personality_authoring import (
    PersonalityAuthoringError,
    build_guided_personality,
    load_guided_personality_revision,
    save_guided_personality,
)
from bodyrig.personality_exemplar_approval import build_approval


def _communication() -> dict[str, float]:
    return {
        "directness": 0.6,
        "warmth": 0.6,
        "playfulness": 0.5,
        "formality": 0.4,
        "verbosity": 0.5,
        "initiative": 0.5,
    }


def _bodyprint() -> dict:
    return {
        "format": "modelrig-bodyprint",
        "version": 1,
        "motion": {
            "energy": 0.5,
            "gesture_frequency": 0.5,
            "gesture_amplitude": 0.5,
            "head_motion": 0.5,
        },
        "expression": {
            "gaze_strength": 0.5,
            "speech_motion": 0.5,
        },
    }


def _report() -> dict:
    return {
        "format": "bodyrig-personality-exemplar-candidates",
        "version": 1,
        "source_count": 1,
        "source_sha256": ["a" * 64],
        "candidate_count": 2,
        "candidates": [
            "That is actually pretty funny.",
            "Yeah, I mean, probably.",
        ],
        "suggested_exemplars": [
            "That is actually pretty funny.",
        ],
        "operator_review_required": True,
        "speaker_identity_authority": False,
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def _preview(report: dict, *, manifest: str = "b" * 64) -> dict:
    return {
        "ok": True,
        "person_id": "unused",
        "body_revision": "body-r0001",
        "performer": {"id": "42", "name": "Target"},
        "source_manifest_sha256": manifest,
        "source_media_count": 1,
        "transcript_count": 1,
        "transcripts": [
            {
                "scene_id": "scene-7",
                "name": "scene.en.srt",
                "sha256": "a" * 64,
            }
        ],
        "candidate_report": report,
        "candidate_count": report["candidate_count"],
        "suggested_exemplars": list(report["suggested_exemplars"]),
        "operator_review_required": True,
        "speaker_identity_authority": False,
        "style_use_authority": False,
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def _patch_bodyprint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        authoring,
        "_validated_bodyprint",
        lambda profile, revision_id: _bodyprint(),
    )


def test_guided_stash_style_evidence_is_bound_to_exact_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = create_profile(tmp_path, display_name="Style Source")
    report = _report()
    approval = build_approval(
        report,
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )
    _patch_bodyprint(monkeypatch)
    monkeypatch.setattr(
        authoring,
        "preview_source_personality_exemplars",
        lambda root, person_id, *, body_revision: _preview(report),
    )

    result = build_guided_personality(
        tmp_path,
        profile["person_id"],
        default_language="en",
        communication=_communication(),
        body_revision="body-r0001",
        style_report=report,
        style_approval=approval,
        style_source={
            "kind": "stash-source-transcript",
            "body_revision": "body-r0001",
            "source_manifest_sha256": "b" * 64,
        },
    )

    assert result["style_evidence"]["source_kind"] == "stash-source-transcript"
    assert result["style_evidence"]["source_body_revision"] == "body-r0001"
    assert (
        result["style_evidence"]["source_manifest_sha256"]
        == "b" * 64
    )
    style_notes = result["candidate"]["style_notes"]
    assert "style_source=stash-source-transcript" in style_notes
    assert "style_source_body_revision=body-r0001" in style_notes
    assert f"style_source_manifest_sha256={'b' * 64}" in style_notes
    assert "That is actually pretty funny." in result["candidate"]["instructions"]


def test_guided_stash_style_evidence_rejects_other_body_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = create_profile(tmp_path, display_name="Wrong Body")
    report = _report()
    approval = build_approval(
        report,
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )
    _patch_bodyprint(monkeypatch)

    with pytest.raises(
        PersonalityAuthoringError,
        match="bound to a different body revision",
    ):
        build_guided_personality(
            tmp_path,
            profile["person_id"],
            default_language="en",
            communication=_communication(),
            body_revision="body-r0001",
            style_report=report,
            style_approval=approval,
            style_source={
                "kind": "stash-source-transcript",
                "body_revision": "body-r0002",
                "source_manifest_sha256": "b" * 64,
            },
        )


def test_guided_stash_style_evidence_rejects_changed_source_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = create_profile(tmp_path, display_name="Changed Manifest")
    report = _report()
    approval = build_approval(
        report,
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )
    _patch_bodyprint(monkeypatch)
    monkeypatch.setattr(
        authoring,
        "preview_source_personality_exemplars",
        lambda root, person_id, *, body_revision: _preview(
            report,
            manifest="c" * 64,
        ),
    )

    with pytest.raises(
        PersonalityAuthoringError,
        match="source manifest changed",
    ):
        build_guided_personality(
            tmp_path,
            profile["person_id"],
            default_language="en",
            communication=_communication(),
            body_revision="body-r0001",
            style_report=report,
            style_approval=approval,
            style_source={
                "kind": "stash-source-transcript",
                "body_revision": "body-r0001",
                "source_manifest_sha256": "b" * 64,
            },
        )


def test_guided_stash_style_evidence_rejects_changed_candidate_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = create_profile(tmp_path, display_name="Changed Report")
    report = _report()
    current = _report()
    current["candidates"][0] = "Source changed this utterance."
    current["suggested_exemplars"] = ["Yeah, I mean, probably."]
    approval = build_approval(
        report,
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )
    _patch_bodyprint(monkeypatch)
    monkeypatch.setattr(
        authoring,
        "preview_source_personality_exemplars",
        lambda root, person_id, *, body_revision: _preview(current),
    )

    with pytest.raises(
        PersonalityAuthoringError,
        match="candidate report changed",
    ):
        build_guided_personality(
            tmp_path,
            profile["person_id"],
            default_language="en",
            communication=_communication(),
            body_revision="body-r0001",
            style_report=report,
            style_approval=approval,
            style_source={
                "kind": "stash-source-transcript",
                "body_revision": "body-r0001",
                "source_manifest_sha256": "b" * 64,
            },
        )


def test_manual_style_evidence_remains_backward_compatible_without_source_binding(
    tmp_path: Path,
) -> None:
    profile = create_profile(tmp_path, display_name="Manual Evidence")
    report = _report()
    approval = build_approval(
        report,
        selected_candidate_indexes=[1],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )

    result = build_guided_personality(
        tmp_path,
        profile["person_id"],
        default_language="en",
        communication=_communication(),
        style_report=report,
        style_approval=approval,
    )

    assert result["style_evidence"]["approved_count"] == 1
    assert "source_kind" not in result["style_evidence"]
    assert "style_source=" not in result["candidate"]["style_notes"]


def test_guided_stash_style_rejects_simultaneous_source_baseline_stack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = create_profile(tmp_path, display_name="Stack Conflict")
    report = _report()
    approval = build_approval(
        report,
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )
    _patch_bodyprint(monkeypatch)

    with pytest.raises(
        PersonalityAuthoringError,
        match="cannot be combined with source baseline stacking",
    ):
        build_guided_personality(
            tmp_path,
            profile["person_id"],
            default_language="en",
            communication=_communication(),
            body_revision="body-r0001",
            style_report=report,
            style_approval=approval,
            style_source={
                "kind": "stash-source-transcript",
                "body_revision": "body-r0001",
                "source_manifest_sha256": "b" * 64,
            },
            baseline_revision="personality-r0001",
        )


def test_saved_guided_stash_style_reopens_with_exact_source_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = create_profile(tmp_path, display_name="Round Trip")
    report = _report()
    approval = build_approval(
        report,
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )
    _patch_bodyprint(monkeypatch)
    monkeypatch.setattr(
        authoring,
        "preview_source_personality_exemplars",
        lambda root, person_id, *, body_revision: _preview(report),
    )

    saved = save_guided_personality(
        tmp_path,
        profile["person_id"],
        default_language="en",
        communication=_communication(),
        body_revision="body-r0001",
        style_report=report,
        style_approval=approval,
        style_source={
            "kind": "stash-source-transcript",
            "body_revision": "body-r0001",
            "source_manifest_sha256": "b" * 64,
        },
        feedback="reviewed transcript style",
    )

    reopened = load_guided_personality_revision(
        tmp_path,
        profile["person_id"],
        saved["saved_personality_revision"],
    )

    assert reopened["style_source"] == {
        "kind": "stash-source-transcript",
        "body_revision": "body-r0001",
        "source_manifest_sha256": "b" * 64,
    }
    assert reopened["style_approval"]["approved_exemplars"] == [
        "That is actually pretty funny."
    ]
