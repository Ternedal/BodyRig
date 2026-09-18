from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from bodyrig.guided_app import (
    GuidedPersonalityRequest,
    _authoring_kwargs,
    personality_revision_traits,
    personality_stash_context,
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

