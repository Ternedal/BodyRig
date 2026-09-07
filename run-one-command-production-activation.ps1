param(
    [Parameter(Mandatory = $true)][string]$PerformerId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9æøå_-]{1,160}$')][string]$BodyId,
    [string]$Name = "",
    [string]$RigSetupReport = "",
    [string]$BodyRigPython = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$WslExe = "wsl.exe",
    [ValidateRange(1, 10)][int]$MaxSources = 10,
    [ValidateRange(1, 1000)][int]$SceneLimit = 200,
    [ValidateRange(1, 10)][int]$MaxSegments = 10,
    [string]$TrackId = "",
    [string]$Ffmpeg = "",
    [ValidateRange(0, 2147483647)][int]$SithSeed = 1337,
    [string]$UnityExe = "",
    [string]$AdbExe = "",
    [string]$Serial = "",
    [string]$RunRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig one-command production activation is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required."
}
if ($null -eq (Get-Command pwsh -ErrorAction SilentlyContinue)) {
    throw "PowerShell 7 executable (pwsh) was not found."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout cleanliness." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; production activation requires an exact clean checkout." }

& git -C $repoRoot fetch --quiet origin main
if ($LASTEXITCODE -ne 0) { throw "Could not refresh origin/main authority." }
$head = ([string](& git -C $repoRoot rev-parse HEAD)).Trim().ToLowerInvariant()
$originMain = ([string](& git -C $repoRoot rev-parse origin/main)).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$' -or $originMain -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve canonical BodyRig Git authority."
}
if ($head -ne $originMain) {
    throw "Checkout is not exact current origin/main. HEAD=$head origin/main=$originMain"
}

$artifactBase = [string]$env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($artifactBase)) { $artifactBase = [IO.Path]::GetTempPath() }
if ([string]::IsNullOrWhiteSpace($RunRoot)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $RunRoot = Join-Path $artifactBase "BodyRig\automatic-production\$BodyId-$stamp-$suffix"
}
$RunRoot = [IO.Path]::GetFullPath($RunRoot)
if (Test-Path -LiteralPath $RunRoot) { throw "RunRoot already exists; refusing cross-attempt reuse: $RunRoot" }
New-Item -ItemType Directory -Path $RunRoot | Out-Null

$cloneOutput = Join-Path $RunRoot "clone-output"
$sessionReport = Join-Path $RunRoot "bodyrig-physical-clone-session.json"
$acceptanceDir = Join-Path $cloneOutput "acceptance"
$finalReceipt = Join-Path $acceptanceDir "bodyrig-release-acceptance.json"
$runAuthority = Join-Path $RunRoot "run-authority.json"

$authority = [ordered]@{
    format = "bodyrig-one-command-production-authority"
    version = 1
    started_at = [DateTime]::UtcNow.ToString("o")
    bodyrig_revision = $head
    performer_id = $PerformerId
    requested_body_alias = $BodyId
    session_report = $sessionReport
    clone_output = $cloneOutput
    acceptance_dir = $acceptanceDir
    production_activation = $false
}
$authority | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runAuthority -Encoding UTF8

$cloneScript = Join-Path $repoRoot "clone-body-from-stash-ready.ps1"
$acceptScript = Join-Path $repoRoot "accept-physical-clone.ps1"
$activateScript = Join-Path $repoRoot "run-automatic-production-activation.ps1"
foreach ($script in @($cloneScript, $acceptScript, $activateScript)) {
    if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { throw "Required production script missing: $script" }
}

Write-Host "BodyRig one-command production activation"
Write-Host "Revision: $head"
Write-Host "Run root: $RunRoot"
Write-Host "Performer: $PerformerId"
Write-Host "Body alias: $BodyId"
Write-Host ""

$cloneArgs = @{
    PerformerId = $PerformerId
    BodyId = $BodyId
    ApiKeyEnv = $ApiKeyEnv
    WslExe = $WslExe
    MaxSources = $MaxSources
    SceneLimit = $SceneLimit
    MaxSegments = $MaxSegments
    SithSeed = $SithSeed
    OutputDir = $cloneOutput
    SessionReport = $sessionReport
}
if (-not [string]::IsNullOrWhiteSpace($Name)) { $cloneArgs.Name = $Name }
if (-not [string]::IsNullOrWhiteSpace($RigSetupReport)) { $cloneArgs.RigSetupReport = $RigSetupReport }
if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $cloneArgs.BodyRigPython = $BodyRigPython }
if (-not [string]::IsNullOrWhiteSpace($StashUrl)) { $cloneArgs.StashUrl = $StashUrl }
if (-not [string]::IsNullOrWhiteSpace($TrackId)) { $cloneArgs.TrackId = $TrackId }
if (-not [string]::IsNullOrWhiteSpace($Ffmpeg)) { $cloneArgs.Ffmpeg = $Ffmpeg }

& $cloneScript @cloneArgs
if ($LASTEXITCODE -ne 0) { throw "Physical Stash clone failed." }
if (-not (Test-Path -LiteralPath $sessionReport -PathType Leaf)) { throw "Physical clone PASS did not publish the expected session report." }

$acceptArgs = @{ SessionReport = $sessionReport }
if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $acceptArgs.BodyRigPython = $BodyRigPython }
& $acceptScript @acceptArgs
if ($LASTEXITCODE -ne 0) { throw "High-fidelity Gate A promotion failed." }
if (-not (Test-Path -LiteralPath (Join-Path $acceptanceDir "bodyrig-acceptance.json") -PathType Leaf)) {
    throw "Gate A PASS did not publish the expected acceptance report."
}

$activateArgs = @{ AcceptanceDir = $acceptanceDir; Output = $finalReceipt }
if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $activateArgs.BodyRigPython = $BodyRigPython }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $activateArgs.UnityExe = $UnityExe }
if (-not [string]::IsNullOrWhiteSpace($AdbExe)) { $activateArgs.AdbExe = $AdbExe }
if (-not [string]::IsNullOrWhiteSpace($Serial)) { $activateArgs.Serial = $Serial }
& $activateScript @activateArgs
if ($LASTEXITCODE -ne 0) { throw "Automatic Windows/Quest production gate failed." }

if (-not (Test-Path -LiteralPath $finalReceipt -PathType Leaf)) { throw "Final production receipt was not written: $finalReceipt" }
try { $release = Get-Content -LiteralPath $finalReceipt -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Final production receipt is invalid JSON: $finalReceipt" }
if ([string]$release.format -ne "bodyrig-release-acceptance" -or [int]$release.version -ne 2 -or $release.release_gate_pass -ne $true -or $release.production_activation -ne $true) {
    throw "Final receipt is not an automatic production PASS."
}
if (([string]$release.bodyrig_revision).ToLowerInvariant() -ne $head) {
    throw "Final production receipt is bound to a different BodyRig revision."
}

$finalAuthority = [ordered]@{
    format = "bodyrig-one-command-production-authority"
    version = 1
    started_at = [string]$authority.started_at
    completed_at = [DateTime]::UtcNow.ToString("o")
    bodyrig_revision = $head
    performer_id = $PerformerId
    requested_body_alias = $BodyId
    session_report = $sessionReport
    clone_output = $cloneOutput
    acceptance_dir = $acceptanceDir
    release_receipt = $finalReceipt
    production_activation = $true
}
$finalTemp = "$runAuthority.$([Guid]::NewGuid().ToString('N')).tmp"
try {
    $finalAuthority | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $finalTemp -Encoding UTF8
    Move-Item -LiteralPath $finalTemp -Destination $runAuthority -Force
} finally {
    if (Test-Path -LiteralPath $finalTemp) { Remove-Item -LiteralPath $finalTemp -Force }
}

Write-Host ""
Write-Host "BODYRIG ONE-COMMAND PRODUCTION ACTIVATION: PASS"
Write-Host "production_activation=true"
Write-Host "Revision: $head"
Write-Host "Run authority: $runAuthority"
Write-Host "Release receipt: $finalReceipt"
exit 0
