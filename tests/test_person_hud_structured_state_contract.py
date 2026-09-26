from pathlib import Path


HUD = Path("bodyrig/ui/person_hud.js").read_text(encoding="utf-8")
OVERVIEW = Path("bodyrig/ui/person_overview_cockpit.js").read_text(encoding="utf-8")
DRIFT = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")


def test_global_hud_uses_versioned_structured_cockpit_state() -> None:
    assert 'root.dataset.stateVersion !== "1"' in HUD
    assert 'integerDataset(root, "pipelineComplete")' in HUD
    assert 'integerDataset(root, "pipelineTotal")' in HUD
    assert 'root.dataset.bodyState' in HUD
    assert 'root.dataset.voiceState' in HUD
    assert 'root.dataset.personalityState' in HUD

    assert "parsePipeline" not in HUD
    assert 'text("overviewCockpitBadge")' not in HUD
    assert '.replace(/^Krop' not in HUD
    assert '.replace(/^Stemme' not in HUD
    assert '.replace(/^Personlighed' not in HUD


def test_overview_publishes_hud_state_from_authoritative_profile_snapshot() -> None:
    assert "function publishHudState(" in OVERVIEW
    assert 'hud.dataset.stateVersion = "1";' in OVERVIEW
    assert 'hud.dataset.personRevision = revision;' in OVERVIEW
    assert 'hud.dataset.pipelineComplete = String(complete);' in OVERVIEW
    assert 'hud.dataset.pipelineTotal = String(total);' in OVERVIEW
    assert 'hud.dataset.bodyState = bodyRevision ? "bound" : "unbound";' in OVERVIEW
    assert 'hud.dataset.voiceState = voiceRevision ? "bound" : "unbound";' in OVERVIEW
    assert 'hud.dataset.personalityState = personalityRevision ? "bound" : "unbound";' in OVERVIEW
    assert "publishHudUnknown();" in OVERVIEW


def test_hud_attention_uses_structured_drift_counts() -> None:
    assert 'badge.dataset.activeCount = String(activeCount);' in DRIFT
    assert 'badge.dataset.unseenCount = String(unseenCount);' in DRIFT
    assert 'badge?.dataset?.activeCount' in HUD
    assert 'badge?.dataset?.unseenCount' in HUD
    assert 'text("operatorAttentionBadge")' not in HUD

def test_global_control_surfaces_reuse_structured_attention_count() -> None:
    palette = Path("bodyrig/ui/person_command_palette.js").read_text(encoding="utf-8")
    activity = Path("bodyrig/ui/person_activity_drawer.js").read_text(encoding="utf-8")

    assert 'dataset?.activeCount' in palette
    assert 'integerDataset(badge, "activeCount")' in activity
    assert 'integerDataset(badge, "unseenCount")' in activity
    assert 'badge.dataset.stateVersion !== "1"' in activity
    assert 'textContent || ""' not in palette[palette.index("function attentionCount()"):palette.index("function commandHint")]
    assert 'operatorAttentionBadge")?.textContent' not in activity
