from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ui_uses_unified_kaliv_brand_roles() -> None:
    css = (ROOT / "bodyrig" / "ui" / "styles.css").read_text(encoding="utf-8")
    html = (ROOT / "bodyrig" / "ui" / "index.html").read_text(encoding="utf-8")
    person = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")

    assert "--bg: #0B0A09;" in css
    assert "--panel: #171411;" in css
    assert "--ember: #D4AB52;" in css
    assert "--ember-fill: #B08A3E;" in css
    assert "--signal: #48C7FF;" in css
    assert "--signal-light: #73D6FF;" in css
    assert "--signal-glow: rgba(72,199,255,.22);" in css

    assert "KALIV · MODELRIG EMBODIMENT" in html
    assert "☥" in html
    assert "KALIV · MODELRIG PERSON STUDIO" in person


def test_live_runtime_surfaces_use_signal_role() -> None:
    photoreal = (ROOT / "bodyrig" / "ui" / "photoreal_control_plane.css").read_text(encoding="utf-8")
    continuation = (ROOT / "bodyrig" / "ui" / "high_fidelity_continuation.css").read_text(encoding="utf-8")
    operator = (ROOT / "bodyrig" / "ui" / "operator_control_plane.css").read_text(encoding="utf-8")
    cockpit = (ROOT / "bodyrig" / "ui" / "person_overview_cockpit.css").read_text(encoding="utf-8")
    calibration = (ROOT / "bodyrig" / "ui" / "photoreal_calibration_status.css").read_text(encoding="utf-8")

    assert "var(--signal)" in photoreal
    assert "var(--signal-light)" in photoreal
    assert "rgba(72,199,255" in continuation
    assert "var(--signal)" in operator
    assert "var(--signal)" in cockpit
    assert "var(--signal-light)" in calibration
