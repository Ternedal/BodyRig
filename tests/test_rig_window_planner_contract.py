from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (ROOT / "plan-rig-window.ps1").read_text(encoding="utf-8")
CORE = (ROOT / "bodyrig" / "rig_window_plan.py").read_text(encoding="utf-8")
INTERRUPTED = (ROOT / "resume-interrupted-body-job.ps1").read_text(encoding="utf-8")


def test_rig_window_wrapper_requires_clean_checkout_bound_authority() -> None:
    assert "PowerShell 7+ (pwsh) is required" in WRAPPER
    assert "git -C $repoRoot rev-parse HEAD" in WRAPPER
    assert "git -C $repoRoot status --porcelain" in WRAPPER
    assert "BodyRig checkout is dirty" in WRAPPER
    assert "bodyrig.__file__" in WRAPPER
    assert "unexpected location" in WRAPPER
    assert '"-m", "bodyrig.rig_window_plan"' in WRAPPER


def test_wrapper_exposes_explicit_person_scope() -> None:
    assert "[string]$PersonId" in WRAPPER
    assert "^person-[0-9a-f]{32}$" in WRAPPER
    assert '"--person-id", $PersonId' in WRAPPER
    assert '"--performer-id", $PerformerId' in WRAPPER
    assert '"--body-id", $BodyId' in WRAPPER


def test_rig_window_priority_is_reuse_before_reconstruction() -> None:
    rescue = CORE.index('path="historical-gate-a-resume"')
    acceptance = CORE.index('path="existing-gate-a-acceptance"')
    historical = CORE.index('path="historical-acceptance-checkout"')
    existing = CORE.index('path="existing-physical-session"')
    interrupted = CORE.index('path="interrupted-body-recovery"')
    fresh = CORE.index('path="fresh-profiled-physical-preflight"')

    assert rescue < acceptance < historical < existing < interrupted < fresh
    assert "assess_body_job_resume(job_id_value)" in CORE
    assert 'wrapper = repo_root / "resume-interrupted-body-job.ps1"' in CORE
    assert '"-AssessOnly"' in CORE
    assert '"expensive_reconstruction_rerun": False' in CORE
    assert '"expensive_reconstruction_rerun": True' in CORE
    assert "furthest valid physical body acceptance chain" in CORE


def test_person_scope_fails_closed_instead_of_cross_person_reuse() -> None:
    assert "def resolve_person_scope" in CORE
    assert "Multiple BodyRig Persons are bound to the requested Stash performer" in CORE
    assert "Rig-window evidence belongs to multiple BodyRig Persons" in CORE
    assert "pass -PersonId or -PerformerId" in CORE
    assert "def _scope_rows" in CORE
    assert "return []" in CORE
    assert '"scope": {' in CORE


def test_standalone_session_reuse_is_scoped_when_identity_is_explicit() -> None:
    assert "def _scoped_completed_sessions" in CORE
    assert "explicit_performer_id and body_id" in CORE
    assert "performer_id=explicit_performer_id" in CORE
    assert "body_id=body_id" in CORE
    assert "only reuse when that leaves exactly one" in CORE


def test_historical_acceptance_switches_to_exact_evidence_revision_before_new_compute() -> None:
    assert "_historical_revision_is_safe" in CORE
    assert 'path="historical-acceptance-checkout"' in CORE
    assert "-Revision {_ps_quote(evidence_revision)} -NoBrowser" in CORE
    assert "physical-acceptance-status.ps1 -AcceptanceDir" in CORE
    assert "Re-enter it before spending rig time on an earlier stage" in CORE


def test_planner_searches_both_ui_data_and_standalone_session_roots() -> None:
    assert 'os.environ.get("LOCALAPPDATA")' in CORE
    assert '"BodyRig" / "physical-clone-sessions"' in CORE
    assert 'root / "physical-clone-sessions"' in CORE
    assert "def _session_roots" in CORE
    assert "for sessions_root in _session_roots(root)" in CORE


def test_planner_keeps_gate_a_resume_candidate_after_failed_retry() -> None:
    assert '"resume_source_error": str(job.get("resume_source_error") or "")' in CORE
    assert '"high-fidelity Gate A failed" in row["resume_source_error"]' in CORE


def test_interrupted_recovery_wrapper_uses_existing_bodyrig_service_authority() -> None:
    assert "$PSVersionTable.PSVersion.Major -lt 7" in INTERRUPTED
    assert "git -C $repoRoot rev-parse HEAD" in INTERRUPTED
    assert "git -C $repoRoot status --porcelain" in INTERRUPTED
    assert 'Invoke-RestMethod -Method Get -Uri "$baseUri/api/v1/health"' in INTERRUPTED
    assert '$health.PSObject.Properties["bodyrig_revision"]' in INTERRUPTED
    assert '"$baseUri/api/v1/jobs/$JobId/resume-status"' in INTERRUPTED
    assert '"$baseUri/api/v1/jobs/$JobId/resume"' in INTERRUPTED
    assert "$status.expensive_reconstruction_rerun -ne $false" in INTERRUPTED
    assert "$status.bodyrig_revision -ne $head" in INTERRUPTED
    assert "[switch]$AssessOnly" in INTERRUPTED


def test_python_planner_only_assesses_and_emits_mutating_next_commands() -> None:
    assert 'f".\\\\resume-body-job.ps1 -JobId {_ps_quote(job_id_value)}"' in CORE
    assert 'f".\\\\resume-interrupted-body-job.ps1 -JobId {_ps_quote(row[\'job_id\'])}"' in CORE
    assert 'f".\\\\bodyrig-status.ps1 -PerformerId' in CORE
    assert '"-AssessOnly"' in CORE
    assert "assess_body_job_resume(job_id_value)" in CORE
    assert "start_body_resume" not in CORE
    assert "resume_body_job(job_id_value)" not in CORE
    assert "clone-body-from-stash-ready.ps1" not in CORE
