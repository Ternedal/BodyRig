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


def test_person_ui_requires_modelrig_executed_cross_modal_audition_before_approval() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/person_app.js").read_text(encoding="utf-8")
    app = Path("bodyrig/app.py").read_text(encoding="utf-8")

    for token in (
        "Mine personer",
        "assemblyBodyPreview",
        "assemblyVoiceAudio",
        "assemblyPersonalityText",
        "assemblyModel",
        "assemblyPrompt",
        "assemblyReply",
        "Kør samlet audition",
        "ModelRig-svar hørt til ende",
    ):
        assert token in html or token in js

    assert 'addEventListener("ended"' in js
    assert "bodyLoaded" in js
    assert "voiceHeard" in js
    assert "personalityShown" in js
    assert "replyShown" in js
    assert "auditionId" in js
    assert "assembly_fingerprint" in js
    assert "audition_id: state.assembly.auditionId" in js
    assert "/api/v1/modelrig/models" in js
    assert "/auditions" in js
    assert "/assembly" in js
    assert "changed after audition" in app
    assert "verify_audition" in app
    assert "audition_receipt_sha256" in app
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


def test_component_model_or_prompt_change_invalidates_previous_audition() -> None:
    js = Path("bodyrig/ui/person_app.js").read_text(encoding="utf-8")
    assert 'for (const id of ["assembleBody", "assembleVoice", "assemblePersonality", "assemblyModel"])' in js
    assert '$("assemblyPrompt").addEventListener("input"' in js
    assert "selectedAuditionKey" in js
    assert "a.key === selectedAuditionKey()" in js
    assert "Kandidat eller model ændret — kør audition igen." in js
    assert "Testprompt ændret — kør audition igen." in js


def test_modelrig_token_is_transport_only_and_service_identity_is_checked_before_protected_calls() -> None:
    app = Path("bodyrig/app.py").read_text(encoding="utf-8")
    client = Path("bodyrig/modelrig_client.py").read_text(encoding="utf-8")
    audition = Path("bodyrig/person_audition.py").read_text(encoding="utf-8")
    profile = Path("bodyrig/person_profiles.py").read_text(encoding="utf-8")

    assert 'os.environ.get("MODELRIG_TOKEN"' in app
    assert "client.health()\n        models = client.models()" in app
    assert "modelrig.health()\n        reply = modelrig.chat" in app
    assert '"Authorization"' in client and 'f"Bearer {self.config.token}"' in client
    assert "MODELRIG_TOKEN" not in audition
    assert "MODELRIG_TOKEN" not in profile
    assert '"token"' not in audition


def test_windows_product_launcher_is_checkout_bound_and_opens_person_ui() -> None:
    script = Path("start-windows.ps1").read_text(encoding="utf-8")
    doc = Path("docs/PERSON_UI.md").read_text(encoding="utf-8")

    for token in (
        ".venv\\Scripts\\python.exe",
        ".venv\\Scripts\\bodyrig.exe",
        "bodyrig\\__init__.py",
        "git rev-parse HEAD",
        "git status --porcelain",
        "127.0.0.1:8775/api/v1/health",
        "bodyrig-ui-service",
        "ui-service.json",
        "Start-Process \"http://127.0.0.1:8775/\"",
    ):
        assert token in script

    assert "start-windows.ps1" in doc
    assert "Mine personer" in doc
    assert "assembly_fingerprint" in doc
    assert "VoiceRig" in doc
