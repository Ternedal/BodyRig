param(
    [Parameter(Mandatory = $true)]
    [string]$PerformerId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId,

    [string]$Name = "",
    [string]$RigSetupReport = "",
    [string]$BodyRigPython = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$WslExe = "wsl.exe",
    [ValidateRange(1, 10)]
    [int]$MaxSources = 10,
    [ValidateRange(1, 1000)]
    [int]$SceneLimit = 200,
    [ValidateRange(1, 10)]
    [int]$MaxSegments = 10,
    [string]$TrackId = "",
    [string]$Ffmpeg = "",
    [ValidateRange(0, 2147483647)]
    [int]$SithSeed = 1337,
    [ValidateSet("female", "male", "neutral")]
    [string]$BodyModelGender = "",
    [string]$UnityExe = "",
    [string]$RunRoot = "",
    [switch]$KeepPrivateWorkspace
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Invoke-CanonicalScript {
    param(
        [Parameter(Mandatory = $true)][string]$Script,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    & $pwsh -NoProfile -ExecutionPolicy Bypass -File $Script @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { throw "$Label failed with exit code $exitCode" }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The profiled fidelity-to-renderer workflow is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the profiled fidelity-to-renderer workflow."
}
$pwshCommand = Get-Command pwsh -ErrorAction SilentlyContinue
if ($null -eq $pwshCommand -or [string]::IsNullOrWhiteSpace([string]$pwshCommand.Source)) {
    throw "PowerShell 7 executable (pwsh) was not found."
}
$pwsh = $pwshCommand.Source

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$profiledClone = Need-File -Path (Join-Path $repoRoot "clone-body-from-stash-profiled-ready.ps1") -Label "Profiled canonical clone launcher"
$gateA = Need-File -Path (Join-Path $repoRoot "accept-physical-clone.ps1") -Label "Canonical Gate A launcher"
$rendererReady = Need-File -Path (Join-Path $repoRoot "check-reference-renderer-ready.ps1") -Label "Reference renderer readiness launcher"
$rendererProbe = Need-File -Path (Join-Path $repoRoot "run-reference-windows-renderer-probe.ps1") -Label "Canonical Windows renderer probe"

$headLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) { throw "Could not resolve BodyRig Git HEAD." }
$head = ([string]$headLines[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig Git HEAD is not canonical." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig Git status." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; the profiled physical workflow requires an exact clean checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $BodyRigPython = $candidate
    } else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python -or [string]::IsNullOrWhiteSpace([string]$python.Source)) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"

$artifactBase = [string]$env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($artifactBase)) { $artifactBase = [System.IO.Path]::GetTempPath() }
if ([string]::IsNullOrWhiteSpace($RunRoot)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $RunRoot = Join-Path $artifactBase "BodyRig\profiled-fidelity-runs\$BodyId-$stamp-$suffix"
}
$RunRoot = [System.IO.Path]::GetFullPath($RunRoot)
$repoPrefix = $repoRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if ([string]::Equals($RunRoot.TrimEnd('\', '/'), $repoRoot.TrimEnd('\', '/'), [System.StringComparison]::OrdinalIgnoreCase) -or
    $RunRoot.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "RunRoot must be outside the BodyRig checkout so generated physical evidence cannot dirty the repository."
}
if (Test-Path -LiteralPath $RunRoot) { throw "RunRoot already exists; refusing cross-run evidence reuse: $RunRoot" }
New-Item -ItemType Directory -Path $RunRoot | Out-Null

$sessionReport = Join-Path $RunRoot "physical-session.json"
$cloneOutput = Join-Path $RunRoot "clone-output"
$acceptanceDir = Join-Path $cloneOutput "acceptance"

$cloneArgs = @(
    "-PerformerId", $PerformerId,
    "-BodyId", $BodyId,
    "-BodyRigPython", $BodyRigPython,
    "-ApiKeyEnv", $ApiKeyEnv,
    "-WslExe", $WslExe,
    "-MaxSources", [string]$MaxSources,
    "-SceneLimit", [string]$SceneLimit,
    "-MaxSegments", [string]$MaxSegments,
    "-SithSeed", [string]$SithSeed,
    "-OutputDir", $cloneOutput,
    "-SessionReport", $sessionReport
)
if (-not [string]::IsNullOrWhiteSpace($Name)) { $cloneArgs += @("-Name", $Name) }
if (-not [string]::IsNullOrWhiteSpace($RigSetupReport)) { $cloneArgs += @("-RigSetupReport", $RigSetupReport) }
if (-not [string]::IsNullOrWhiteSpace($StashUrl)) { $cloneArgs += @("-StashUrl", $StashUrl) }
if (-not [string]::IsNullOrWhiteSpace($TrackId)) { $cloneArgs += @("-TrackId", $TrackId) }
if (-not [string]::IsNullOrWhiteSpace($Ffmpeg)) { $cloneArgs += @("-Ffmpeg", $Ffmpeg) }
if (-not [string]::IsNullOrWhiteSpace($BodyModelGender)) { $cloneArgs += @("-BodyModelGender", $BodyModelGender) }
if ($KeepPrivateWorkspace) { $cloneArgs += "-KeepPrivateWorkspace" }

Write-Host "BodyRig profiled fidelity -> renderer readiness"
Write-Host "Revision:       $head"
Write-Host "Performer id:   $PerformerId"
Write-Host "Body id:        $BodyId"
Write-Host "Run root:       $RunRoot"
Write-Host "Session report: $sessionReport"
Write-Host "Clone output:   $cloneOutput"
Write-Host "Acceptance:     $acceptanceDir"
Write-Host ""
Write-Host "Stage 1/3: fresh performer-profiled physical clone"
Invoke-CanonicalScript -Script $profiledClone -Arguments $cloneArgs -Label "Profiled physical clone"

Write-Host ""
Write-Host "Stage 2/3: canonical high-fidelity Gate A"
$gateArgs = @(
    "-SessionReport", $sessionReport,
    "-BodyRigPython", $BodyRigPython,
    "-OutputDir", $acceptanceDir
)
Invoke-CanonicalScript -Script $gateA -Arguments $gateArgs -Label "High-fidelity Gate A"

Write-Host ""
Write-Host "Stage 3/3: pinned reference-renderer toolchain readiness"
$rendererArgs = @()
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $rendererArgs += @("-UnityExe", $UnityExe) }
Invoke-CanonicalScript -Script $rendererReady -Arguments $rendererArgs -Label "Reference renderer readiness"

if (-not (Test-Path -LiteralPath (Join-Path $acceptanceDir "bodyrig-acceptance.json") -PathType Leaf)) {
    throw "Gate A returned success without a canonical bodyrig-acceptance.json."
}

Write-Host ""
Write-Host "BodyRig profiled fidelity preparation: PASS"
Write-Host "Fresh clone and Gate A are complete; no human renderer acceptance has been claimed."
Write-Host "Acceptance directory: $acceptanceDir"
Write-Host ""
Write-Host "NEXT HUMAN GATE (run only when ready to inspect the six-pose WindowsPlayer):"
$nextCommand = ".\run-reference-windows-renderer-probe.ps1 -AcceptanceDir `"$acceptanceDir`""
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $nextCommand += " -UnityExe `"$UnityExe`"" }
Write-Host $nextCommand
Write-Host "If Windows visual quality fails, stop there; do not proceed to Quest/final activation."
exit 0