param(
    [Parameter(Mandatory = $true)]
    [string]$PerformerId,

    [Parameter(Mandatory = $true)]
    [string]$ExternalPython,

    [Parameter(Mandatory = $true)]
    [string]$FourDHumansRepo,

    [Parameter(Mandatory = $true)]
    [string]$IdentityCaptureConfig,

    [Parameter(Mandatory = $true)]
    [string]$FitterConfig,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId,

    [string]$Name = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [ValidateRange(1, 10)]
    [int]$MaxSources = 10,
    [ValidateRange(1, 1000)]
    [int]$SceneLimit = 200,
    [string]$TrackId = "",
    [string]$OutputDir = "",
    [string]$BodyRigPython = "",
    [switch]$AllowCpu,
    [switch]$KeepPrivateWorkspace
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
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Step
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
if ([string]::IsNullOrWhiteSpace($StashUrl)) {
    $StashUrl = [string]$env:STASH_URL
}
if ([string]::IsNullOrWhiteSpace($StashUrl)) {
    throw "Stash URL is required via -StashUrl or STASH_URL."
}
if ([string]::IsNullOrWhiteSpace($ApiKeyEnv)) {
    throw "-ApiKeyEnv must name the environment variable containing the Stash API key."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $BodyRigPython = $venvPython
    } else {
        $BodyRigPython = Resolve-CommandPath "python"
    }
}
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    throw "BodyRig Python not found. Create .venv or pass -BodyRigPython."
}
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"

$powerShellExe = Resolve-CommandPath "pwsh"
if ($null -eq $powerShellExe) {
    $powerShellExe = Resolve-CommandPath "powershell"
}
if ($null -eq $powerShellExe) {
    throw "PowerShell executable not found."
}

$stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path (Get-Location).Path "bodyrig-stash-$BodyId-$stamp"
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) {
    throw "Stash clone output directory already exists; refusing cross-run reuse: $OutputDir"
}
New-Item -ItemType Directory -Path $OutputDir | Out-Null

$sourceManifest = Join-Path $OutputDir "bodyrig-stash-source-manifest.json"
$cloneOutput = Join-Path $OutputDir "clone"

$selectArgs = @(
    "-m", "bodyrig.stash_cli", "select",
    "--performer-id", $PerformerId,
    "--scene-limit", [string]$SceneLimit,
    "--max-sources", [string]$MaxSources,
    "--out", $sourceManifest,
    "--url", $StashUrl,
    "--api-key-env", $ApiKeyEnv
)
Invoke-Checked -Executable $BodyRigPython -Arguments $selectArgs -Step "Stash performer source selection"

try {
    $manifest = Get-Content -LiteralPath $sourceManifest -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    throw "BodyRig Stash source manifest is unreadable after selection."
}
if ([string]$manifest.performer.id -ne $PerformerId) {
    throw "Stash source manifest performer id mismatch."
}
$selected = @($manifest.selected)
if ($selected.Count -lt 1 -or $selected.Count -gt 10) {
    throw "Stash source selection returned an invalid source count."
}
if ([string]::IsNullOrWhiteSpace($Name)) {
    $Name = [string]$manifest.performer.name
}
if ([string]::IsNullOrWhiteSpace($Name) -or $Name.Length -gt 160) {
    throw "BodyRig display name from Stash is invalid; pass -Name explicitly."
}

Write-Host "BodyRig Stash clone"
Write-Host "Performer: $Name [$PerformerId]"
Write-Host "Selected sources: $($selected.Count)"
foreach ($item in $selected) {
    Write-Host ("  {0:N1} | {1}x{2} | performers={3} | {4}" -f [double]$item.score, [int]$item.width, [int]$item.height, [int]$item.performer_count, [string]$item.scene_title)
}
Write-Host ""

$cloneScript = Join-Path $repoRoot "clone-body.ps1"
if (-not (Test-Path -LiteralPath $cloneScript -PathType Leaf)) {
    throw "clone-body.ps1 not found: $cloneScript"
}

$cloneArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $cloneScript,
    "-SourceManifest", $sourceManifest,
    "-ExternalPython", $ExternalPython,
    "-FourDHumansRepo", $FourDHumansRepo,
    "-IdentityCaptureConfig", $IdentityCaptureConfig,
    "-FitterConfig", $FitterConfig,
    "-BodyId", $BodyId,
    "-Name", $Name,
    "-OutputDir", $cloneOutput,
    "-BodyRigPython", $BodyRigPython
)
if (-not [string]::IsNullOrWhiteSpace($TrackId)) {
    $cloneArgs += @("-TrackId", $TrackId)
}
if ($AllowCpu) { $cloneArgs += "-AllowCpu" }
if ($KeepPrivateWorkspace) { $cloneArgs += "-KeepPrivateWorkspace" }

Invoke-Checked -Executable $powerShellExe -Arguments $cloneArgs -Step "BodyRig clone pipeline"

# Keep the exact selection manifest beside the clone evidence. The clone
# pipeline references this fixed filename but does not place it in .mrbody.
Copy-Item -LiteralPath $sourceManifest -Destination (Join-Path $cloneOutput "bodyrig-stash-source-manifest.json") -Force

Write-Host ""
Write-Host "BodyRig Stash clone: PASS"
Write-Host "Performer: $Name [$PerformerId]"
Write-Host "Source manifest: $sourceManifest"
Write-Host "Clone output: $cloneOutput"
exit 0
