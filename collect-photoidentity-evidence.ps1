param(
    [Parameter(Mandatory = $true)][string]$PerformerId,
    [Parameter(Mandatory = $true)][string]$BaselineCloneOutput,
    [string]$OutputDir = "",
    [string]$BodyRigPython = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$Ffmpeg = "",
    [string]$SchpRuntimeRoot = "",
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
function Need-CommandArgument {
    param(
        [Parameter(Mandatory = $true)][object[]]$Command,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $indices = @()
    for ($index = 0; $index -lt $Command.Count; $index++) {
        if ([string]$Command[$index] -eq $Name) { $indices += $index }
    }
    if ($indices.Count -ne 1) { throw "$Label requires exactly one $Name binding in the retained fitter command." }
    $valueIndex = [int]$indices[0] + 1
    if ($valueIndex -ge $Command.Count) { throw "$Label has an incomplete $Name binding." }
    $value = ([string]$Command[$valueIndex]).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) { throw "$Label has an empty $Name binding." }
    return $value
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
$fitterConfig = Need-File -Path (Join-Path $BaselineCloneOutput "bodyrig-sith-fitter-config.json") -Label "Baseline pinned SiTH fitter config"
try { $fitter = Get-Content -LiteralPath $fitterConfig -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Baseline pinned SiTH fitter config is unreadable JSON." }
if (
    [string]$fitter.format -ne "bodyrig-external-fitter-config" -or
    [int]$fitter.version -ne 1 -or
    [string]$fitter.adapter -ne "sith-smplx-vrm" -or
    [string]$fitter.revision -ne "1"
) {
    throw "Photoidentity detail collection requires the exact built-in pinned SiTH fitter config."
}
$fitterCommand = @($fitter.command)
if ($fitterCommand.Count -lt 8) { throw "Baseline pinned SiTH fitter command is incomplete." }
$SithDistribution = Need-CommandArgument -Command $fitterCommand -Name "--distribution" -Label "SiTH detail runtime"
$SithRepo = Need-CommandArgument -Command $fitterCommand -Name "--sith-repo" -Label "SiTH detail runtime"
$SithPython = Need-CommandArgument -Command $fitterCommand -Name "--sith-python" -Label "SiTH detail runtime"
$SithOpenPose = Need-CommandArgument -Command $fitterCommand -Name "--openpose" -Label "SiTH detail runtime"
$WslExe = Need-CommandArgument -Command $fitterCommand -Name "--wsl-exe" -Label "SiTH detail runtime"
$WslExe = Need-Executable -Value $WslExe -Fallback "wsl.exe" -Label "WSL"
foreach ($linuxValue in @($SithRepo,$SithPython,$SithOpenPose)) {
    if (-not $linuxValue.StartsWith("/")) { throw "Retained SiTH/OpenPose detail runtime must use absolute Linux paths." }
}
$openPoseSuffix = "/build/examples/openpose/openpose.bin"
if (-not $SithOpenPose.EndsWith($openPoseSuffix,[StringComparison]::Ordinal)) {
    throw "Retained OpenPose executable does not use the pinned standard repository layout."
}
$SithOpenPoseRepo = $SithOpenPose.Substring(0,$SithOpenPose.Length - $openPoseSuffix.Length)
if ([string]::IsNullOrWhiteSpace($SithOpenPoseRepo) -or -not $SithOpenPoseRepo.StartsWith("/")) {
    throw "Could not derive the pinned OpenPose repository from the retained fitter authority."
}

if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = [string]$env:STASH_URL }
if ([string]::IsNullOrWhiteSpace($StashUrl)) { throw "Stash URL is required via -StashUrl or STASH_URL." }
if ([string]::IsNullOrWhiteSpace($ApiKeyEnv)) { throw "ApiKeyEnv is required." }
$Ffmpeg = Need-Executable -Value $Ffmpeg -Fallback "ffmpeg" -Label "FFmpeg"

Write-Host "BodyRig photoidentity OpenPose detail runtime preflight"
& $BodyRigPython -m bodyrig.sith_preflight `
  --distribution $SithDistribution `
  --repo $SithRepo `
  --python $SithPython `
  --openpose $SithOpenPose `
  --openpose-repo $SithOpenPoseRepo `
  --wsl-exe $WslExe
if ($LASTEXITCODE -ne 0) { throw "Pinned SiTH/OpenPose detail runtime preflight failed with exit code $LASTEXITCODE." }

if ([string]::IsNullOrWhiteSpace($SchpRuntimeRoot)) {
    $base = [string]$env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($base)) { throw "LOCALAPPDATA is required for the default isolated SCHP runtime." }
    $SchpRuntimeRoot = Join-Path $base "BodyRig\runtimes\schp-atr18-v1"
}
$SchpRuntimeRoot = [IO.Path]::GetFullPath($SchpRuntimeRoot)
$setupSchp = Need-File -Path (Join-Path $repoRoot "setup-photoidentity-schp-windows.ps1") -Label "SCHP provisioning operator"
if (-not (Test-Path -LiteralPath $SchpRuntimeRoot -PathType Container)) {
    Write-Host "BodyRig SCHP runtime is not provisioned; creating isolated pinned runtime."
    & $setupSchp -RuntimeRoot $SchpRuntimeRoot -BodyRigPython $BodyRigPython
    if ($LASTEXITCODE -ne 0) { throw "SCHP runtime provisioning failed with exit code $LASTEXITCODE." }
}
& $BodyRigPython -m bodyrig.photoidentity_schp_preflight --runtime-root $SchpRuntimeRoot
if ($LASTEXITCODE -ne 0) { throw "Pinned SCHP runtime preflight failed with exit code $LASTEXITCODE." }

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
Write-Host "OpenPose proof: eyes + both hands + both feet"
Write-Host "SCHP proof:     hair/hairline + exposed source-skin observability"
Write-Host "Output:         $OutputDir"
Write-Host "Policy:         no generic guessing; no reconstruction/render authority"
Write-Host ""

$sweepArgs = @(
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
& $BodyRigPython @sweepArgs
if ($LASTEXITCODE -ne 0) { throw "BodyRig photoidentity evidence sweep failed with exit code $LASTEXITCODE." }

$detailArgs = @(
    "-m", "bodyrig.photoidentity_detail_enrich",
    "--sweep-root", $OutputDir,
    "--ffmpeg", $Ffmpeg,
    "--distribution", $SithDistribution,
    "--openpose", $SithOpenPose,
    "--wsl-exe", $WslExe
)
& $BodyRigPython @detailArgs
if ($LASTEXITCODE -ne 0) { throw "BodyRig pinned OpenPose detail enrichment failed with exit code $LASTEXITCODE." }

$schpArgs = @(
    "-m", "bodyrig.photoidentity_schp_enrich",
    "--sweep-root", $OutputDir,
    "--runtime-root", $SchpRuntimeRoot,
    "--ffmpeg", $Ffmpeg,
    "--repo-root", $repoRoot
)
& $BodyRigPython @schpArgs
if ($LASTEXITCODE -ne 0) { throw "BodyRig pinned SCHP enrichment failed with exit code $LASTEXITCODE." }

$reportPath = Need-File -Path (Join-Path $OutputDir "human-parsing-evidence\photoidentity-evidence.json") -Label "Final photoidentity sufficiency report"
$observationPath = Need-File -Path (Join-Path $OutputDir "human-parsing-evidence\photoidentity-observations.json") -Label "Final photoidentity observation evidence"
$validateCode = "import json,sys; from bodyrig.photoidentity_evidence import validate_bundle; r=validate_bundle(sys.argv[1],sys.argv[2]); print(json.dumps(r,separators=(',',':')))"
$validatedRaw = @(& $BodyRigPython -c $validateCode $reportPath $observationPath)
if ($LASTEXITCODE -ne 0 -or $validatedRaw.Count -ne 1) { throw "Photoidentity final evidence bundle failed strict validation." }
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
