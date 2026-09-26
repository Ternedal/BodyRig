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


def test_topology_reuses_existing_status_without_new_authority() -> None:
    for token in (
        "personSource",
        "personActive",
        "bodyActive",
        "voiceActive",
        "personalityActive",
        "operator-digital-twin-badge",
    ):
        assert token in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS


def test_topology_has_futuristic_system_map_visuals() -> None:
    assert "person-topology-orbit" in CSS
    assert "radial-gradient" in CSS
    assert "person-topology-links" in CSS
    assert "box-shadow" in CSS
