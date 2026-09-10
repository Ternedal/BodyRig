param(
    [Parameter(Mandatory = $true)][string]$SweepRoot,
    [string]$BodyRigPython = "",
    [switch]$NoOpen
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
    throw "BodyRig nail source review preparation is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not establish exact BodyRig Git authority." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig Git HEAD is not canonical." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Nail source review preparation requires an exact clean BodyRig checkout." }

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
$discovery = Need-File -Path (Join-Path $SweepRoot "nail-source-candidates.json") -Label "Nail source discovery manifest"
$revisionRaw = @(& $BodyRigPython -c "import json,sys; print(json.load(open(sys.argv[1],encoding='utf-8'))['bodyrig_revision'])" $discovery 2>&1)
if ($LASTEXITCODE -ne 0 -or $revisionRaw.Count -ne 1) { throw "Could not read nail discovery revision." }
$evidenceRevision = ([string]$revisionRaw[0]).Trim().ToLowerInvariant()
if ($evidenceRevision -ne $head) {
    throw "Nail source discovery belongs to BodyRig revision $evidenceRevision, current checkout is $head."
}

& $BodyRigPython -m bodyrig.photoidentity_nail_review_prepare --sweep-root $SweepRoot
if ($LASTEXITCODE -ne 0) { throw "BodyRig private nail source review preparation failed with exit code $LASTEXITCODE." }

$reviewRoot = Need-Directory -Path (Join-Path $SweepRoot "private-nail-source-review") -Label "Private nail source review folder"
$refs = Need-File -Path (Join-Path $reviewRoot "review-refs.txt") -Label "Nail source review reference list"
Write-Host ""
Write-Host "Review only the real source closeups in:"
Write-Host $reviewRoot
Write-Host ""
Write-Host "Candidate refs:"
Get-Content -LiteralPath $refs -Encoding UTF8 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "No avatar render was created. No nail authority has been granted."
if (-not $NoOpen) {
    Start-Process explorer.exe -ArgumentList @($reviewRoot)
}
