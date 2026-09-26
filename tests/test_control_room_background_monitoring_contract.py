from pathlib import Path


JS = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")
HUD = Path("bodyrig/ui/person_hud.js").read_text(encoding="utf-8")
ACTIVITY = Path("bodyrig/ui/person_activity_drawer.js").read_text(encoding="utf-8")


def test_drift_monitoring_runs_while_person_studio_is_visible_outside_drift() -> None:
    assert "const ACTIVE_REFRESH_MS = 10000;" in JS
    assert "const BACKGROUND_REFRESH_MS = 30000;" in JS
    assert "const HIDDEN_REFRESH_MS = 60000;" in JS
    assert "if (!visible() && !force) return;" not in JS
    refresh = JS[JS.index("async function refresh"):JS.index("function schedule")]
    assert "if (document.hidden && !force)" in refresh
    assert "schedule(HIDDEN_REFRESH_MS);" in refresh
    assert "schedule(visible() ? ACTIVE_REFRESH_MS : BACKGROUND_REFRESH_MS);" in refresh
    assert "schedule(1500);" in JS


def test_hidden_browser_tab_does_not_poll_but_resumes_immediately() -> None:
    visibility = JS[
        JS.index('document.addEventListener("visibilitychange"'):
        JS.index("restoreServiceObservations();")
    ]
    assert "if (!document.hidden)" in visibility
    assert "void refresh(true);" in visibility
    assert "schedule(HIDDEN_REFRESH_MS);" in visibility

    observer = JS[
        JS.index('const personNode = document.getElementById("personId")'):
        JS.index('for (const id of ["operatorLaunchPersonFilter"')
    ]
    assert "if (!document.hidden)" in observer
    assert "void refresh(true);" in observer
    assert "schedule(HIDDEN_REFRESH_MS);" in observer


def test_global_control_room_consumers_remain_dom_only() -> None:
    assert "operatorAttentionBadge" in HUD
    assert "operatorAttentionItems" in ACTIVITY
    for source in (HUD, ACTIVITY):
        assert "fetch(" not in source
        assert "POST" not in source
        assert "/action" not in source
