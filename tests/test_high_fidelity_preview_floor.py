from __future__ import annotations

import threading

import pytest

import bodyrig.high_fidelity_preview_jobs as preview_jobs


PRE_FLOOR = "a" * 40
JOB_ID = "hfpreview-" + "b" * 32


def _manager_without_reconcile() -> preview_jobs.HighFidelityPreviewManager:
    manager = preview_jobs.HighFidelityPreviewManager.__new__(preview_jobs.HighFidelityPreviewManager)
    manager._lock = threading.RLock()
    manager._processes = {}
    return manager


def test_start_rejects_pre_floor_body_before_checkout(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    manager = _manager_without_reconcile()
    body_job = {
        "bodyrig_revision": PRE_FLOOR,
        "body_revision": "body-r1",
        "canonical_body_id": "body-1",
        "clone_output": str(tmp_path / "clone"),
    }
    monkeypatch.setattr(
        preview_jobs,
        "_body_job_authority",
        lambda _person_id, _body_job_id: (body_job, {"display_name": "Subject"}, tmp_path),
    )
    monkeypatch.setattr(preview_jobs, "_revision_meets_current_fidelity_floor", lambda _revision: False)

    checkout_called = False

    def unexpected_checkout(_revision: str):
        nonlocal checkout_called
        checkout_called = True
        raise AssertionError("pre-floor baseline must fail before checkout routing")

    monkeypatch.setattr(preview_jobs, "_checkout_revision", unexpected_checkout)

    with pytest.raises(preview_jobs.HighFidelityPreviewError, match="current high-fidelity preview floor"):
        manager.start("person-1", body_job_id="body-job-1", target_family="female")

    assert checkout_called is False


def test_persisted_succeeded_pre_floor_preview_loses_current_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preview_jobs, "_revision_meets_current_fidelity_floor", lambda _revision: False)
    job = {
        "status": "succeeded",
        "job_id": JOB_ID,
        "bodyrig_revision": PRE_FLOOR,
        "target_family": "female",
        "canonical_body_id": "body-1",
    }

    with pytest.raises(preview_jobs.HighFidelityPreviewError, match="current high-fidelity preview floor"):
        preview_jobs._validate_completed(job)


def test_floor_guard_accepts_current_revision_without_changing_review_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preview_jobs, "_revision_meets_current_fidelity_floor", lambda _revision: True)
    preview_jobs._require_current_fidelity_floor("c" * 40, label="test preview")

    source = preview_jobs.Path(preview_jobs.__file__).read_text(encoding="utf-8")
    assert 'from .physical_handoff_floor import MINIMUM_PHYSICAL_HANDOFF_REVISION' in source
    assert '_require_current_fidelity_floor(bodyrig_revision, label="baseline body-build")' in source
    assert '_require_current_fidelity_floor(expected_revision, label="persisted high-fidelity preview")' in source
    assert '"comparison_only": True' in source
    assert '"human_review_required": True' in source
    assert '"production_activation": False' in source
