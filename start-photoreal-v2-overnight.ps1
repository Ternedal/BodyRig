param(
    [string]$PerformerId = "42",
    [string]$RunRoot = "",
    [string]$ModelRoot = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$PathMap = "",
    [string]$BodyRigPython = "",
    [double]$EvalFraction = 0.20,
    [string]$SplitSeed = "bodyrig-photoreal-v2",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [string]$VisionDevice = "cuda:0",
    [switch]$AcceptInsightFaceResearchLicense,
    [switch]$RepairReferenceModels,
    [switch]$RepairReferenceEnvironment
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$entrypoint = Join-Path $repoRoot "start-photoreal-v2-reference.ps1"
if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) { throw "Photoreal V2 entrypoint not found: $entrypoint" }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required on Windows." }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if ([string]::IsNullOrWhiteSpace($RunRoot)) {
    $RunRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\overnight"
}
$RunRoot = [IO.Path]::GetFullPath($RunRoot)
[IO.Directory]::CreateDirectory($RunRoot) | Out-Null

$runDirectory = Join-Path $RunRoot ("performer-{0}-{1}" -f $PerformerId, $stamp)
$transcriptPath = Join-Path $RunRoot ("performer-{0}-{1}.log" -f $PerformerId, $stamp)
$summaryPath = Join-Path $RunRoot ("performer-{0}-{1}-summary.json" -f $PerformerId, $stamp)

$summary = [ordered]@{
    format = "bodyrig-photoreal-v2-overnight-summary"
    version = 1
    performer_id = $PerformerId
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    finished_at = $null
    output_root = $runDirectory
    transcript = $transcriptPath
    status = "running"
    exit_code = $null
    p0_status = (Join-Path $runDirectory "p0-status.json")
    production_activation = $false
}
$summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

$transcriptStarted = $false
$exitCode = 1
try {
    Start-Transcript -LiteralPath $transcriptPath -Force | Out-Null
    $transcriptStarted = $true

    Write-Host "BODYRIG PHOTOREAL V2 - OVERNIGHT P0"
    Write-Host "Performer: $PerformerId"
    Write-Host "Output:    $runDirectory"
    Write-Host "Log:       $transcriptPath"
    Write-Host "Summary:   $summaryPath"
    Write-Host ""

    $args = @{
        PerformerId = $PerformerId
        OutputRoot = $runDirectory
        ApiKeyEnv = $ApiKeyEnv
        EvalFraction = $EvalFraction
        SplitSeed = $SplitSeed
        Distribution = $Distribution
        LinuxPython = $LinuxPython
        VisionDevice = $VisionDevice
    }
    if (-not [string]::IsNullOrWhiteSpace($ModelRoot)) { $args.ModelRoot = $ModelRoot }
    if (-not [string]::IsNullOrWhiteSpace($StashUrl)) { $args.StashUrl = $StashUrl }
    if (-not [string]::IsNullOrWhiteSpace($PathMap)) { $args.PathMap = $PathMap }
    if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $args.BodyRigPython = $BodyRigPython }
    if ($AcceptInsightFaceResearchLicense) { $args.AcceptInsightFaceResearchLicense = $true }
    if ($RepairReferenceModels) { $args.RepairReferenceModels = $true }
    if ($RepairReferenceEnvironment) { $args.RepairReferenceEnvironment = $true }

    & $entrypoint @args
    if (-not $?) { throw "Photoreal V2 entrypoint returned failure." }
    $exitCode = 0
    $summary.status = "completed"
}
catch {
    $summary.status = "failed"
    $summary.error = $_.Exception.Message
    Write-Error $_
}
finally {
    $summary.finished_at = (Get-Date).ToUniversalTime().ToString("o")
    $summary.exit_code = $exitCode
    $summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}

Write-Host ""
Write-Host "Overnight run status: $($summary.status)"
Write-Host "Summary: $summaryPath"
Write-Host "P0 status: $($summary.p0_status)"
exit $exitCode
