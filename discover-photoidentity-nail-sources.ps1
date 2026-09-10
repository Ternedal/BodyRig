param(
    [Parameter(Mandatory = $true)][string]$SweepRoot,
    [Parameter(Mandatory = $true)][string]$BaselineCloneOutput,
    [string]$BodyRigPython = "",
    [string]$Ffmpeg = ""
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
    param([Parameter(Mandatory = $true)][object[]]$Command,[Parameter(Mandatory = $true)][string]$Name)
    $indices = @()
    for ($index = 0; $index -lt $Command.Count; $index++) {
        if ([string]$Command[$index] -eq $Name) { $indices += $index }
    }
    if ($indices.Count -ne 1) { throw "Pinned fitter requires exactly one $Name binding." }
    $valueIndex = [int]$indices[0] + 1
    if ($valueIndex -ge $Command.Count) { throw "Pinned fitter $Name binding is incomplete." }
    $value = ([string]$Command[$valueIndex]).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) { throw "Pinned fitter $Name binding is empty." }
    return $value
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig nail source discovery is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not establish exact BodyRig Git authority." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig Git HEAD is not canonical." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Nail source discovery requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { $BodyRigPython = Need-Executable -Value "" -Fallback "python" -Label "BodyRig Python" }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$expectedModule = Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "Checkout BodyRig module"
$moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "BodyRig Python could not prove checkout-bound imports." }
$actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
if (-not [string]::Equals($actualModule,$expectedModule,[StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports from a different checkout: $actualModule"
}

$SweepRoot = Need-Directory -Path $SweepRoot -Label "Photoidentity sweep root"
$BaselineCloneOutput = Need-Directory -Path $BaselineCloneOutput -Label "Baseline clone output"
$finalEvidence = Need-File -Path (Join-Path $SweepRoot "human-parsing-evidence\photoidentity-observations.json") -Label "Hair/skin-enriched observation evidence"
$revisionRaw = @(& $BodyRigPython -c "import json,sys; print(json.load(open(sys.argv[1],encoding='utf-8'))['bodyrig_revision'])" $finalEvidence 2>&1)
if ($LASTEXITCODE -ne 0 -or $revisionRaw.Count -ne 1) { throw "Could not read photoidentity evidence revision." }
$evidenceRevision = ([string]$revisionRaw[0]).Trim().ToLowerInvariant()
if ($evidenceRevision -ne $head) {
    throw "Photoidentity sweep belongs to BodyRig revision $evidenceRevision, current checkout is $head. Refusing cross-revision nail evidence."
}

$fitterConfig = Need-File -Path (Join-Path $BaselineCloneOutput "bodyrig-sith-fitter-config.json") -Label "Baseline pinned SiTH fitter config"
try { $fitter = Get-Content -LiteralPath $fitterConfig -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Baseline pinned SiTH fitter config is unreadable JSON." }
if (
    [string]$fitter.format -ne "bodyrig-external-fitter-config" -or
    [int]$fitter.version -ne 1 -or
    [string]$fitter.adapter -ne "sith-smplx-vrm" -or
    [string]$fitter.revision -ne "1"
) { throw "Nail discovery requires the exact built-in pinned SiTH fitter config." }
$fitterCommand = @($fitter.command)
$distribution = Need-CommandArgument -Command $fitterCommand -Name "--distribution"
$sithRepo = Need-CommandArgument -Command $fitterCommand -Name "--sith-repo"
$sithPython = Need-CommandArgument -Command $fitterCommand -Name "--sith-python"
$openpose = Need-CommandArgument -Command $fitterCommand -Name "--openpose"
$wslExe = Need-CommandArgument -Command $fitterCommand -Name "--wsl-exe"
$wslExe = Need-Executable -Value $wslExe -Fallback "wsl.exe" -Label "WSL"
$openPoseSuffix = "/build/examples/openpose/openpose.bin"
if (-not $openpose.EndsWith($openPoseSuffix,[StringComparison]::Ordinal)) {
    throw "Retained OpenPose executable does not use the pinned standard repository layout."
}
$openPoseRepo = $openpose.Substring(0,$openpose.Length - $openPoseSuffix.Length)
$Ffmpeg = Need-Executable -Value $Ffmpeg -Fallback "ffmpeg" -Label "FFmpeg"

Write-Host "BodyRig nail source discovery preflight"
Write-Host "Revision:  $head"
Write-Host "Sweep:     $SweepRoot"
Write-Host "Policy:    source closeups only; machine nail authority FALSE; no avatar render"
Write-Host ""

& $BodyRigPython -m bodyrig.sith_preflight `
  --distribution $distribution `
  --repo $sithRepo `
  --python $sithPython `
  --openpose $openpose `
  --openpose-repo $openPoseRepo `
  --wsl-exe $wslExe
if ($LASTEXITCODE -ne 0) { throw "Pinned OpenPose authority preflight failed with exit code $LASTEXITCODE." }

& $BodyRigPython -m bodyrig.photoidentity_nail_source_discovery `
  --sweep-root $SweepRoot `
  --ffmpeg $Ffmpeg `
  --distribution $distribution `
  --openpose $openpose `
  --wsl-exe $wslExe
if ($LASTEXITCODE -ne 0) { throw "BodyRig nail source discovery failed with exit code $LASTEXITCODE." }

Write-Host ""
Write-Host "BodyRig nail source discovery: COMPLETE"
Write-Host "No nail sufficiency authority has been granted. Review source closeups before any nail PASS can exist."
