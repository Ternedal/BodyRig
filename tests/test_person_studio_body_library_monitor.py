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

def test_body_library_monitor_has_no_import_or_activation_authority() -> None:
    section = JS.split("function renderBodyLibrary", 1)[1].split("function boundedNumber", 1)[0]
    assert "fetch(" not in section
    assert "/api/v1/bodies/import" not in section
    assert "/activate" not in section
    assert 'method: "POST"' not in section
