from pathlib import Path


def test_person_studio_has_operations_control_plane() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")

    assert 'data-tab="operations"' in html
    assert 'id="tab-operations"' in html
    assert "/ui/operator_control_plane.css" in html
    assert "/ui/operator_control_plane.js" in html
    for endpoint in (
        "/api/v1/health",
        "/api/v1/operator-authority",
        "/api/v1/stash/health",
        "/api/v1/modelrig/health",
        "/api/v1/voicerig/health",
        "/api/v1/runtime/state",
        "/api/v1/jobs",
    ):
        assert endpoint in js
    assert "/cancel" in js
    assert "Annullér" in js
    assert "setTimeout(() => void refresh" in js
