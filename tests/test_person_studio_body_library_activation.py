from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "bodyrig" / "ui" / "operator_control_plane.js").read_text(encoding="utf-8")
APP = (ROOT / "bodyrig" / "app.py").read_text(encoding="utf-8")
RUNTIME = (ROOT / "bodyrig" / "runtime.py").read_text(encoding="utf-8")

def test_body_library_activation_is_bound_to_latest_inventory() -> None:
    assert "let bodyLibraryBodyIds = new Set();" in JS
    assert "if (!bodyLibraryBodyIds.has(bodyId)) return;" in JS
    assert '"/api/v1/bodies/" + encodeURIComponent(bodyId) + "/activate"' in JS
    assert 'method: "POST"' in JS.split("async function activateBodyLibraryBody", 1)[1].split("function renderBodyLibrary", 1)[0]

def test_body_library_activation_requires_explicit_operator_confirmation() -> None:
    section = JS.split("async function activateBodyLibraryBody", 1)[1].split("function renderBodyLibrary", 1)[0]
    assert "window.confirm" in section
    assert "rydder aktiv utterance/cue/speech" in section

def test_backend_revalidates_package_and_runtime_switch_is_session_boundary() -> None:
    assert '@app.post("/api/v1/bodies/{body_id}/activate")' in APP
    assert 'validated = validate_package(body_library() / f"{body_id}.mrbody")' in APP
    assert 'return runtime.activate(validated.manifest["id"], validated.bodyprint).__dict__' in APP
    activate = RUNTIME.split("def activate(", 1)[1].split("def apply_cue", 1)[0]
    assert "self._state.utterance_id = None" in activate
    assert "self._state.cue = None" in activate
    assert "self._state.speech = None" in activate

def test_body_library_activation_does_not_add_import_authority() -> None:
    section = JS.split("async function activateBodyLibraryBody", 1)[1].split("function renderBodyLibrary", 1)[0]
    assert "/api/v1/bodies/import" not in section
