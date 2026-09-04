from __future__ import annotations

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "bodyrig" / "ui" / "body_job_progress.js").read_text(encoding="utf-8")


def test_failure_summary_prefers_innermost_fail_marker_from_diagnostic_tail() -> None:
    assert 'line.lastIndexOf("FAIL:")' in SCRIPT
    assert 'line.slice(failIndex + 5).trim()' in SCRIPT
    assert 'job?.diagnostic_tail' in SCRIPT


def test_failure_summary_strips_ansi_and_retained_staging_path_from_operator_summary() -> None:
    assert "function stripAnsi" in SCRIPT
    assert "staging retained:" in SCRIPT
    assert "candidate.replace" in SCRIPT
    assert "diagnostic.textContent = stripAnsi(tail)" in SCRIPT


def test_concrete_failure_replaces_generic_persisted_error_in_latest_body_build_card() -> None:
    assert 'document.getElementById("bodyJobDetail")' in SCRIPT
    assert 'line.startsWith("Fejl:")' in SCRIPT
    assert 'const value = `Fejl: ${summary}`' in SCRIPT
    assert "replacePersistedError(job, failure)" in SCRIPT


def test_full_diagnostic_tail_remains_visible_after_summary_extraction() -> None:
    assert 'document.getElementById("bodyJobDiagnosticTail")' in SCRIPT
    assert 'if (FAILURE.has(job.status) && tail)' in SCRIPT
    assert 'diagnostic.classList.remove("hidden")' in SCRIPT


def test_long_recovery_phase_does_not_claim_sith_has_already_started() -> None:
    assert 'job?.stage === "high_fidelity_reconstruction"' in SCRIPT
    assert "Recovery/identity/high-fidelity pipeline kører" in SCRIPT
    assert "PHALP/4D-Humans" in SCRIPT
    assert "Do not pretend that observation evidence means SiTH has" in SCRIPT
