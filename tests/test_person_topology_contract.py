from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_topology.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "person_topology.css").read_text(encoding="utf-8")


def test_person_studio_has_person_topology() -> None:
    for token in (
        'id="personTopologySource"',
        'id="personTopologyBody"',
        'id="personTopologyVoice"',
        'id="personTopologyPersonality"',
        'id="personTopologyCore"',
        'id="personTopologyTwin"',
    ):
        assert token in HTML
    assert '<script src="/ui/person_topology.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/person_topology.css">' in HTML


def test_topology_reuses_structured_rendered_status_without_new_authority() -> None:
    for token in (
        'readField(root, "source")',
        'readField(root, "body")',
        'readField(root, "voice")',
        'readField(root, "personality")',
        'readField(root, "core")',
        'readField(root, "twin")',
        '"data-source-state"',
        '"data-twin-state"',
    ):
        assert token in JS
    assert "personSource" not in JS
    assert "personActive" not in JS
    assert "operator-digital-twin-badge" not in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS


def test_topology_has_futuristic_system_map_visuals() -> None:
    assert "person-topology-orbit" in CSS
    assert "radial-gradient" in CSS
    assert "person-topology-links" in CSS
    assert "box-shadow" in CSS


def test_topology_body_surfaces_structured_fidelity_state() -> None:
    assert "function fidelityState()" in JS
    assert 'root.dataset.fidelityState' in JS
    assert 'root.dataset.fidelityReviewState' in JS
    assert 'root.dataset.fidelityLabel' in JS
    assert '[state.body.label, fidelity?.label].filter(Boolean).join(" · ")' in JS
    assert 'fidelity?.state === "blocked" || fidelity?.review === "required"' in JS
    assert '"data-fidelity-state"' in JS
    assert '"data-fidelity-review-state"' in JS
    assert '"data-fidelity-label"' in JS
    assert "fidelity-attention" in CSS
    assert "fetch(" not in JS


def test_topology_body_attention_deeplinks_to_fidelity_center() -> None:
    assert 'button.id === "personTopologyBody"' in JS
    assert 'const bodyBound = topology?.body?.state === "bound";' in JS
    assert 'bodyBound && (fidelity?.state === "blocked" || fidelity?.review === "required")' in JS
    assert "BodyRigPersonNavigation?.focusFidelityCenter()" in JS
    assert "fetch(" not in JS


def test_topology_body_fidelity_state_is_not_color_only() -> None:
    assert 'bodyNode.title = fidelity?.label' in JS
    assert '"aria-label"' in JS
    assert 'BodyRig kræver handling' in JS
    assert 'fidelity-attention' in JS


def test_topology_clears_stale_fidelity_attention_when_state_is_invalid() -> None:
    assert 'bodyNode.classList.remove("fidelity-attention")' in JS
    assert 'bodyNode.title = "Åbn BodyRig"' in JS
    assert 'bodyNode.setAttribute("aria-label", "BodyRig")' in JS


def test_topology_ignores_stale_fidelity_without_body_binding() -> None:
    assert 'const fidelityAttention = bodyActive' in JS
    assert 'const fidelityLabel = bodyActive ? fidelity?.label : "";' in JS
    assert 'const bodyBound = topology?.body?.state === "bound";' in JS
