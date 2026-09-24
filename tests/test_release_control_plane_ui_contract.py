from pathlib import Path


def test_release_status_ui_can_launch_only_canonical_backend_actions() -> None:
    app = Path("bodyrig/app.py").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/body_release_status.js").read_text(encoding="utf-8")
    launcher = Path("bodyrig/operator_launch.py").read_text(encoding="utf-8")

    assert '@app.post("/api/v1/people/{person_id}/body/release-control/action")' in app
    assert "physical-next" in app
    assert "high-fidelity-review" in app
    assert "Human physical attestation requires a concrete quality note." in app
    assert "High-fidelity human review requires a concrete quality note." in app
    assert "launch_canonical_operator(" in app
    assert "/body/release-control/action?revision=" in js
    assert "Registrér Windows review" in js
    assert "Registrér Quest review" in js
    assert "Registrér high-fidelity review" in js
    assert "shell=False" in launcher
    assert "pwsh" in launcher
