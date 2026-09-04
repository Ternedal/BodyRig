param(
    [ValidatePattern('^$|^job-[0-9a-f]{32}$')]
    [string]$JobId = "",

    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = $PSScriptRoot
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "BodyRig virtualenv Python not found: $python"
}

if ([string]::IsNullOrWhiteSpace($JobId)) {
    $dataRoot = [string]$env:BODYRIG_DATA_DIR
    if ([string]::IsNullOrWhiteSpace($dataRoot)) {
        if ([string]::IsNullOrWhiteSpace([string]$env:LOCALAPPDATA)) {
            throw "BODYRIG_DATA_DIR/LOCALAPPDATA is required to locate failed UI jobs."
        }
        $dataRoot = Join-Path $env:LOCALAPPDATA "BodyRig"
    }
    $jobsRoot = Join-Path ([System.IO.Path]::GetFullPath($dataRoot)) "ui-jobs"
    if (-not (Test-Path -LiteralPath $jobsRoot -PathType Container)) {
        throw "BodyRig UI job directory not found: $jobsRoot"
    }

    $failedJobs = @(
        Get-ChildItem -LiteralPath $jobsRoot -Directory -ErrorAction Stop |
            ForEach-Object {
                $jobPath = Join-Path $_.FullName "job.json"
                if (-not (Test-Path -LiteralPath $jobPath -PathType Leaf)) { return }
                try {
                    $job = Get-Content -LiteralPath $jobPath -Raw -Encoding UTF8 | ConvertFrom-Json
                } catch {
                    return
                }
                if ([string]$job.kind -ne "body-build") { return }
                if ([string]$job.status -notin @("failed", "interrupted", "canceled")) { return }
                [pscustomobject]@{
                    job_id = [string]$job.job_id
                    completed_utc = [string]$job.completed_utc
                    created_utc = [string]$job.created_utc
                }
            }
    )
    $latest = $failedJobs |
        Sort-Object -Property @{ Expression = { if ($_.completed_utc) { $_.completed_utc } else { $_.created_utc } }; Descending = $true } |
        Select-Object -First 1
    if ($null -eq $latest -or [string]::IsNullOrWhiteSpace([string]$latest.job_id)) {
        throw "No failed/interrupted BodyRig body-build job was found."
    }
    $JobId = [string]$latest.job_id
    Write-Host "BodyRig recovery rescue probe: latest failed body-build = $JobId"
}

& $python -m bodyrig.recovery_rescue_probe --job-id $JobId
exit $LASTEXITCODE
