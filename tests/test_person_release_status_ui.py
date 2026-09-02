from pathlib import Path


def test_person_studio_release_status_is_read_only_and_candidate_bound() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/body_release_status.js").read_text(encoding="utf-8")
    css = Path("bodyrig/ui/body_release_status.css").read_text(encoding="utf-8")
    app = Path("bodyrig/app.py").read_text(encoding="utf-8")
    status = Path("bodyrig/person_release_status.py").read_text(encoding="utf-8")

    assert '/ui/body_release_status.css' in html
    assert '/ui/body_release_status.js' in html
    assert '/body/release-status?revision=' in js
    assert 'Gate A' in js and 'Windows' in js and 'Quest' in js and 'Release' in js
    assert 'Production låst' in js and 'Production klar' in js
    assert 'value.production_ready === true' in js
    assert 'value.production_activation === true' in js
    assert 'En aktiv Person Revision betyder kun' in js
    assert 'det er ikke production authority.' in js
    assert 'High-fidelity completeness og fysisk release er separate gates.' in js
    assert 'Person Studio kan kun vise status; den kan ikke selv attestere fysisk kvalitet.' in js
    assert 'Static fidelity-billeder er ikke release authority.' in js
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


def test_release_status_ui_has_no_physical_acceptance_write_action() -> None:
    js = Path("bodyrig/ui/body_release_status.js").read_text(encoding="utf-8")

    # Status polling is GET-only. Physical review/release remains in the existing
    # PowerShell evidence path and cannot be granted by the static gallery UI.
    assert 'method: "POST"' not in js
    assert "method: 'POST'" not in js
    assert 'record-renderer-acceptance' not in js
    assert 'complete-acceptance' not in js
