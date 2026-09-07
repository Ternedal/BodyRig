from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (ROOT / "plan-rig-window.ps1").read_text(encoding="utf-8")
CORE = (ROOT / "bodyrig" / "rig_window_plan.py").read_text(encoding="utf-8")
POLICY = (ROOT / "bodyrig" / "rig_window_policy.py").read_text(encoding="utf-8")
AUTHORITY = (ROOT / "bodyrig" / "rig_window_authority_policy.py").read_text(encoding="utf-8")
INTERRUPTED = (ROOT / "resume-interrupted-body-job.ps1").read_text(encoding="utf-8")


def test_rig_window_wrapper_requires_clean_checkout_bound_authority() -> None:
    assert "PowerShell 7+ (pwsh) is required" in WRAPPER
    assert "git -C $repoRoot rev-parse HEAD" in WRAPPER
    assert "git -C $repoRoot status --porcelain" in WRAPPER
    assert "BodyRig checkout is dirty" in WRAPPER
    assert "bodyrig.__file__" in WRAPPER
    assert "unexpected location" in WRAPPER
    assert '"-m", "bodyrig.rig_window_authority_policy"' in WRAPPER


def test_wrapper_exposes_explicit_person_scope() -> None:
    assert "[string]$PersonId" in WRAPPER
    assert "^person-[0-9a-f]{32}$" in WRAPPER
    assert '"--person-id", $PersonId' in WRAPPER
    assert '"--performer-id", $PerformerId' in WRAPPER
    assert '"--body-id", $BodyId' in WRAPPER


def test_unified_policy_scores_physical_progress_before_reconstruction() -> None:
    assert "RESCUE_RANK = 15" in POLICY
    assert "SESSION_RANK = 10" in POLICY
    assert "INTERRUPTED_ADOPT_RANK = 8" in POLICY
    assert "INTERRUPTED_FIT_RANK = 5" in POLICY
    assert "rank_physical_candidates(existing + rescues + interrupted)" in POLICY
    assert 'path="fresh-profiled-physical-preflight"' in POLICY
    assert "Only now spend rig time on fresh profiled physical preflight/reconstruction" in POLICY


def test_authority_layer_places_committed_gate_a_above_rescue_without_promoting_plain_session() -> None:
    assert "COMMITTED_GATE_A_RANK = 16" in AUTHORITY
    assert 'str(candidate.get("gate") or "") != "gate-a"' in AUTHORITY
    assert '"bodyrig-acceptance.json"' in AUTHORITY
    assert 'candidate["rank"] = max' in AUTHORITY
    assert "COMMITTED_GATE_A_RANK" in AUTHORITY


def test_complete_historical_evidence_requires_current_origin_main_ancestry_now() -> None:
    assert "def _strict_complete_historical_revision_is_safe" in AUTHORITY
    assert '"refs/remotes/origin/main^{commit}"' in AUTHORITY
    assert '"merge-base", "--is-ancestor"' in AUTHORITY
    assert 'str(candidate.get("state") or "") == "complete"' in AUTHORITY
    assert "complete historical evidence revision is not proven as an ancestor" in AUTHORITY


def test_person_scope_fails_closed_instead_of_cross_person_reuse() -> None:
    assert "def resolve_person_scope" in CORE
    assert "Multiple BodyRig Persons are bound to the requested Stash performer" in CORE
    assert "Rig-window evidence belongs to multiple BodyRig Persons" in CORE
    assert "pass -PersonId or -PerformerId" in CORE
    assert "def _scope_rows" in CORE
    assert '"scope": {' in CORE


def test_historical_session_switches_to_exact_revision_without_reconstruction() -> None:
    assert 'path="historical-physical-session-checkout"' in POLICY
    assert 'flag="-SessionReport"' in POLICY
    assert "update-windows.ps1 -Revision" in POLICY
    assert "Re-enter it instead of rerunning clone/reconstruction" in POLICY


def test_historical_acceptance_switches_to_exact_evidence_revision_before_new_compute() -> None:
    assert 'path="historical-acceptance-checkout"' in POLICY
    assert 'flag="-AcceptanceDir"' in POLICY
    assert "base._historical_revision_is_safe" in POLICY
    assert "re-enter its exact revision instead of recomputing" in POLICY


def test_planner_searches_both_ui_data_and_standalone_session_roots() -> None:
    assert "for sessions_root in base._session_roots(root)" in POLICY
    assert 'session.get("performer_id")' in POLICY
    assert 'session.get("body_id")' in POLICY
    assert 'session.get("bodyrig_revision")' in POLICY


def test_planner_keeps_gate_a_resume_candidate_after_failed_retry() -> None:
    assert '"resume_source_error": str(job.get("resume_source_error") or "")' in CORE
    assert '"high-fidelity Gate A failed" not in str(row.get("resume_source_error") or "")' in POLICY
    assert "base.assess_body_job_resume(job_id)" in POLICY


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


def test_unified_policy_only_assesses_and_emits_mutating_next_commands() -> None:
    assert 'f".\\\\resume-body-job.ps1 -JobId {base._ps_quote(job_id)}"' in POLICY
    assert 'f".\\\\resume-interrupted-body-job.ps1 -JobId {base._ps_quote(job_id)}"' in POLICY
    assert 'f".\\\\bodyrig-status.ps1 -PerformerId' in POLICY
    assert "base.assess_body_job_resume(job_id)" in POLICY
    assert "base._interrupted_assessment(repo_root, job_id)" in POLICY
    assert "start_body_resume" not in POLICY
    assert "clone-body-from-stash-ready.ps1" not in POLICY


def test_authority_shim_is_scoped_and_restores_legacy_policy_hook() -> None:
    assert "with _PATCH_LOCK" in AUTHORITY
    assert "previous = policy._existing_candidates" in AUTHORITY
    assert "policy._existing_candidates = _guarded_existing_candidates" in AUTHORITY
    assert "policy._existing_candidates = previous" in AUTHORITY
