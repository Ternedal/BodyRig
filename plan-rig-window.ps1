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
$interruptedResume = Join-Path $repoRoot "resume-interrupted-body-job.ps1"
if (-not (Test-Path -LiteralPath $interruptedResume -PathType Leaf)) {
    throw "BodyRig interrupted-recovery wrapper is missing: $interruptedResume"
}

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

    # UI jobs follow BODYRIG_DATA_DIR, but the canonical standalone physical
    # launcher intentionally writes default session reports under LOCALAPPDATA
    # (or the system temp root when LOCALAPPDATA is unavailable). Search both
    # authorities so a custom UI data root cannot hide reusable clone evidence.
    $artifactBase = [string]$env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($artifactBase)) {
        $artifactBase = [System.IO.Path]::GetTempPath()
    }
    $standaloneSessionRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $artifactBase "BodyRig\physical-clone-sessions")
    )
    $dataSessionRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $dataRoot "physical-clone-sessions")
    )
    $sessionRoots = @($standaloneSessionRoot, $dataSessionRoot) | Select-Object -Unique

    $rejectedResume = @()
    $rejectedInterrupted = @()
    $jobRows = @()
    $resumeCandidates = @()
    $acceptanceCandidates = @()
    $jobsRoot = Join-Path $dataRoot "ui-jobs"
    if (Test-Path -LiteralPath $jobsRoot -PathType Container) {
        $jobRows = @(
            Get-ChildItem -LiteralPath $jobsRoot -Directory -ErrorAction Stop |
                ForEach-Object {
                    $jobPath = Join-Path $_.FullName "job.json"
                    if (-not (Test-Path -LiteralPath $jobPath -PathType Leaf)) { return }
                    try { $job = Get-Content -LiteralPath $jobPath -Raw -Encoding UTF8 | ConvertFrom-Json }
                    catch { return }
                    if ([string]$job.format -ne "bodyrig-ui-job" -or [string]$job.kind -ne "body-build") { return }
                    $resumeSourceError = ""
                    $resumeSourceErrorProperty = $job.PSObject.Properties["resume_source_error"]
                    if ($null -ne $resumeSourceErrorProperty) {
                        $resumeSourceError = [string]$resumeSourceErrorProperty.Value
                    }
                    [pscustomobject]@{
                        job_id = [string]$job.job_id
                        status = [string]$job.status
                        error = [string]$job.error
                        resume_source_error = $resumeSourceError
                        acceptance_dir = [string]$job.acceptance_dir
                        stamp = $(if ([string]$job.completed_utc) { [string]$job.completed_utc } else { [string]$job.created_utc })
                    }
                }
        )
        $resumeCandidates = @(
            $jobRows |
                Where-Object {
                    $_.status -eq "failed" -and (
                        $_.error -like "*high-fidelity Gate A failed*" -or
                        $_.resume_source_error -like "*high-fidelity Gate A failed*"
                    )
                } |
                Sort-Object -Property stamp -Descending
        )
        $acceptanceCandidates = @(
            $jobRows |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_.acceptance_dir) } |
                Sort-Object -Property stamp -Descending
        )
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
                    expensive_reconstruction_rerun = $false
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
                    Write-Host "Expensive reconstruction rerun: false | fitter rerun: false"
                    Write-Host $result.rationale
                    Write-Host "Next command:"
                    Write-Host $result.next_command
                }
                exit 0
            }
        }
        $rejectedResume += [pscustomobject]@{
            job_id = [string]$candidate.job_id
            reason = ($assessmentRaw -join "`n").Trim()
        }
    }

    $statusScript = Join-Path $repoRoot "physical-acceptance-status.ps1"

    foreach ($candidate in $acceptanceCandidates) {
        if (-not (Test-Path -LiteralPath $candidate.acceptance_dir -PathType Container)) { continue }
        if (-not (Test-Path -LiteralPath (Join-Path $candidate.acceptance_dir "bodyrig-acceptance.json") -PathType Leaf)) { continue }
        $statusRaw = @(& $statusScript -AcceptanceDir $candidate.acceptance_dir -BodyRigPython $python -Json 2>&1)
        $statusCode = $LASTEXITCODE
        if ($statusCode -ne 0 -and $statusCode -ne 3) { continue }
        try { $status = ($statusRaw -join "`n") | ConvertFrom-Json }
        catch { continue }
        if ([string]$status.state -eq "complete") {
            $result = [ordered]@{
                format = "bodyrig-rig-window-plan"
                version = 1
                read_only = $true
                state = "complete"
                priority = 2
                path = "existing-gate-a-acceptance"
                bodyrig_revision = $head
                acceptance_dir = [string]$candidate.acceptance_dir
                gate = [string]$status.gate
                expensive_reconstruction_rerun = $false
                fitter_rerun = $false
                rationale = "This physical body acceptance chain is already complete. Do not start a fresh reconstruction for this body."
                next_command = $null
            }
            if ($Json) { $result | ConvertTo-Json -Depth 5 -Compress }
            else {
                Write-Host "BodyRig rig-window plan: COMPLETE | PRIORITY 2"
                Write-Host "Path: existing Gate A acceptance"
                Write-Host "Acceptance: $([string]$candidate.acceptance_dir)"
                Write-Host $result.rationale
            }
            exit 0
        }

        # A valid historical Gate-A acceptance is farther downstream than any
        # new reconstruction. If current operator code is the only blocker,
        # switch to the exact accepted ancestor revision and ask that revision's
        # own status engine for the next physical command.
        if ([string]$status.state -eq "blocked" -and [string]$status.gate -eq "operator-checkout") {
            $evidenceRevision = ([string]$status.bodyrig_revision).Trim().ToLowerInvariant()
            if ($evidenceRevision -match '^[0-9a-f]{40}$' -and $evidenceRevision -ne $head) {
                $escapedAcceptance = ([string]$candidate.acceptance_dir).Replace("'", "''")
                $result = [ordered]@{
                    format = "bodyrig-rig-window-plan"
                    version = 1
                    read_only = $true
                    state = "ready"
                    priority = 2
                    path = "historical-acceptance-checkout"
                    bodyrig_revision = $head
                    evidence_revision = $evidenceRevision
                    acceptance_dir = [string]$candidate.acceptance_dir
                    gate = "operator-checkout"
                    expensive_reconstruction_rerun = $false
                    fitter_rerun = $false
                    rationale = "A valid downstream physical acceptance exists on an older exact BodyRig revision. Re-enter that accepted revision before spending rig time on any new reconstruction."
                    next_command = "& .\update-windows.ps1 -Revision '$evidenceRevision' -NoBrowser; if (`$?) { & .\physical-acceptance-status.ps1 -AcceptanceDir '$escapedAcceptance' }"
                }
                if ($Json) { $result | ConvertTo-Json -Depth 5 -Compress }
                else {
                    Write-Host "BodyRig rig-window plan: READY | PRIORITY 2"
                    Write-Host "Path: historical acceptance exact checkout"
                    Write-Host "Current revision: $head"
                    Write-Host "Evidence revision: $evidenceRevision"
                    Write-Host "Acceptance: $([string]$candidate.acceptance_dir)"
                    Write-Host "Expensive reconstruction rerun: false | fitter rerun: false"
                    Write-Host $result.rationale
                    Write-Host "Next command:"
                    Write-Host $result.next_command
                }
                exit 0
            }
        }

        if ([string]$status.state -notin @("blocked", "error") -and -not [string]::IsNullOrWhiteSpace([string]$status.next_command)) {
            $result = [ordered]@{
                format = "bodyrig-rig-window-plan"
                version = 1
                read_only = $true
                state = "ready"
                priority = 2
                path = "existing-gate-a-acceptance"
                bodyrig_revision = $head
                acceptance_dir = [string]$candidate.acceptance_dir
                gate = [string]$status.gate
                expensive_reconstruction_rerun = $false
                fitter_rerun = $false
                rationale = "Continue the existing Gate A acceptance chain before spending rig time on a new clone/reconstruction."
                next_command = [string]$status.next_command
            }
            if ($Json) { $result | ConvertTo-Json -Depth 5 -Compress }
            else {
                Write-Host "BodyRig rig-window plan: READY | PRIORITY 2"
                Write-Host "Path: existing Gate A acceptance"
                Write-Host "Gate: $([string]$status.gate)"
                Write-Host "Revision: $head"
                Write-Host $result.rationale
                Write-Host "Next command:"
                Write-Host $result.next_command
            }
            exit 0
        }
    }

    $sessionRows = @(
        foreach ($sessionsRoot in $sessionRoots) {
            if (-not (Test-Path -LiteralPath $sessionsRoot -PathType Container)) { continue }
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
                }
        }
    ) | Sort-Object -Property stamp -Descending

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
                priority = 3
                path = "existing-physical-session"
                bodyrig_revision = $head
                session_report = [string]$sessionRow.path
                gate = [string]$status.gate
                expensive_reconstruction_rerun = $false
                fitter_rerun = $false
                rationale = "Continue the exact completed physical session before spending rig time on a new reconstruction."
                next_command = [string]$status.next_command
            }
            if ($Json) { $result | ConvertTo-Json -Depth 5 -Compress }
            else {
                Write-Host "BodyRig rig-window plan: READY | PRIORITY 3"
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

    # Reuse a retained completed package or completed SiTH reconstruction from
    # an interrupted/failed exact-current body job before allowing a new PHALP/
    # SiTH reconstruction. The existing BodyRig service owns this recovery plan.
    $interruptedCandidates = @(
        $jobRows |
            Where-Object { $_.status -in @("failed", "interrupted") -and $_.job_id -match '^job-[0-9a-f]{32}$' } |
            Sort-Object -Property stamp -Descending
    )
    if (-not [string]::IsNullOrWhiteSpace($PreferredJobId)) {
        $preferredInterrupted = @($interruptedCandidates | Where-Object { $_.job_id -eq $PreferredJobId })
        $otherInterrupted = @($interruptedCandidates | Where-Object { $_.job_id -ne $PreferredJobId })
        $interruptedCandidates = @($preferredInterrupted + $otherInterrupted)
    }
    foreach ($candidate in $interruptedCandidates) {
        $assessmentRaw = @(& $interruptedResume -JobId $candidate.job_id -AssessOnly 2>&1)
        $code = $LASTEXITCODE
        if ($code -eq 0) {
            try { $assessment = ($assessmentRaw -join "`n") | ConvertFrom-Json }
            catch { $assessment = $null }
            if ($null -ne $assessment -and $assessment.available -eq $true -and $assessment.expensive_reconstruction_rerun -eq $false) {
                $fitterRerun = [bool]$assessment.fitter_rerun
                $result = [ordered]@{
                    format = "bodyrig-rig-window-plan"
                    version = 1
                    read_only = $true
                    state = "ready"
                    priority = 4
                    path = "interrupted-body-recovery"
                    bodyrig_revision = $head
                    job_id = [string]$candidate.job_id
                    recovery_mode = [string]$assessment.recovery_mode
                    reconstruction_sha256 = [string]$assessment.reconstruction_sha256
                    package_sha256 = [string]$assessment.package_sha256
                    expensive_reconstruction_rerun = $false
                    fitter_rerun = $fitterRerun
                    rationale = [string]$assessment.reason
                    next_command = ".\resume-interrupted-body-job.ps1 -JobId '$([string]$candidate.job_id)'"
                }
                if ($Json) { $result | ConvertTo-Json -Depth 5 -Compress }
                else {
                    Write-Host "BodyRig rig-window plan: READY | PRIORITY 4"
                    Write-Host "Path: interrupted body recovery"
                    Write-Host "Revision: $head"
                    Write-Host "Job: $([string]$candidate.job_id)"
                    Write-Host "Recovery mode: $([string]$assessment.recovery_mode)"
                    Write-Host "Expensive reconstruction rerun: false | fitter rerun: $fitterRerun"
                    Write-Host $result.rationale
                    Write-Host "Next command:"
                    Write-Host $result.next_command
                }
                exit 0
            }
        }
        $rejectedInterrupted += [pscustomobject]@{
            job_id = [string]$candidate.job_id
            reason = ($assessmentRaw -join "`n").Trim()
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
        priority = 5
        path = "fresh-profiled-physical-preflight"
        bodyrig_revision = $head
        expensive_reconstruction_rerun = $true
        fitter_rerun = $true
        rejected_gate_a_resume_count = $rejectedResume.Count
        rejected_interrupted_recovery_count = $rejectedInterrupted.Count
        rationale = "No reusable Gate-A rescue, Gate-A continuation, completed physical session or interrupted reconstruction/package recovery validated. Only now spend rig time on fresh profiled physical preflight/reconstruction."
        next_command = $nextCommand
    }
    if ($Json) { $result | ConvertTo-Json -Depth 5 -Compress }
    else {
        Write-Host "BodyRig rig-window plan: READY | PRIORITY 5"
        Write-Host "Path: fresh profiled physical preflight"
        Write-Host "Revision: $head"
        if ($rejectedResume.Count -gt 0) {
            Write-Host "Rejected historical Gate-A rescue candidates: $($rejectedResume.Count)"
        }
        if ($rejectedInterrupted.Count -gt 0) {
            Write-Host "Rejected interrupted recovery candidates: $($rejectedInterrupted.Count)"
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
