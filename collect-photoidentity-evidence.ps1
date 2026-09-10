param(
    [Parameter(Mandatory = $true)][string]$PerformerId,
    [Parameter(Mandatory = $true)][string]$BaselineCloneOutput,
    [string]$OutputDir = "",
    [string]$BodyRigPython = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$Ffmpeg = "",
    [ValidateRange(1, 1000)][int]$SceneLimit = 1000,
    [ValidateRange(1, 100)][int]$MaxSources = 50,
    [ValidateRange(1, 10)][int]$BatchSize = 10,
    [ValidateRange(1, 120)][int]$DecodeTimeout = 20,
    [switch]$RequireSufficient
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-Executable {
    param([string]$Value,[string]$Fallback,[string]$Label)
    $candidate = if ([string]::IsNullOrWhiteSpace($Value)) { $Fallback } else { $Value }
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "$Label executable not found: $candidate" }
    return $command.Source
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig photoidentity source collection is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not bind photoidentity collection to BodyRig Git HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig Git HEAD is not canonical." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Photoidentity collection requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { $BodyRigPython = $venv }
    else { $BodyRigPython = Need-Executable -Value "" -Fallback "python" -Label "BodyRig Python" }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$expectedModule = Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "Checkout BodyRig module"
$moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "BodyRig Python could not prove checkout-bound import authority." }
$actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
if (-not [string]::Equals($actualModule,$expectedModule,[StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports bodyrig from a different checkout: $actualModule"
}

$BaselineCloneOutput = Need-Directory -Path $BaselineCloneOutput -Label "Baseline Stash clone output"
$sourceManifest = Need-File -Path (Join-Path $BaselineCloneOutput "bodyrig-stash-source-manifest.json") -Label "Baseline Stash source manifest"
$analyzerConfig = Need-File -Path (Join-Path $BaselineCloneOutput "bodyrig-observation-analyzer-config.json") -Label "Baseline observation analyzer config"

if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = [string]$env:STASH_URL }
if ([string]::IsNullOrWhiteSpace($StashUrl)) { throw "Stash URL is required via -StashUrl or STASH_URL." }
if ([string]::IsNullOrWhiteSpace($ApiKeyEnv)) { throw "ApiKeyEnv is required." }
$Ffmpeg = Need-Executable -Value $Ffmpeg -Fallback "ffmpeg" -Label "FFmpeg"

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $base = [string]$env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($base)) { $base = [IO.Path]::GetTempPath() }
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $OutputDir = Join-Path $base "BodyRig\photoidentity-evidence\$PerformerId-$stamp-$suffix"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$repoBoundary = $repoRoot + [IO.Path]::DirectorySeparatorChar
if ([string]::Equals($OutputDir,$repoRoot,[StringComparison]::OrdinalIgnoreCase) -or $OutputDir.StartsWith($repoBoundary,[StringComparison]::OrdinalIgnoreCase)) {
    throw "Photoidentity evidence output must be outside the BodyRig Git checkout."
}
if (Test-Path -LiteralPath $OutputDir) { throw "Photoidentity evidence output already exists: $OutputDir" }

Write-Host "BodyRig photoidentity evidence collection"
Write-Host "Revision:       $head"
Write-Host "Performer:      $PerformerId"
Write-Host "Scene limit:    $SceneLimit"
Write-Host "Source budget:  $MaxSources (batches of $BatchSize)"
Write-Host "Output:         $OutputDir"
Write-Host "Policy:         no generic guessing; no reconstruction/render authority"
Write-Host ""

$args = @(
    "-m", "bodyrig.photoidentity_sweep",
    "--performer-id", $PerformerId,
    "--baseline-source-manifest", $sourceManifest,
    "--analyzer-config", $analyzerConfig,
    "--stash-url", $StashUrl,
    "--api-key-env", $ApiKeyEnv,
    "--bodyrig-revision", $head,
    "--output-dir", $OutputDir,
    "--ffmpeg", $Ffmpeg,
    "--scene-limit", [string]$SceneLimit,
    "--max-sources", [string]$MaxSources,
    "--batch-size", [string]$BatchSize,
    "--decode-timeout", [string]$DecodeTimeout
)
& $BodyRigPython @args
if ($LASTEXITCODE -ne 0) { throw "BodyRig photoidentity evidence sweep failed with exit code $LASTEXITCODE." }

$reportPath = Need-File -Path (Join-Path $OutputDir "evidence\photoidentity-evidence.json") -Label "Photoidentity sufficiency report"
$observationPath = Need-File -Path (Join-Path $OutputDir "evidence\photoidentity-observations.json") -Label "Photoidentity observation evidence"
$validateCode = "import json,sys; from bodyrig.photoidentity_evidence import validate_bundle; r=validate_bundle(sys.argv[1],sys.argv[2]); print(json.dumps(r,separators=(',',':')))"
$validatedRaw = @(& $BodyRigPython -c $validateCode $reportPath $observationPath)
if ($LASTEXITCODE -ne 0 -or $validatedRaw.Count -ne 1) { throw "Photoidentity evidence bundle failed strict validation." }
try { $report = ([string]$validatedRaw[0]) | ConvertFrom-Json -Depth 30 }
catch { throw "Photoidentity evidence validator returned unreadable JSON." }

Write-Host ""
Write-Host "========== PHOTOIDENTITY SOURCE SUFFICIENCY =========="
foreach ($property in $report.domains.PSObject.Properties) {
    $name = [string]$property.Name
    $entry = $property.Value
    Write-Host ("{0,-20} {1,-24} scenes={2}/{3}" -f $name, [string]$entry.status, [int]$entry.qualifying_distinct_scenes, [int]$entry.minimum_distinct_scenes)
}
Write-Host ""
Write-Host "Scanned sources: $([int]$report.source_files_scanned)"
Write-Host "Scan exhausted:  $([bool]$report.scan_exhausted)"
Write-Host "Next action:     $([string]$report.next_action)"
Write-Host "Evidence:        $reportPath"
Write-Host "Render permitted: $([bool]$report.human_review_render_permitted)"
Write-Host "Generic guessing permitted: FALSE"

if ($report.source_evidence_sufficient -eq $true) {
    Write-Host "BodyRig photoidentity evidence gate: PASS"
    exit 0
}

Write-Host "BodyRig photoidentity evidence gate: INSUFFICIENT EVIDENCE"
if (@($report.analyzer_blockers).Count -gt 0) {
    Write-Host "Analyzer cannot prove: $(@($report.analyzer_blockers) -join ', ')"
}
if (@($report.source_blockers).Count -gt 0) {
    Write-Host "Source coverage missing: $(@($report.source_blockers) -join ', ')"
}
if ($RequireSufficient) { exit 2 }
exit 0
