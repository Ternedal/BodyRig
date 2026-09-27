from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "operator_control_plane.js").read_text(encoding="utf-8")

def test_drift_exposes_read_only_body_library_inventory() -> None:
    assert 'id="operator-body-library-badge"' in HTML
    assert 'id="operator-body-library-list"' in HTML
    assert 'readApi("/api/v1/bodies")' in JS
    assert 'renderBodyLibrary(bodyLibrary);' in JS
    assert '"Aktiv runtime"' in JS

def test_body_library_monitor_has_no_import_or_free_path_authority() -> None:
    section = JS.split("function activateLibraryBody", 1)[1].split("function boundedNumber", 1)[0]
    assert "/api/v1/bodies/import" not in section
    assert "ImportRequest" not in section


def test_body_library_runtime_activation_is_explicit_and_backend_list_bound() -> None:
    section = JS.split("function activateLibraryBody", 1)[1].split("function boundedNumber", 1)[0]
    assert 'window.confirm(' in section
    assert 'api("/api/v1/bodies/" + encodeURIComponent(bodyId) + "/activate"' in section
    assert 'method: "POST"' in section
    assert 'activateLibraryBody(id, name, activate)' in section
