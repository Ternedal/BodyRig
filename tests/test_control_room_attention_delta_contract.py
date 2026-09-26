from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "bodyrig" / "ui" / "operator_control_plane.js").read_text(encoding="utf-8")
ACTIVITY = (ROOT / "bodyrig" / "ui" / "person_activity_drawer.js").read_text(encoding="utf-8")
HUD = (ROOT / "bodyrig" / "ui" / "person_hud.js").read_text(encoding="utf-8")
CONTROL_CSS = (ROOT / "bodyrig" / "ui" / "operator_control_plane.css").read_text(encoding="utf-8")
ACTIVITY_CSS = (ROOT / "bodyrig" / "ui" / "person_activity_drawer.css").read_text(encoding="utf-8")
HUD_CSS = (ROOT / "bodyrig" / "ui" / "person_hud.css").read_text(encoding="utf-8")


def test_attention_delta_uses_session_local_semantic_keys_and_silent_baseline() -> None:
    assert "let attentionBaselineReady = false;" in CONTROL
    assert "let attentionScope = null;" in CONTROL
    assert "let activeAttentionKeys = new Set();" in CONTROL
    assert "const unseenAttentionKeys = new Set();" in CONTROL
    assert "function attentionTracking(items)" in CONTROL
    assert 'const scope = currentPersonId() || "no-person";' in CONTROL
    assert "if (!attentionBaselineReady || attentionScope !== scope)" in CONTROL
    assert "unseenAttentionKeys.clear();" in CONTROL
    assert "if (!activeAttentionKeys.has(key)) unseenAttentionKeys.add(key);" in CONTROL
    assert "if (!currentKeys.has(key)) unseenAttentionKeys.delete(key);" in CONTROL

    for token in (
        "service:",
        "job:",
        "photoreal:",
        "digital-twin:",
        "launch:",
    ):
        assert token in CONTROL

    assert "localStorage" not in CONTROL[
        CONTROL.index("function attentionTracking(items)"):
        CONTROL.index("async function refresh(", CONTROL.index("function attentionTracking(items)"))
    ]


def test_new_attention_is_rendered_until_live_activity_acknowledges_it() -> None:
    assert "new-attention" in CONTROL
    assert 'node.dataset.attentionKey = item.key;' in CONTROL
    assert 'badge.dataset.unseenCount = String(unseenCount);' in CONTROL
    assert 'badge.classList.toggle("has-new", unseenCount > 0);' in CONTROL
    assert 'new CustomEvent("bodyrig:attention-delta"' in CONTROL
    assert 'window.addEventListener("bodyrig:attention-seen", acknowledgeAttention);' in CONTROL
    assert "document.querySelectorAll("#operatorAttentionItems .new-attention")" in CONTROL

    assert "unseenAttentionCount" in ACTIVITY
    assert 'sourceNode.classList.contains("new-attention")' in ACTIVITY
    assert 'window.dispatchEvent(new CustomEvent("bodyrig:attention-seen"));' in ACTIVITY
    assert 'window.addEventListener("bodyrig:attention-delta", scheduleRefresh);' in ACTIVITY

    assert "unseenAttentionCount" in HUD
    assert 'classList.toggle("has-new", unseen > 0)' in HUD
    assert "· NY " in HUD
    assert 'window.addEventListener("bodyrig:attention-delta", refresh);' in HUD
    assert 'window.addEventListener("bodyrig:attention-seen", refresh);' in HUD


def test_attention_delta_adds_no_external_notification_or_action_authority() -> None:
    delta = CONTROL[
        CONTROL.index("function attentionTracking(items)"):
        CONTROL.index("async function refresh(", CONTROL.index("function attentionTracking(items)"))
    ]
    for forbidden in (
        "Notification(",
        "Audio(",
        "fetch(",
        'method: "POST"',
        "/action",
        "localStorage.setItem",
    ):
        assert forbidden not in delta

    for source in (ACTIVITY, HUD):
        assert "Notification(" not in source
        assert "fetch(" not in source
        assert 'method: "POST"' not in source
        assert "/action" not in source


def test_new_attention_visuals_respect_reduced_motion() -> None:
    assert ".operator-attention-item.new-attention" in CONTROL_CSS
    assert ".person-activity-toggle.has-new" in ACTIVITY_CSS
    assert ".person-activity-attention-item.new-attention" in ACTIVITY_CSS
    assert "@media(prefers-reduced-motion:no-preference)" in ACTIVITY_CSS
    assert ".person-hud-signal.attention.has-new" in HUD_CSS
    assert "@media(prefers-reduced-motion:no-preference)" in HUD_CSS
