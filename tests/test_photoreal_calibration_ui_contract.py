from __future__ import annotations

from pathlib import Path

from bodyrig.app import app


def test_photoreal_calibration_api_routes_are_exposed() -> None:
    paths = app.openapi()["paths"]

    status = paths[
        "/api/v1/people/{person_id}/body/photoreal-calibration"
    ]
    diagnostic = paths[
        "/api/v1/people/{person_id}/body/"
        "photoreal-calibration/diagnostic"
    ]

    assert "get" in status
    assert "post" in diagnostic


def test_person_studio_loads_calibration_status_ui() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path(
        "bodyrig/ui/photoreal_calibration_status.js"
    ).read_text(encoding="utf-8")
    css = Path(
        "bodyrig/ui/photoreal_calibration_status.css"
    ).read_text(encoding="utf-8")
    app_source = Path("bodyrig/app.py").read_text(encoding="utf-8")

    assert '/ui/photoreal_calibration_status.css' in html
    assert '/ui/photoreal_calibration_status.js' in html
    assert 'photoreal_calibration_ui_router' in app_source
    assert 'app.include_router(photoreal_calibration_ui_router)' in app_source

    assert 'Photoreal V2 · identity calibration' in js
    assert 'Stage 13 BLOCKED' in js
    assert 'Stage 13 PASS' in js
    assert 'Kør diagnostic' in js
    assert 'Stash-kontekst' in js
    assert 'Stash-data er kun kontekst' in js
    assert 'Quality-audit kræver re-extraction' in js
    assert 'Closest positive group:' not in js
    assert 'Nærmeste positive group' in js
    assert '/body/photoreal-calibration' in js
    assert '/body/photoreal-calibration/diagnostic' in js
    assert '{ method: "POST" }' in js

    assert '.photoreal-calibration-grid' in css
    assert '.photoreal-calibration-blocker' in css
    assert 'var(--danger)' in css


def test_calibration_ui_keeps_authority_boundary_explicit() -> None:
    service = Path(
        "bodyrig/photoreal_calibration_ui.py"
    ).read_text(encoding="utf-8")
    js = Path(
        "bodyrig/ui/photoreal_calibration_status.js"
    ).read_text(encoding="utf-8")

    assert '"diagnostic_only": True' in service
    assert '"identity_matching_authority": False' in service
    assert '"teacher_training_authorized": False' in service
    assert '"photoreal_acceptance_authority": False' in service
    assert '"production_activation": False' in service

    assert (
        "Diagnosticen er read-only og kan ikke give identity matching"
        in js
    )
    assert "Stash-data er kun kontekst" in js


def test_calibration_ui_does_not_start_extraction_or_mutate_stage13() -> None:
    api_source = Path(
        "bodyrig/photoreal_calibration_ui_api.py"
    ).read_text(encoding="utf-8")
    service = Path(
        "bodyrig/photoreal_calibration_ui.py"
    ).read_text(encoding="utf-8")

    assert "photoreal_identity_calibration_diagnostic" in service
    assert "build_identity_calibration_diagnostic_files" in service
    assert "photoreal_identity_calibration_extractor" not in api_source
    assert "photoreal_reference_vision_adapter" not in api_source
    assert "build_identity_calibration_files" not in service
    assert "subprocess" not in service
