from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ui_uses_unified_kaliv_brand_roles() -> None:
    css = (ROOT / "bodyrig" / "ui" / "styles.css").read_text(encoding="utf-8")
    html = (ROOT / "bodyrig" / "ui" / "index.html").read_text(encoding="utf-8")

    # Canonical Kaliv / ModelRig foundation.
    assert "--bg: #0B0A09;" in css
    assert "--panel: #171411;" in css
    assert "--ember: #D4AB52;" in css
    assert "--ember-fill: #B08A3E;" in css

    # Signal is reserved for live tracking / inference / runtime activity.
    assert "--signal: #48C7FF;" in css
    assert "--signal-light: #73D6FF;" in css
    assert "--signal-glow: rgba(72,199,255,.22);" in css
    assert ".signal-ring" in css
    assert ".live-metric" in css

    # BodyRig remains a member of the Kaliv / ModelRig family.
    assert "KALIV · MODELRIG EMBODIMENT" in html
    assert "☥" in html
