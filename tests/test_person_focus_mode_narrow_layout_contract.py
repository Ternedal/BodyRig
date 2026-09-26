from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "bodyrig" / "ui" / "person_focus_mode.css").read_text(encoding="utf-8")

def test_focus_mode_removes_sidebar_from_narrow_layout_flow() -> None:
    breakpoint = CSS.split("@media(max-width:900px){", 1)[1]
    assert "body.person-focus-mode .sidebar{display:none}" in breakpoint
    assert "body.person-focus-mode .app-shell{grid-template-columns:1fr}" in breakpoint
