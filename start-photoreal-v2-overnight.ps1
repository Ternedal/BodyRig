param(
    [string]$PerformerId = "42",
    [string]$RunRoot = "",
    [string]$ModelRoot = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$PathMap = "",
    [string]$ProjectionAuthority = "",
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

function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 }
    catch { throw "$Label is unreadable JSON: $Path" }
}

function Test-NumericV1 {
    param([AllowNull()]$Value)
    if ($null -eq $Value -or $Value -is [bool]) { return $false }
    try { $typeCode = [Type]::GetTypeCode($Value.GetType()) } catch { return $false }
    $numericTypes = @([TypeCode]::Byte,[TypeCode]::Decimal,[TypeCode]::Double,[TypeCode]::Int16,[TypeCode]::Int32,[TypeCode]::Int64,[TypeCode]::SByte,[TypeCode]::Single,[TypeCode]::UInt16,[TypeCode]::UInt32,[TypeCode]::UInt64)
    if ($numericTypes -notcontains $typeCode) { return $false }
    $number = [double]$Value
    return (-not [double]::IsNaN($number)) -and (-not [double]::IsInfinity($number)) -and $number -eq 1.0
}

function Test-StrictBoolean {
    param([AllowNull()]$Value,[Parameter(Mandatory = $true)][bool]$Expected)
    return ($Value -is [bool]) -and ([bool]$Value -eq $Expected)
}

function Read-AuthorizedP0Status {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedPerformerId
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Photoreal P0 returned success without p0-status.json: $Path"
    }
    $status = Read-Json -Path $Path -Label "Photoreal P0 status"
    if ([string]$status.format -ne "bodyrig-photoreal-p0-status" -or -not (Test-NumericV1 -Value $status.version)) {
        throw "Photoreal P0 success status format/version mismatch."
    }
    if ([string]$status.performer_id -ne $ExpectedPerformerId) {
        throw "Photoreal P0 success status performer mismatch."
    }
    if ([string]$status.bodyrig_revision -notmatch '^[0-9a-f]{40}$') {
        throw "Photoreal P0 success status has invalid BodyRig revision."
    }
    if ([string]$status.status -ne "teacher-training-authorized") {
        throw "Photoreal P0 exit 0 did not persist canonical teacher-training-authorized status."
    }
    if (-not (Test-StrictBoolean -Value $status.teacher_training_authorized -Expected $true)) {
        throw "Photoreal P0 exit 0 did not persist teacher-training authority."
    }
    if (@($status.blockers).Count -ne 0) {
        throw "Photoreal P0 success status contains blockers."
    }
    if (-not (Test-StrictBoolean -Value $status.human_visual_acceptance_required -Expected $true)) {
        throw "Photoreal P0 success status crossed the required human visual acceptance boundary."
    }
    if (-not (Test-StrictBoolean -Value $status.photoreal_acceptance_authority -Expected $false)) {
        throw "Photoreal P0 success status crossed photoreal acceptance authority."
    }
    if (-not (Test-StrictBoolean -Value $status.production_activation -Expected $false)) {
        throw "Photoreal P0 success status crossed production activation authority."
    }
    return $status
}

function Restore-SavedStashCredential {
    param(
        [Parameter(Mandatory = $true)][string]$EnvironmentName,
        [string]$RequestedUrl = ""
    )
    if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($EnvironmentName, "Process"))) {
        return $null
    }
    if ($EnvironmentName -ne "STASH_API_KEY") {
        return $null
    }
    $configPath = Join-Path $env:LOCALAPPDATA "BodyRig\config\stash.json"
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        return $null
    }
    $config = Read-Json -Path $configPath -Label "Saved Stash config"
    if ([string]$config.format -ne "bodyrig-local-stash-config" -or -not (Test-NumericV1 -Value $config.version)) {
        throw "Saved Stash config has an unexpected format/version: $configPath"
    }
    $savedUrl = ([string]$config.url).Trim()
    if ([string]::IsNullOrWhiteSpace($savedUrl) -or [string]::IsNullOrWhiteSpace([string]$config.api_key_dpapi)) {
        throw "Saved Stash config lacks URL or protected API key: $configPath"
    }
    if (-not [string]::IsNullOrWhiteSpace($RequestedUrl) -and -not [string]::Equals($RequestedUrl.Trim(), $savedUrl, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Saved Stash config URL '$savedUrl' does not match requested Stash URL '$RequestedUrl'."
    }

    $secure = ConvertTo-SecureString ([string]$config.api_key_dpapi)
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        if ([string]::IsNullOrWhiteSpace($apiKey)) {
            throw "Saved Stash API key could not be decrypted for this Windows user."
        }
        [Environment]::SetEnvironmentVariable($EnvironmentName, $apiKey, "Process")
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    return $savedUrl
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$entrypoint = Join-Path $repoRoot "start-photoreal-v2-reference.ps1"
if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) { throw "Photoreal V2 entrypoint not found: $entrypoint" }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required on Windows." }

$projectionAuthorityEnv = "BODYRIG_PHOTOREAL_PROJECTION_AUTHORITY"
$projectionAuthorityWasExplicit = -not [string]::IsNullOrWhiteSpace($ProjectionAuthority)
if ($projectionAuthorityWasExplicit) {
    if (-not (Test-Path -LiteralPath $ProjectionAuthority -PathType Leaf)) {
        throw "Photoreal projection authority not found: $ProjectionAuthority"
    }
    $ProjectionAuthority = (Resolve-Path -LiteralPath $ProjectionAuthority).Path
}
$originalProjectionAuthority = [Environment]::GetEnvironmentVariable($projectionAuthorityEnv, "Process")

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if ([string]::IsNullOrWhiteSpace($RunRoot)) {
    $RunRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\overnight"
}
$RunRoot = [IO.Path]::GetFullPath($RunRoot)
[IO.Directory]::CreateDirectory($RunRoot) | Out-Null

$runDirectory = Join-Path $RunRoot ("performer-{0}-{1}" -f $PerformerId, $stamp)
$transcriptPath = Join-Path $RunRoot ("performer-{0}-{1}.log" -f $PerformerId, $stamp)
$summaryPath = Join-Path $RunRoot ("performer-{0}-{1}-summary.json" -f $PerformerId, $stamp)
$p0StatusPath = Join-Path $runDirectory "p0-status.json"

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
    p0_status = $p0StatusPath
    p0_status_sha256 = $null
    bodyrig_revision = $null
    teacher_training_authorized = $false
    human_visual_acceptance_required = $true
    photoreal_acceptance_authority = $false
    production_activation = $false
}
$summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

$transcriptStarted = $false
$exitCode = 1
$originalApiKey = [Environment]::GetEnvironmentVariable($ApiKeyEnv, "Process")
$restoredSavedCredential = $false
try {
    Start-Transcript -LiteralPath $transcriptPath -Force | Out-Null
    $transcriptStarted = $true

    Write-Host "BODYRIG PHOTOREAL V2 - OVERNIGHT P0"
    Write-Host "Performer: $PerformerId"
    Write-Host "Output:    $runDirectory"
    Write-Host "Log:       $transcriptPath"
    Write-Host "Summary:   $summaryPath"
    if ($projectionAuthorityWasExplicit) { Write-Host "Projection authority: $ProjectionAuthority" }
    Write-Host ""

    $savedStashUrl = Restore-SavedStashCredential -EnvironmentName $ApiKeyEnv -RequestedUrl $StashUrl
    if (-not [string]::IsNullOrWhiteSpace([string]$savedStashUrl)) {
        $restoredSavedCredential = $true
        if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = [string]$savedStashUrl }
        Write-Host "Stash auth: restored from saved DPAPI config"
    }

    if ($projectionAuthorityWasExplicit) {
        [Environment]::SetEnvironmentVariable($projectionAuthorityEnv, $ProjectionAuthority, "Process")
    }

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
    $entrypointExit = $LASTEXITCODE
    if (-not $? -or $entrypointExit -ne 0) {
        throw "Photoreal V2 entrypoint returned failure (exit $entrypointExit)."
    }

    $p0Status = Read-AuthorizedP0Status -Path $p0StatusPath -ExpectedPerformerId $PerformerId
    $statusHash = (Get-FileHash -LiteralPath $p0StatusPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($statusHash -notmatch '^[0-9a-f]{64}$') { throw "Could not bind Photoreal P0 status digest." }

    $summary.p0_status_sha256 = $statusHash
    $summary.bodyrig_revision = [string]$p0Status.bodyrig_revision
    $summary.teacher_training_authorized = $true
    $exitCode = 0
    $summary.status = "completed"
}
catch {
    $summary.status = "failed"
    $summary.error = $_.Exception.Message
}
finally {
    if ($projectionAuthorityWasExplicit) {
        [Environment]::SetEnvironmentVariable($projectionAuthorityEnv, $originalProjectionAuthority, "Process")
    }
    if ($restoredSavedCredential) {
        [Environment]::SetEnvironmentVariable($ApiKeyEnv, $originalApiKey, "Process")
    }
    $summary.finished_at = (Get-Date).ToUniversalTime().ToString("o")
    $summary.exit_code = $exitCode
    $summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}

Write-Host ""
Write-Host "Overnight run status: $($summary.status)"
if ($summary.status -eq "failed" -and -not [string]::IsNullOrWhiteSpace([string]$summary.error)) {
    Write-Host "Error: $($summary.error)"
}
Write-Host "Summary: $summaryPath"
Write-Host "P0 status: $($summary.p0_status)"
exit $exitCode
