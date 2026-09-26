from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "bodyrig" / "ui" / "operator_control_plane.js").read_text(encoding="utf-8")
ACTIVITY = (ROOT / "bodyrig" / "ui" / "person_activity_drawer.js").read_text(encoding="utf-8")
HUD = (ROOT / "bodyrig" / "ui" / "person_hud.js").read_text(encoding="utf-8")
CONTROL_CSS = (ROOT / "bodyrig" / "ui" / "operator_control_plane.css").read_text(encoding="utf-8")
ACTIVITY_CSS = (ROOT / "bodyrig" / "ui" / "person_activity_drawer.css").read_text(encoding="utf-8")
HUD_CSS = (ROOT / "bodyrig" / "ui" / "person_hud.css").read_text(encoding="utf-8")


def test_attention_delta_uses_persisted_per_person_semantic_keys_and_silent_first_baseline() -> None:
    assert "let attentionBaselineReady = false;" in CONTROL
    assert "let attentionScope = null;" in CONTROL
    assert "let activeAttentionKeys = new Set();" in CONTROL
    assert "const unseenAttentionKeys = new Set();" in CONTROL
    assert "const attentionPersistedScopes = new Map();" in CONTROL
    assert 'ATTENTION_STATE_STORAGE_KEY = "bodyrig-control-room-attention-state-v1"' in CONTROL
    assert "ATTENTION_STATE_RETENTION_MS = 24 * 60 * 60 * 1000" in CONTROL
    assert "function restoreAttentionPersistence()" in CONTROL
    assert "function persistAttentionState(scope)" in CONTROL
    assert "function activateAttentionScope(scope, currentKeys)" in CONTROL
    assert "function attentionTracking(items)" in CONTROL
    assert 'const scope = currentPersonId() || "no-person";' in CONTROL
    assert "return activateAttentionScope(scope, currentKeys);" in CONTROL
    assert "if (!persisted)" in CONTROL
    assert "activeAttentionKeys = currentKeys;" in CONTROL
    assert "if (!previousActive.has(key)) unseenAttentionKeys.add(key);" in CONTROL
    assert "if (!currentKeys.has(key)) unseenAttentionKeys.delete(key);" in CONTROL
    assert "persistAttentionState(scope);" in CONTROL
    assert "restoreAttentionPersistence();" in CONTROL

    for token in (
        "service:",
        "job:",
        "photoreal:",
        "digital-twin:",
        "launch:",
    ):
        assert token in CONTROL


def test_new_attention_is_rendered_until_live_activity_acknowledges_it() -> None:
    assert "new-attention" in CONTROL
    assert 'node.dataset.attentionKey = item.key;' in CONTROL
    assert 'badge.dataset.unseenCount = String(unseenCount);' in CONTROL
    assert 'badge.classList.toggle("has-new", unseenCount > 0);' in CONTROL
    assert 'new CustomEvent("bodyrig:attention-delta"' in CONTROL
    assert 'window.addEventListener("bodyrig:attention-seen", acknowledgeAttention);' in CONTROL
    assert "function syncAttentionPresentation()" in CONTROL
    assert 'document.querySelectorAll("#operatorAttentionItems [data-attention-key]")' in CONTROL

    assert "unseenAttentionCount" in ACTIVITY
    assert 'sourceNode.classList.contains("new-attention")' in ACTIVITY
    assert 'window.dispatchEvent(new CustomEvent("bodyrig:attention-seen"));' in ACTIVITY
    assert "function handleAttentionDelta(event)" in ACTIVITY
    assert "if (open && unseen > 0)" in ACTIVITY
    assert 'window.addEventListener("bodyrig:attention-delta", handleAttentionDelta);' in ACTIVITY

    assert "unseenAttentionCount" in HUD
    assert 'classList.toggle("has-new", unseen > 0)' in HUD
    assert "· NY " in HUD
    assert 'window.addEventListener("bodyrig:attention-delta", refresh);' in HUD
    assert 'window.addEventListener("bodyrig:attention-seen", refresh);' in HUD


def test_attention_delta_persistence_adds_no_external_notification_or_action_authority() -> None:
    delta = CONTROL[
        CONTROL.index("function validAttentionScope(value)"):
        CONTROL.index("async function refresh(", CONTROL.index("function attentionTracking(items)"))
    ]
    for forbidden in (
        "Notification(",
        "Audio(",
        "fetch(",
        'method: "POST"',
        "/action",
    ):
        assert forbidden not in delta

    assert "window.localStorage.getItem(ATTENTION_STATE_STORAGE_KEY)" in delta
    assert "window.localStorage.setItem(" in delta
    assert "JSON.stringify(payload)" in delta
    assert "Attention persistence is presentation-only" in delta

    for source in (ACTIVITY, HUD):
        assert "Notification(" not in source
        assert "fetch(" not in source
        assert 'method: "POST"' not in source
        assert "/action" not in source


def test_attention_persistence_is_bounded_validated_and_acknowledgement_persists() -> None:
    assert "function validAttentionScope(value)" in CONTROL
    assert 'scope === "no-person" || /^person-[0-9a-f]{32}$/.test(scope)' in CONTROL
    assert "function validAttentionKey(value)" in CONTROL
    assert "ATTENTION_STATE_SCOPE_LIMIT = 64" in CONTROL
    assert "ATTENTION_STATE_KEY_LIMIT = 512" in CONTROL
    assert "ATTENTION_KEY_PREFIXES" in CONTROL
    assert "normalizedAttentionKeys" in CONTROL
    assert "unique.size >= 32" in CONTROL
    assert "validAttentionStamp" in CONTROL
    assert "ATTENTION_STATE_RETENTION_MS" in CONTROL
    assert 'payload.format !== "bodyrig-control-room-attention-state"' in CONTROL
    assert "payload.version !== 1" in CONTROL
    assert "unseen_keys" in CONTROL
    assert ".filter((key) => activeSet.has(key))" in CONTROL
    assert "if (attentionScope) persistAttentionState(attentionScope);" in CONTROL


def test_attention_persistence_stores_keys_only_not_rendered_attention_content() -> None:
    persistence = CONTROL[
        CONTROL.index("function persistAttentionState(scope)"):
        CONTROL.index("function activateAttentionScope(", CONTROL.index("function persistAttentionState(scope)"))
    ]
    for forbidden in (
        "title",
        "detail",
        "action",
        "onClick",
        "severity",
    ):
        assert forbidden not in persistence
    assert "active_keys" in persistence
    assert "unseen_keys" in persistence
    assert "observed_ms" in persistence


def test_new_attention_visuals_respect_reduced_motion() -> None:
    assert ".operator-attention-item.new-attention" in CONTROL_CSS
    assert ".person-activity-toggle.has-new" in ACTIVITY_CSS
    assert ".person-activity-attention-item.new-attention" in ACTIVITY_CSS
    assert "@media(prefers-reduced-motion:no-preference)" in ACTIVITY_CSS
    assert ".person-hud-signal.attention.has-new" in HUD_CSS
    assert "@media(prefers-reduced-motion:no-preference)" in HUD_CSS


def test_attention_acknowledgement_syncs_across_tabs_without_storage_becoming_authority() -> None:
    assert "function parseAttentionPersistence(raw" in CONTROL
    assert "function mergeIncomingAttentionScope(current, incoming)" in CONTROL
    assert "function applyCrossTabAttentionPersistence(raw)" in CONTROL
    assert 'window.addEventListener("storage", (event) =>' in CONTROL
    assert "event.key !== ATTENTION_STATE_STORAGE_KEY" in CONTROL
    assert "applyCrossTabAttentionPersistence(event.newValue);" in CONTROL

    cross_tab = CONTROL[
        CONTROL.index("function applyCrossTabAttentionPersistence(raw)"):
        CONTROL.index("function persistAttentionState(scope)")
    ]
    assert "incomingActive.has(key) && !incomingUnseen.has(key)" in cross_tab
    assert "unseenAttentionKeys.delete(key);" in cross_tab
    assert "unseenAttentionKeys.add(" not in cross_tab
    assert "activeAttentionKeys =" not in cross_tab
    assert "fetch(" not in cross_tab
    assert 'method: "POST"' not in cross_tab
    assert "/action" not in cross_tab


def test_cross_tab_merge_never_resurrects_a_seen_active_key_from_stale_unseen_state() -> None:
    merge = CONTROL[
        CONTROL.index("function mergeIncomingAttentionScope(current, incoming)"):
        CONTROL.index("function syncAttentionPresentation()")
    ]
    assert "currentActive" in merge
    assert "currentUnseen" in merge
    assert "!currentActive.has(key) || currentUnseen.has(key)" in merge
    assert "incoming.observed_ms" in merge
    assert "current?.observed_ms" in merge


def test_cross_tab_attention_reuses_the_same_validated_bounded_storage_contract() -> None:
    parser = CONTROL[
        CONTROL.index("function parseAttentionPersistence(raw"):
        CONTROL.index("function restoreAttentionPersistence()")
    ]
    for token in (
        'payload.format !== "bodyrig-control-room-attention-state"',
        "payload.version !== 1",
        "validAttentionScope(scope)",
        "validAttentionStamp(value.observed_ms, now)",
        "normalizedAttentionKeys(value.active_keys)",
        "normalizedAttentionKeys(value.unseen_keys)",
        "ATTENTION_STATE_SCOPE_LIMIT",
    ):
        assert token in parser
