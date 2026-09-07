param(
    [ValidatePattern('^$|^job-[0-9a-f]{32}$')]
    [string]$PreferredJobId = "",
    [string]$PerformerId = "",
    [ValidatePattern('^$|^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the BodyRig rig-window planner."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "BodyRig repo virtualenv is required before rig-window planning: $python"
}
$python = (Resolve-Path -LiteralPath $python).Path

$hasPerformer = -not [string]::IsNullOrWhiteSpace($PerformerId)
$hasBodyId = -not [string]::IsNullOrWhiteSpace($BodyId)
if ($hasPerformer -xor $hasBodyId) {
    throw "Pass -PerformerId and -BodyId together, or omit both."
}

$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not resolve exact BodyRig checkout revision."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
if ($dirty.Count -gt 0) {
    throw "BodyRig checkout is dirty. Rig-window planning refuses to authorize a physical next command."
}

$expectedModule = (Resolve-Path -LiteralPath (Join-Path $repoRoot "bodyrig\__init__.py")).Path
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $repoRoot
    $moduleRaw = @(& $python -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())")
    if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) {
        throw "BodyRig Python could not prove checkout-bound import authority."
    }
    $actualModule = (Resolve-Path -LiteralPath ([string]$moduleRaw[0]).Trim()).Path
    if (-not [string]::Equals($actualModule, $expectedModule, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "BodyRig Python imports bodyrig from unexpected location: $actualModule"
    }

    $dataRoot = [string]$env:BODYRIG_DATA_DIR
    if ([string]::IsNullOrWhiteSpace($dataRoot)) {
        if ([string]::IsNullOrWhiteSpace([string]$env:LOCALAPPDATA)) {
            throw "BODYRIG_DATA_DIR or LOCALAPPDATA is required for rig-window planning."
        }
        $dataRoot = Join-Path $env:LOCALAPPDATA "BodyRig"
    }
    $dataRoot = [System.IO.Path]::GetFullPath($dataRoot)

    $rejectedResume = @()
    $resumeCandidates = @()
    $jobsRoot = Join-Path $dataRoot "ui-jobs"
    if (Test-Path -LiteralPath $jobsRoot -PathType Container) {
        $rows = @(
            Get-ChildItem -LiteralPath $jobsRoot -Directory -ErrorAction Stop |
                ForEach-Object {
                    $jobPath = Join-Path $_.FullName "job.json"
                    if (-not (Test-Path -LiteralPath $jobPath -PathType Leaf)) { return }
                    try { $job = Get-Content -LiteralPath $jobPath -Raw -Encoding UTF8 | ConvertFrom-Json }
                    catch { return }
                    if ([string]$job.format -ne "bodyrig-ui-job" -or [string]$job.kind -ne "body-build") { return }
                    if ([string]$job.status -ne "failed") { return }
                    if ([string]$job.error -notlike "*high-fidelity Gate A failed*") { return }
                    [pscustomobject]@{
                        job_id = [string]$job.job_id
                        stamp = $(if ([string]$job.completed_utc) { [string]$job.completed_utc } else { [string]$job.created_utc })
                    }
                }
        )
        $resumeCandidates = @($rows | Sort-Object -Property stamp -Descending)
    }

    if (-not [string]::IsNullOrWhiteSpace($PreferredJobId)) {
        $preferred = @($resumeCandidates | Where-Object { $_.job_id -eq $PreferredJobId })
        $others = @($resumeCandidates | Where-Object { $_.job_id -ne $PreferredJobId })
        $resumeCandidates = @($preferred + $others)
    }

    foreach ($candidate in $resumeCandidates) {
        $assessmentRaw = @(& $python -m bodyrig.resume_body_job $candidate.job_id --assess-only 2>&1)
        $code = $LASTEXITCODE
        if ($code -eq 0) {
            try { $assessment = ($assessmentRaw -join "`n") | ConvertFrom-Json }
            catch { $assessment = $null }
            if ($null -ne $assessment -and $assessment.eligible -eq $true -and $assessment.persistent_mutation -eq $false) {
                $result = [ordered]@{
                    format = "bodyrig-rig-window-plan"
                    version = 1
                    read_only = $true
                    state = "ready"
                    priority = 1
                    path = "historical-gate-a-resume"
                    bodyrig_revision = $head
                    job_id = [string]$candidate.job_id
                    body_id = [string]$assessment.body_id
                    package_sha256 = [string]$assessment.package_sha256
                    recovery_rerun = $false
                    fitter_rerun = $false
                    rationale = "Reuse the already completed clone/recovery/fitter output first; only Gate A and downstream fidelity rendering need to run."
                    next_command = ".\resume-body-job.ps1 -JobId '$([string]$candidate.job_id)'"
                }
                if ($Json) { $result | ConvertTo-Json -Depth 5 -Compress }
                else {
                    Write-Host "BodyRig rig-window plan: READY | PRIORITY 1"
                    Write-Host "Path: historical Gate A resume"
                    Write-Host "Revision: $head"
                    Write-Host "Job: $([string]$candidate.job_id)"
                    Write-Host "Body: $([string]$assessment.body_id)"
                    Write-Host "Recovery rerun: false | fitter rerun: false"
                    Write-Host $result.rationale
                    Write-Host "Next command:"
                    Write-Host $result.next_command
                }
                exit 0
            }
        }
        $rejectedResume += [pscustomobject]@{
            job_id = [string]$candidate.job_id
            reason = (($assessmentRaw -join "`n").Trim())[-[Math]::Min((($assessmentRaw -join "`n").Trim()).Length), 1000)..-1] -join ""
        }
    }

    # If no cross-revision rescue is valid, prefer a completed physical session
    # from this exact checkout over a fresh reconstruction.
    $sessionsRoot = Join-Path $dataRoot "physical-clone-sessions"
    $sessionRows = @()
    if (Test-Path -LiteralPath $sessionsRoot -PathType Container) {
        $sessionRows = @(
            Get-ChildItem -LiteralPath $sessionsRoot -Filter "*.json" -File -ErrorAction Stop |
                Where-Object { $_.Name -notlike "*.readiness.json" } |
                ForEach-Object {
                    try { $session = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json }
                    catch { return }
                    if ([string]$session.format -ne "bodyrig-physical-clone-session" -or [int]$session.version -ne 1) { return }
                    if ([string]$session.status -ne "pass" -or [string]$session.stage -ne "complete") { return }
                    if ([string]$session.bodyrig_revision -ne $head) { return }
                    [pscustomobject]@{
                        path = $_.FullName
                        stamp = [string]$session.completed_utc
                    }
                } |
                Sort-Object -Property stamp -Descending
        )
    }

    $statusScript = Join-Path $repoRoot "physical-acceptance-status.ps1"
    foreach ($sessionRow in $sessionRows) {
        $statusRaw = @(& $statusScript -SessionReport $sessionRow.path -BodyRigPython $python -Json 2>&1)
        $statusCode = $LASTEXITCODE
        if ($statusCode -ne 0 -and $statusCode -ne 3) { continue }
        try { $status = ($statusRaw -join "`n") | ConvertFrom-Json }
        catch { continue }
        if ([string]$status.state -notin @("blocked", "error") -and -not [string]::IsNullOrWhiteSpace([string]$status.next_command)) {
            $result = [ordered]@{
                format = "bodyrig-rig-window-plan"
                version = 1
                read_only = $true
                state = "ready"
                priority = 2
                path = "existing-physical-session"
                bodyrig_revision = $head
                session_report = [string]$sessionRow.path
                gate = [string]$status.gate
                recovery_rerun = $false
                fitter_rerun = $false
                rationale = "Continue the exact completed physical session before spending rig time on a new reconstruction."
                next_command = [string]$status.next_command
            }
            if ($Json) { $result | ConvertTo-Json -Depth 5 -Compress }
            else {
                Write-Host "BodyRig rig-window plan: READY | PRIORITY 2"
                Write-Host "Path: existing physical session"
                Write-Host "Gate: $([string]$status.gate)"
                Write-Host "Revision: $head"
                Write-Host $result.rationale
                Write-Host "Next command:"
                Write-Host $result.next_command
            }
            exit 0
        }
    }

    $nextCommand = if ($hasPerformer -and $hasBodyId) {
        ".\bodyrig-status.ps1 -PerformerId '$($PerformerId.Replace("'", "''"))' -BodyId '$($BodyId.Replace("'", "''"))'"
    } else {
        ".\bodyrig-status.ps1"
    }
    $result = [ordered]@{
        format = "bodyrig-rig-window-plan"
        version = 1
        read_only = $true
        state = "ready"
        priority = 3
        path = "fresh-profiled-physical-preflight"
        bodyrig_revision = $head
        recovery_rerun = $true
        fitter_rerun = $true
        rejected_resume_count = $rejectedResume.Count
        rationale = "No reusable Gate-A rescue or current-revision completed physical session validated. Only now spend rig time on fresh profiled physical preflight/reconstruction."
        next_command = $nextCommand
    }
    if ($Json) { $result | ConvertTo-Json -Depth 5 -Compress }
    else {
        Write-Host "BodyRig rig-window plan: READY | PRIORITY 3"
        Write-Host "Path: fresh profiled physical preflight"
        Write-Host "Revision: $head"
        if ($rejectedResume.Count -gt 0) {
            Write-Host "Rejected historical Gate-A rescue candidates: $($rejectedResume.Count)"
        }
        Write-Host $result.rationale
        Write-Host "Next command:"
        Write-Host $result.next_command
    }
    exit 0
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
