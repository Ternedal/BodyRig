from pathlib import Path


def test_ui_uses_atomic_person_revision_flow() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/person_app.js").read_text(encoding="utf-8")
    spec = Path("docs/PERSON_PROFILE.md").read_text(encoding="utf-8")

    assert "Saml person" in html
    assert "Godkend og aktivér Person Revision" in html
    for control in (
        "assembleBody",
        "assembleVoice",
        "assemblePersonality",
        "matchBodyVoice",
        "matchVoicePersonality",
        "matchBodyPersonality",
        "matchOverall",
        "compatibilityNote",
    ):
        assert f'id="{control}"' in html

    assert "Gem og aktivér revision" not in html
    assert "Gem som personality-kandidat" in html
    assert "Gem som voice-kandidat" in html
    assert "/revisions/${encodeURIComponent(revisionId)}/activate" in js
    assert "/activate/${encodeURIComponent(kind)}" not in js
    assert "body_voice_match" in js
    assert "voice_personality_match" in js
    assert "body_personality_match" in js
    assert "overall_coherent" in js

    assert "aktiveres aldrig hver for sig" in spec
    assert "Person Revision — atomic activation unit" in spec


def test_person_ui_requires_cross_modal_audition_before_approval() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/person_app.js").read_text(encoding="utf-8")
    app = Path("bodyrig/app.py").read_text(encoding="utf-8")

    for token in (
        "Mine personer",
        "assemblyBodyPreview",
        "assemblyVoiceAudio",
        "assemblyPersonalityText",
        "Forbered audition",
        "Hørt til ende",
    ):
        assert token in html or token in js

    assert 'addEventListener("ended"' in js
    assert "bodyLoaded" in js
    assert "voiceHeard" in js
    assert "personalityShown" in js
    assert "assembly_fingerprint" in js
    assert "/assembly" in js
    assert "changed after audition" in app
    assert "verify_receipt" in app
    assert "write_receipt" in app


def test_voice_candidates_come_from_voicerig_library_not_manual_ids_or_paths() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/person_app.js").read_text(encoding="utf-8")

    assert "voiceLibrarySelect" in html
    assert "/api/v1/voicerig/voices" in js
    assert "voice_package" in js
    assert "voiceIdInput" not in html
    assert "voicePathInput" not in html
    assert "package_path" not in js


def test_component_selection_change_invalidates_previous_review() -> None:
    js = Path("bodyrig/ui/person_app.js").read_text(encoding="utf-8")
    assert 'for (const id of ["assembleBody", "assembleVoice", "assemblePersonality"])' in js
    assert "Kandidatvalg ændret — forbered audition igen." in js
    assert "selectedAssemblyKey" in js
    assert "a.key === selectedAssemblyKey()" in js
