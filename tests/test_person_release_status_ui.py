from pathlib import Path


def test_person_studio_release_status_is_candidate_bound_and_controlled() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/body_release_status.js").read_text(encoding="utf-8")
    css = Path("bodyrig/ui/body_release_status.css").read_text(encoding="utf-8")
    app = Path("bodyrig/app.py").read_text(encoding="utf-8")
    status = Path("bodyrig/person_release_status.py").read_text(encoding="utf-8")

    assert '/ui/body_release_status.css' in html
    assert '/ui/body_release_status.js' in html
    assert '/body/release-status?revision=' in js
    assert '/body/release-control/action?revision=' in js
    assert 'Gate A' in js and 'Windows' in js and 'Quest' in js and 'Release' in js
    assert 'Production låst' in js and 'Production klar' in js
    assert 'value.production_ready === true' in js
    assert 'value.production_activation === true' in js
    assert 'En aktiv Person Revision er ikke production authority' in js
    assert 'komplette high-fidelity components' in js
    assert 'eksplicit high-fidelity human review' in js
    assert 'fysisk Windows + Quest final release' in js
    assert 'fysisk kvalitet kan kun attesteres efter din eksplicitte review-note' in js
    assert 'blocked: "Blokeret"' in js
    assert 'Operator checkout blokerer næste kommando:' in js
    assert 'Fysisk acceptance er blokeret ved' in js
    assert '.body-release-stages' in css
    assert 'var(--panel-2)' in css

    route = '@app.get("/api/v1/people/{person_id}/body/release-status")'
    assert route in app
    route_index = app.index(route)
    route_body = app[route_index : route_index + 1400]
    assert '_body_bytes_match(item)' in route_body
    assert 'inspect_candidate_release_status(' in route_body
    assert 'ui_jobs.list(person_id=person_id)' in route_body
    assert 'package_sha256=str(item["package_sha256"])' in route_body

    control_route = '@app.post("/api/v1/people/{person_id}/body/release-control/action")'
    assert control_route in app
    assert 'action: str = Field(pattern=r"^(physical-next|high-fidelity-review)$")' in app
    assert 'Human physical attestation requires a concrete quality note.' in app
    assert 'High-fidelity human review requires a concrete quality note.' in app
    assert 'launch_canonical_operator(' in app
    assert '_operator_quest_status()' in app

    assert 'job.get("kind") == "body-build"' in status
    assert 'job.get("body_revision") == body_revision' in status
    assert 'job.get("status") != "succeeded"' in status
    assert 'Gate A package SHA no longer matches the registered body revision' in status
    assert 'attestation.get("attestation") != "operator-supplied"' in status
    assert 'bodyrig-human-quality-v1' in status
    assert 'apply_reference_policy(inspect_acceptance_dir(acceptance_dir))' in status
    assert '_REFERENCE_OPERATOR_FILES' in status
    assert 'does not match acceptance revision' in status
    assert 'Executable next command withheld' in status
    assert 'operator_checkout' in status
    assert 'production_activation' in status
    assert 'production_ready' in status
    assert 'fidelity' in status


def test_release_status_ui_never_sends_arbitrary_shell_command() -> None:
    js = Path("bodyrig/ui/body_release_status.js").read_text(encoding="utf-8")
    app = Path("bodyrig/app.py").read_text(encoding="utf-8")
    launcher = Path("bodyrig/operator_launch.py").read_text(encoding="utf-8")

    assert 'method: "POST"' in js
    assert 'body: JSON.stringify({' in js
    assert 'action,' in js
    assert 'quality_note:' in js
    assert 'quest_serial:' in js
    assert 'command:' not in js
    assert 'command = status.get("next_command")' in app
    assert 'launch_canonical_operator(' in app
    assert 'shell=False' in launcher
