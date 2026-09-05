from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "bodyrig" / "high_fidelity_preview_jobs.py"
API = ROOT / "bodyrig" / "high_fidelity_preview_api.py"
APP = ROOT / "bodyrig" / "app.py"
UI = ROOT / "bodyrig" / "ui" / "high_fidelity_preview.js"
BASELINE_GALLERY = ROOT / "bodyrig" / "ui" / "body_review_gallery.js"


def test_continuation_runs_anatomy_then_components_then_exact_windows_preview() -> None:
    source = MANAGER.read_text(encoding="utf-8")

    anatomy = source.index('str(root / "run-subject-anatomy-physical-gate.ps1")')
    components = source.index('str(root / "run-subject-component-discovery.ps1")', anatomy)
    preview = source.index('str(root / "run-source-hair-eye-windows-preview.ps1")', components)

    assert anatomy < components < preview
    assert '"retained-anatomy-source"' in source
    assert 'target_family must be explicitly female, male or neutral' in source
    assert 'and job.get("body_revision") == body_revision' in source
    assert 'high-fidelity continuation requires the exact BodyRig revision that produced the baseline body' in source


def test_anatomy_alias_is_reused_from_portable_identity_instead_of_asserting_canonical_body_id() -> None:
    source = MANAGER.read_text(encoding="utf-8")
    anatomy_start = source.index("anatomy_args = [")
    anatomy_end = source.index("]\n            code = self._run_command", anatomy_start)
    anatomy_args = source[anatomy_start:anatomy_end]

    assert '"-TargetFamily"' in anatomy_args
    assert '"-BodyId"' not in anatomy_args
    assert 'str(job["canonical_body_id"])' not in anatomy_args


def test_success_is_not_persisted_until_all_exact_hash_evidence_validates() -> None:
    source = MANAGER.read_text(encoding="utf-8")

    status = source.index('candidate["status"] = "succeeded"')
    validate = source.index("_validate_completed(candidate)", status)
    persist = source.index("_write_job(candidate)", validate)

    assert status < validate < persist
    assert 'current["status"] = "failed"' in source
    assert "baseline body revision er uændret" in source


def test_completed_preview_revalidates_review_authority_and_six_images_fail_closed() -> None:
    source = MANAGER.read_text(encoding="utf-8")

    for view in (
        "front-full",
        "three-quarter-full",
        "side-full",
        "face-front",
        "face-zoom",
        "eyes-closeup",
    ):
        assert f'"{view}"' in source

    assert 'runtime_value.get("hairComponentAuthority") is not False' in source
    assert 'runtime_value.get("eyeComponentAuthority") is not False' in source
    assert 'runtime_value.get("productionActivation") is not False' in source
    assert 'comparison.get("physical_acceptance_authority") is not False' in source
    assert 'comparison.get("production_activation") is not False' in source
    assert '"comparison_only": True' in source
    assert '"human_review_required": True' in source
    assert '"production_activation": False' in source
    assert "high-fidelity preview image bytes changed after validation" in source


def test_main_app_registers_preview_router_and_baseline_gallery_loads_ui_extension_isolated() -> None:
    app_source = APP.read_text(encoding="utf-8")
    api_source = API.read_text(encoding="utf-8")
    gallery_source = BASELINE_GALLERY.read_text(encoding="utf-8")

    assert "from .high_fidelity_preview_api import router as high_fidelity_preview_router" in app_source
    assert "app.include_router(high_fidelity_preview_router)" in app_source
    assert '@router.post("/api/v1/people/{person_id}/body/high-fidelity-preview")' in api_source
    assert '@router.get("/api/v1/people/{person_id}/body/high-fidelity-preview")' in api_source
    assert '@router.get("/api/v1/high-fidelity-preview-jobs/{job_id}/image/{view}")' in api_source
    assert 'import("/ui/high_fidelity_preview.js")' in gallery_source
    assert ".catch((error) =>" in gallery_source


def test_person_studio_requires_explicit_family_and_surfaces_six_hash_bound_review_views() -> None:
    source = UI.read_text(encoding="utf-8")

    assert '<option value="">Vælg eksplicit…</option>' in source
    for family in ("female", "male", "neutral"):
        assert f'<option value="{family}">{family}</option>' in source
    assert "BodyRig gætter ikke target family" in source
    assert 'job?.kind === "body-build" && job.status === "succeeded" && job.body_revision === revision' in source
    assert "body_job_id: bodyJob.job_id, target_family: targetFamily" in source
    for view in (
        '"front-full"',
        '"three-quarter-full"',
        '"side-full"',
        '"face-front"',
        '"face-zoom"',
        '"eyes-closeup"',
    ):
        assert view in source
    assert 'badge.textContent = "6/6 hash-bundet"' in source
    assert "Iris:" in source
    assert "Eyelashes:" in source
    assert "production activation=false" in source
    assert "baseline body revision er bevaret" in source.lower()
