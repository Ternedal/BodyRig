from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.personality_embodiment_binding as binding_module
from bodyrig.personality_blueprint import build_blueprint
from bodyrig.personality_embodiment_binding import (
    PersonalityEmbodimentBindingError,
    build_binding,
    read_binding,
    verify_binding,
    write_binding,
)


def _communication() -> dict[str, float]:
    return {
        "directness": 0.6,
        "warmth": 0.7,
        "playfulness": 0.4,
        "formality": 0.3,
        "verbosity": 0.5,
        "initiative": 0.6,
    }


def _profile() -> dict:
    return {
        "person_id": "person-" + "a" * 32,
        "body_revisions": [
            {
                "revision_id": "body-r0001",
                "body_id": "person-body",
                "package_sha256": "b" * 64,
                "package_path": "/unused/body.mrbody",
            },
            {
                "revision_id": "body-r0002",
                "body_id": "other-body",
                "package_sha256": "c" * 64,
                "package_path": "/unused/other.mrbody",
            },
        ],
        "personality_revisions": [
            {
                "revision_id": "personality-r0001",
                "instructions": "Speak consistently.",
                "style_notes": "blueprint-bound",
            }
        ],
    }


def _full_bodyprint() -> dict:
    return {
        "format": "modelrig-bodyprint",
        "version": 1,
        "motion": {
            "energy": 0.7,
            "gesture_frequency": 0.6,
            "gesture_amplitude": 0.8,
            "head_motion": 0.4,
        },
        "expression": {
            "gaze_strength": 0.65,
            "speech_motion": 0.75,
        },
    }


def _blueprint(bodyprint: dict | None = None) -> dict:
    if bodyprint is None:
        return build_blueprint(default_language="da", communication=_communication())
    return build_blueprint(
        default_language="da",
        communication=_communication(),
        bodyprint=bodyprint,
        body_revision="body-r0001",
    )


def _patch_body(monkeypatch: pytest.MonkeyPatch, bodyprint: dict) -> None:
    body = _profile()["body_revisions"][0]
    monkeypatch.setattr(
        binding_module,
        "_bodyprint_for_revision",
        lambda profile, revision_id: (dict(body), dict(bodyprint)),
    )


def test_binding_marks_complete_bodyprint_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    bodyprint = _full_bodyprint()
    _patch_body(monkeypatch, bodyprint)

    receipt = build_binding(
        _profile(),
        personality_revision="personality-r0001",
        blueprint=_blueprint(bodyprint),
    )

    assert receipt["grounding"] == {
        "communication": "operator-authored",
        "embodiment": "bodyprint-observed",
        "body_revision": "body-r0001",
    }
    assert receipt["body"] == {
        "revision_id": "body-r0001",
        "body_id": "person-body",
        "package_sha256": "b" * 64,
    }
    assert receipt["embodiment_evidence"]["status"] == "complete-observed"
    assert receipt["embodiment_evidence"]["neutral_fallback_fields"] == []
    assert receipt["embodiment_evidence"]["observed_fields"] == [
        "gaze_strength",
        "gesture_amplitude",
        "gesture_frequency",
        "head_motion",
        "movement_energy",
        "speech_motion",
    ]
    assert receipt["human_review_required"] is True
    assert receipt["production_authority"] is False


def test_binding_exposes_neutral_fallbacks_instead_of_calling_them_observed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sparse = {
        "format": "modelrig-bodyprint",
        "version": 1,
        "motion": {"energy": 0.2},
    }
    _patch_body(monkeypatch, sparse)

    receipt = build_binding(
        _profile(),
        personality_revision="personality-r0001",
        blueprint=_blueprint(sparse),
    )

    assert receipt["embodiment_evidence"] == {
        "status": "partial-observed",
        "observed_fields": ["movement_energy"],
        "neutral_fallback_fields": [
            "gaze_strength",
            "gesture_amplitude",
            "gesture_frequency",
            "head_motion",
            "speech_motion",
        ],
    }


def test_operator_authored_personality_has_no_fake_body_evidence() -> None:
    receipt = build_binding(
        _profile(),
        personality_revision="personality-r0001",
        blueprint=_blueprint(),
    )

    assert receipt["body"] is None
    assert receipt["embodiment_evidence"] == {
        "status": "operator-authored",
        "observed_fields": [],
        "neutral_fallback_fields": [],
    }


def test_verify_binding_fails_closed_on_selected_body_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodyprint = _full_bodyprint()
    _patch_body(monkeypatch, bodyprint)
    blueprint = _blueprint(bodyprint)
    receipt = build_binding(
        _profile(),
        personality_revision="personality-r0001",
        blueprint=blueprint,
    )

    with pytest.raises(PersonalityEmbodimentBindingError, match="selected body revision conflicts"):
        verify_binding(
            _profile(),
            receipt,
            selected_body_revision="body-r0002",
            blueprint=blueprint,
        )

    verified = verify_binding(
        _profile(),
        receipt,
        selected_body_revision="body-r0001",
        blueprint=blueprint,
    )
    assert verified == receipt


def test_binding_is_create_only_and_readable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodyprint = _full_bodyprint()
    _patch_body(monkeypatch, bodyprint)
    profile = _profile()
    blueprint = _blueprint(bodyprint)

    first = write_binding(
        tmp_path,
        profile,
        personality_revision="personality-r0001",
        blueprint=blueprint,
    )
    before = first.read_bytes()
    second = write_binding(
        tmp_path,
        profile,
        personality_revision="personality-r0001",
        blueprint=blueprint,
    )

    assert first == second
    assert second.read_bytes() == before
    assert read_binding(
        tmp_path,
        person_id=profile["person_id"],
        personality_revision="personality-r0001",
    )["blueprint_sha256"] == build_binding(
        profile,
        personality_revision="personality-r0001",
        blueprint=blueprint,
    )["blueprint_sha256"]
