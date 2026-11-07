"""Text contracts: the clone scripts record stage wall-clock without gaining authority.

The sidecar is informational. These contracts pin three things: every stage
wrapper still fails closed exactly as before (record first, then throw on a
non-zero exit code), recording can never raise (try/catch to a warning), and
the record shape the PowerShell emits is the one `bodyrig.stage_timing`
parses, so the reader and the writers cannot drift apart silently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bodyrig import stage_timing

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ("clone-body-from-stash-ready.ps1", "clone-body-from-stash.ps1", "clone-body.ps1")


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", SCRIPTS)
def test_writer_is_present_opt_in_and_never_throws(name: str) -> None:
    text = _text(name)
    assert text.count("function Write-StageTiming {") == 1
    body = text[text.index("function Write-StageTiming {") : text.index("\n}\n", text.index("function Write-StageTiming {")) + 3]
    assert '[Environment]::GetEnvironmentVariable("BODYRIG_STAGE_TIMING_LOG")' in body
    assert "if ([string]::IsNullOrWhiteSpace($timingLog)) { return }" in body
    assert body.index("try {") < body.index("Add-Content -LiteralPath $timingLog") < body.index("} catch {")
    assert "Write-Warning \"Stage timing not recorded for" in body
    assert "throw" not in body
    assert 'format = "bodyrig-stage-timing"' in body
    assert "version = 1" in body
    assert f'script = "{name}"' in body
    assert "ConvertTo-Json -Compress" in body


@pytest.mark.parametrize("name", SCRIPTS)
def test_record_fields_match_the_python_reader(name: str) -> None:
    text = _text(name)
    start = text.index("$record = [ordered]@{", text.index("function Write-StageTiming {"))
    end = text.index("}", start)
    keys = set(re.findall(r"^\s*([a-z_]+) = ", text[start:end], flags=re.MULTILINE))
    assert keys == stage_timing.RECORD_FIELDS


@pytest.mark.parametrize("name", ("clone-body-from-stash.ps1", "clone-body.ps1"))
def test_invoke_checked_records_then_still_fails_closed(name: str) -> None:
    text = _text(name)
    start = text.index("function Invoke-Checked {")
    body = text[start : text.index("\n}\n", start) + 3]
    run = body.index("& $Executable @Arguments")
    capture = body.index("$stageExitCode = $LASTEXITCODE", run)
    record = body.index("Write-StageTiming -Stage $Step -StartedUtc $stageStartedUtc", capture)
    gate = body.index("if ($stageExitCode -ne 0) {", record)
    raise_ = body.index('throw "$Step failed with exit code $stageExitCode"', gate)
    assert run < capture < record < gate < raise_
    assert "$stageStartedUtc = [DateTime]::UtcNow" in body
    assert body.index("$stageStartedUtc = [DateTime]::UtcNow") < run
    # The old direct $LASTEXITCODE gate is gone: a recording step in between
    # would otherwise clobber the exit code it is supposed to report on.
    assert "if ($LASTEXITCODE -ne 0) {" not in body


def test_launcher_names_the_sidecar_next_to_the_session_report_and_times_both_phases() -> None:
    text = _text("clone-body-from-stash-ready.ps1")
    resolved = text.index("$SessionReport = [System.IO.Path]::GetFullPath($SessionReport)")
    sidecar = text.index('$StageTimingLog = [System.IO.Path]::ChangeExtension($SessionReport, "timing.jsonl")', resolved)
    exported = text.index('[Environment]::SetEnvironmentVariable("BODYRIG_STAGE_TIMING_LOG", $StageTimingLog)', sidecar)
    session_start = text.index("Invoke-SessionCommand -Arguments @(")
    assert resolved < sidecar < exported < session_start

    readiness_run = text.index("& $powerShellExe @readinessArgs")
    readiness_code = text.index("$readinessExitCode = $LASTEXITCODE", readiness_run)
    readiness_record = text.index('Write-StageTiming -Stage "Live rig readiness"', readiness_code)
    readiness_gate = text.index("if ($readinessExitCode -ne 0) { throw \"BodyRig live rig readiness failed with exit code $readinessExitCode; clone not started.\" }", readiness_record)
    clone_run = text.index("& $powerShellExe @cloneArgs")
    clone_code = text.index("$cloneExitCode = $LASTEXITCODE", clone_run)
    clone_record = text.index('Write-StageTiming -Stage "Stash clone pipeline"', clone_code)
    clone_gate = text.index('if ($cloneExitCode -ne 0) { throw "BodyRig Stash clone failed with exit code $cloneExitCode" }', clone_record)
    assert readiness_run < readiness_code < readiness_record < readiness_gate < clone_run < clone_code < clone_record < clone_gate
    assert 'Write-Host "Stage timing: $StageTimingLog"' in text
    # The sidecar is not evidence: nothing hashes it, nothing binds it to the session.
    assert "Get-FileHash -Algorithm SHA256 -LiteralPath $StageTimingLog" not in text
    assert "--stage-timing" not in text


def test_session_report_schema_is_untouched() -> None:
    from bodyrig import physical_session

    assert "stage_timing" not in physical_session.FIELDS
    assert len(physical_session.FIELDS) == 15
    assert physical_session.VERSION == 1
