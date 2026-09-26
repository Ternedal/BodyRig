from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLES = (ROOT / "bodyrig" / "ui" / "styles.css").read_text(encoding="utf-8")
DRAWER = (ROOT / "bodyrig" / "ui" / "person_activity_drawer.css").read_text(encoding="utf-8")
PALETTE = (ROOT / "bodyrig" / "ui" / "person_command_palette.css").read_text(encoding="utf-8")

def test_toast_stacks_above_activity_drawer_below_command_palette() -> None:
    assert "z-index: 50;" in STYLES
    assert "z-index:40" in DRAWER
    assert "z-index:41" in DRAWER
    assert "z-index:70" in PALETTE
    assert "z-index:71" in PALETTE
