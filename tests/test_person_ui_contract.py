from pathlib import Path


def test_ui_uses_atomic_person_revision_flow() -> None:
    html = Path("bodyrig/ui/index.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/app.js").read_text(encoding="utf-8")
    spec = Path("docs/PERSON_PROFILE.md").read_text(encoding="utf-8")

    assert "Saml person" in html
    assert "Godkend og aktivér person-revision" in html
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
