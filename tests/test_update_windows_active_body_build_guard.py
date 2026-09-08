from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "update-windows.ps1").read_text(encoding="utf-8")


def test_verified_service_is_not_stopped_while_body_build_is_active() -> None:
    function_start = SCRIPT.index("function Stop-VerifiedBodyRigService")
    jobs_query = SCRIPT.index('Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8775/api/v1/jobs"', function_start)
    active_filter = SCRIPT.index('[string]$_.kind -eq "body-build"', jobs_query)
    refusal = SCRIPT.index('Refuserer at stoppe servicen; vent til de er terminale eller afbryd dem eksplicit først.', active_filter)
    stop_process = SCRIPT.index('Stop-Process -Id ([int]$ownerProcessId)', refusal)

    assert function_start < jobs_query < active_filter < refusal < stop_process
    assert '@("queued", "running", "cancelling")' in SCRIPT


def test_job_inspection_failure_is_fail_closed_before_service_stop() -> None:
    assert 'aktive jobs kunne ikke inspiceres' in SCRIPT
    assert 'Refuserer at stoppe servicen fail-closed' in SCRIPT
