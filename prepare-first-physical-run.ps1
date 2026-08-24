param(
    [string]$RigSetupReport = "",
    [string]$BodyRigPython = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$WslExe = "wsl.exe",
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

function Quote-PowerShellLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The production physical BodyRig run is Windows-only. Run this doctor on the target Windows rig."
}

$head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not prove the BodyRig Git HEAD."
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

if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = [string]$env:STASH_URL }
if ([string]::IsNullOrWhiteSpace($StashUrl)) {
    throw "Stash URL is required via -StashUrl or STASH_URL."
}

$hasPerformer = -not [string]::IsNullOrWhiteSpace($PerformerId)
$hasBodyId = -not [string]::IsNullOrWhiteSpace($BodyId)
if ($hasPerformer -xor $hasBodyId) {
    throw "Pass -PerformerId and -BodyId together, or omit both."
}

$powerShellExe = Resolve-CommandPath "pwsh"
if ($null -eq $powerShellExe) { $powerShellExe = Resolve-CommandPath "powershell" }
if ($null -eq $powerShellExe) { throw "PowerShell executable not found." }

$readinessScript = Join-Path $repoRoot "check-rig-ready.ps1"
if (-not (Test-Path -LiteralPath $readinessScript -PathType Leaf)) {
    throw "check-rig-ready.ps1 not found."
}

Write-Host "BodyRig first physical run doctor"
Write-Host "BodyRig revision: $head"
Write-Host "Checkout: clean"
Write-Host "BodyRig Python: $BodyRigPython"
Write-Host "Rig setup: $RigSetupReport"
Write-Host "Stash URL: $StashUrl"
Write-Host ""
Write-Host "Running live non-session readiness checks..."

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

$finalHead = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $finalHead -ne $head) {
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
Write-Host "No physical clone session or acceptance evidence was created."

if ($hasPerformer -and $hasBodyId) {
    $quotedPerformer = Quote-PowerShellLiteral -Value $PerformerId
    $quotedBody = Quote-PowerShellLiteral -Value $BodyId
    Write-Host ""
    Write-Host "Next production command:"
    Write-Host ".\clone-body-from-stash-ready.ps1 -PerformerId $quotedPerformer -BodyId $quotedBody"
} else {
    Write-Host ""
    Write-Host "Next: run .\stash-sources.ps1 search '<performer name>' -Limit 10, then rerun this doctor with -PerformerId and -BodyId to print the exact production command."
}

exit 0
