param(
    [string]$RigSetupReport = "",
    [string]$BodyRigPython = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$WslExe = "wsl.exe",
    [string]$Ffmpeg = "",
    [string]$PerformerId = "",
    [ValidatePattern('^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Resolve-InputFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-Executable {
    param(
        [string]$Value,
        [Parameter(Mandatory = $true)][string]$Fallback,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        if (Test-Path -LiteralPath $Value -PathType Leaf) {
            return (Resolve-Path -LiteralPath $Value).Path
        }
        $resolvedValue = Resolve-CommandPath $Value
        if ($null -ne $resolvedValue) { return $resolvedValue }
        throw "$Label executable not found: $Value"
    }
    $resolved = Resolve-CommandPath $Fallback
    if ($null -eq $resolved) { throw "$Label executable not found: $Fallback" }
    return $resolved
}

function Quote-PowerShellLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The production physical BodyRig run is Windows-only. Run this doctor on the target Windows rig."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the production physical BodyRig path. Reopen the checkout in pwsh and rerun the doctor."
}
$powerShellExe = Resolve-CommandPath "pwsh"
if ($null -eq $powerShellExe) {
    throw "PowerShell 7 executable (pwsh) was not found even though the current shell reports PowerShell 7+."
}

$headRaw = @(& git -C $repoRoot rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not prove the BodyRig Git HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not prove a canonical 40-character BodyRig Git HEAD."
}
$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect BodyRig Git status."
}
if ($dirty.Count -gt 0) {
    throw "BodyRig checkout is dirty. Commit/stash changes before starting a production-valid physical session."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { $BodyRigPython = $venv }
    else { $BodyRigPython = Resolve-CommandPath "python" }
}
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    throw "BodyRig Python not found. Create the repo venv or pass -BodyRigPython explicitly."
}
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"

$expectedBodyRigModule = Resolve-InputFile -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "BodyRig checkout module"
$authorityRaw = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())")
if ($LASTEXITCODE -ne 0 -or $authorityRaw.Count -ne 1) {
    throw "BodyRig Python could not prove a single checkout-bound bodyrig import."
}
$actualBodyRigModule = Resolve-InputFile -Path ([string]$authorityRaw[0]).Trim() -Label "Imported BodyRig module"
if (-not [string]::Equals($actualBodyRigModule, $expectedBodyRigModule, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports bodyrig from unexpected location: $actualBodyRigModule. Expected checkout authority: $expectedBodyRigModule"
}

if ([string]::IsNullOrWhiteSpace($RigSetupReport)) {
    $RigSetupReport = [string][Environment]::GetEnvironmentVariable("BODYRIG_RIG_SETUP_REPORT")
}
if ([string]::IsNullOrWhiteSpace($RigSetupReport) -and -not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $candidate = Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $RigSetupReport = $candidate }
}
if ([string]::IsNullOrWhiteSpace($RigSetupReport)) {
    throw "BodyRig rig setup report is required. Run setup-rig-windows.ps1 or pass -RigSetupReport."
}
$RigSetupReport = Resolve-InputFile -Path $RigSetupReport -Label "BodyRig rig setup report"

# Fail stale rig/SiTH setup authority before spending operator time on renderer,
# Stash or other live readiness checks. bodyrig.rig_setup verifies the master
# report bytes and its nested bodyrig-sith-setup v4 evidence, including the
# checkpoint-bound setup report introduced for canonical physical runs.
$rigSetupValidationRaw = @(& $BodyRigPython -m bodyrig.rig_setup $RigSetupReport)
if ($LASTEXITCODE -ne 0) {
    throw "BodyRig rig setup validation failed. Canonical physical runs require nested bodyrig-sith-setup v4 authority; rerun setup-rig-windows.ps1 to regenerate stale v1/v2/v3 setup evidence before continuing."
}
if ($rigSetupValidationRaw.Count -ne 1) {
    throw "BodyRig rig setup validation did not return exactly one canonical report."
}

if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = [string]$env:STASH_URL }
if ([string]::IsNullOrWhiteSpace($StashUrl)) {
    throw "Stash URL is required via -StashUrl or STASH_URL."
}
$WslExe = Resolve-Executable -Value $WslExe -Fallback "wsl.exe" -Label "WSL"

$hasPerformer = -not [string]::IsNullOrWhiteSpace($PerformerId)
$hasBodyId = -not [string]::IsNullOrWhiteSpace($BodyId)
if ($hasPerformer -xor $hasBodyId) {
    throw "Pass -PerformerId and -BodyId together, or omit both."
}
if ($hasPerformer) {
    $Ffmpeg = Resolve-Executable -Value $Ffmpeg -Fallback "ffmpeg" -Label "FFmpeg"
}

$rendererReadinessScript = Join-Path $repoRoot "check-reference-renderer-ready.ps1"
if (-not (Test-Path -LiteralPath $rendererReadinessScript -PathType Leaf)) {
    throw "check-reference-renderer-ready.ps1 not found."
}
$readinessScript = Join-Path $repoRoot "check-rig-ready.ps1"
if (-not (Test-Path -LiteralPath $readinessScript -PathType Leaf)) {
    throw "check-rig-ready.ps1 not found."
}

Write-Host "BodyRig first physical run doctor"
Write-Host "BodyRig revision: $head"
Write-Host "Checkout: clean"
Write-Host "PowerShell: $($PSVersionTable.PSVersion.ToString()) | pwsh: $powerShellExe"
Write-Host "BodyRig Python: $BodyRigPython"
Write-Host "Rig setup: $RigSetupReport"
Write-Host "Rig setup authority: validated (nested bodyrig-sith-setup v4)"
Write-Host "Stash URL: $StashUrl"
Write-Host "WSL authority: $WslExe"
if ($hasPerformer) { Write-Host "FFmpeg decode authority: $Ffmpeg" }
Write-Host ""
Write-Host "Checking Unity/Quest reference-renderer toolchain..."
& $rendererReadinessScript
if ($LASTEXITCODE -ne 0) {
    throw "BodyRig reference-renderer toolchain readiness failed with exit code $LASTEXITCODE. No physical session was started."
}
Write-Host ""
Write-Host "Running live non-session recovery/SiTH/Stash readiness checks..."

$readinessArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $readinessScript,
    "-RigSetupReport", $RigSetupReport,
    "-BodyRigPython", $BodyRigPython,
    "-StashUrl", $StashUrl,
    "-ApiKeyEnv", $ApiKeyEnv,
    "-WslExe", $WslExe
)
& $powerShellExe @readinessArgs
if ($LASTEXITCODE -ne 0) {
    throw "BodyRig live readiness failed with exit code $LASTEXITCODE. No physical session was started."
}

if ($hasPerformer) {
    Write-Host ""
    Write-Host "Probing selected Stash performer and local source pool with one-frame FFmpeg decode..."
    $probeRaw = @(& $BodyRigPython -m bodyrig.stash_cli probe --performer-id $PerformerId --url $StashUrl --api-key-env $ApiKeyEnv --ffmpeg $Ffmpeg)
    if ($LASTEXITCODE -ne 0) {
        throw "Selected Stash performer/source decode probe failed with exit code $LASTEXITCODE. No physical session was started."
    }
    try { $probe = ($probeRaw -join "`n") | ConvertFrom-Json }
    catch { throw "Selected Stash performer/source decode probe returned unreadable JSON. No physical session was started." }
    if ($probe.ok -ne $true -or [int]$probe.usable_source_count -lt 1) {
        throw "Selected Stash performer/source decode probe did not prove at least one decodable local video. No physical session was started."
    }
    if ([string]$probe.decode_gate -ne "ffmpeg-one-frame-v1") {
        throw "Selected Stash performer/source probe did not use the canonical ffmpeg-one-frame-v1 decode gate. No physical session was started."
    }
    if ([string]$probe.performer.id -ne $PerformerId) {
        throw "Selected Stash performer/source probe returned a different performer id. No physical session was started."
    }
    Write-Host "Selected performer: $([string]$probe.performer.name) [$([string]$probe.performer.id)] | candidates: $([int]$probe.candidate_count) | rankable local sources: $([int]$probe.rankable_source_count) | decodable local sources: $([int]$probe.usable_source_count)"
}

$finalHeadRaw = @(& git -C $repoRoot rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or $finalHeadRaw.Count -ne 1) {
    throw "Could not re-check BodyRig Git HEAD after pre-session readiness."
}
$finalHead = ([string]$finalHeadRaw[0]).Trim().ToLowerInvariant()
if ($finalHead -ne $head) {
    throw "BodyRig Git HEAD changed during pre-session readiness."
}
$finalDirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Could not re-check BodyRig Git status after readiness."
}
if ($finalDirty.Count -gt 0) {
    throw "BodyRig checkout became dirty during pre-session readiness. Do not start production evidence."
}

Write-Host ""
Write-Host "BodyRig pre-session doctor: READY"
Write-Host "Recovery, selected-source decode, Stash, Unity and Quest build toolchains are ready."
Write-Host "No Unity project was opened and no physical clone session or acceptance evidence was created."

if ($hasPerformer -and $hasBodyId) {
    $quotedPerformer = Quote-PowerShellLiteral -Value $PerformerId
    $quotedBody = Quote-PowerShellLiteral -Value $BodyId
    $quotedRigSetup = Quote-PowerShellLiteral -Value $RigSetupReport
    $quotedBodyRigPython = Quote-PowerShellLiteral -Value $BodyRigPython
    $quotedStashUrl = Quote-PowerShellLiteral -Value $StashUrl
    $quotedApiKeyEnv = Quote-PowerShellLiteral -Value $ApiKeyEnv
    $quotedWslExe = Quote-PowerShellLiteral -Value $WslExe
    $quotedFfmpeg = Quote-PowerShellLiteral -Value $Ffmpeg
    $nextCommand = ".\clone-body-from-stash-ready.ps1 -PerformerId $quotedPerformer -BodyId $quotedBody -RigSetupReport $quotedRigSetup -BodyRigPython $quotedBodyRigPython -StashUrl $quotedStashUrl -ApiKeyEnv $quotedApiKeyEnv -WslExe $quotedWslExe -Ffmpeg $quotedFfmpeg"
    Write-Host ""
    Write-Host "Next production command:"
    Write-Host $nextCommand
} else {
    Write-Host ""
    Write-Host "Next: run .\stash-sources.ps1 search '<performer name>' -Limit 10, then rerun this doctor with -PerformerId and -BodyId to print the exact production command."
}

exit 0
