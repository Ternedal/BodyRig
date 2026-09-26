from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUD = (ROOT / "bodyrig" / "ui" / "person_hud.css").read_text(encoding="utf-8")
FILES = [
    "overview_control_strip.css",
    "body_control_strip.css",
    "voice_control_strip.css",
    "personality_control_strip.css",
    "assembly_control_strip.css",
    "history_control_strip.css",
]

def test_workspace_strips_stop_sticking_when_hud_wraps() -> None:
    assert "@media(max-width:1050px){.person-hud" in HUD
    for name in FILES:
        css = (ROOT / "bodyrig" / "ui" / name).read_text(encoding="utf-8")
        assert "@media(max-width:1050px)" in css
        assert "@media(max-width:1000px)" not in css
