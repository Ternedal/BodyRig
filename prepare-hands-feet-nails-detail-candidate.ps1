param(
    [Parameter(Mandatory = $true)]
    [string]$PersonId,

    [Parameter(Mandatory = $true)]
    [string]$BodyRevision,

    [Parameter(Mandatory = $true)]
    [string]$CaptureId,

    [Parameter(Mandatory = $true)]
    [string]$LandmarkBodyRigRevision,

    [Parameter(Mandatory = $true)]
    [string]$SourcePackagePath,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path $PSScriptRoot).Path

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Hands/feet/nails detail candidate preparation is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for HFN detail candidate preparation."
}

function Resolve-BodyRigPython {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) {
        return (Resolve-Path -LiteralPath $venv).Path
    }
    $command = Get-Command python -ErrorAction Stop
    return $command.Source
}

$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout state." }
if ($dirty.Count -gt 0) {
    throw "HFN detail candidate preparation requires a clean BodyRig checkout."
}
$revision = (@(& git -C $repoRoot rev-parse HEAD 2>&1) | Select-Object -First 1).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve canonical BodyRig checkout revision."
}
$landmarkRevision = $LandmarkBodyRigRevision.Trim().ToLowerInvariant()
if ($landmarkRevision -notmatch '^[0-9a-f]{40}$') {
    throw "LandmarkBodyRigRevision must be an exact 40-character Git revision."
}

$sourcePackage = (Resolve-Path -LiteralPath $SourcePackagePath -ErrorAction Stop).Path
if ([System.IO.Path]::GetExtension($sourcePackage) -ne ".mrbody") {
    throw "HFN detail candidate source must be an exact .mrbody package."
}
$output = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $output) {
    throw "HFN detail candidate output already exists; candidate creation is create-only."
}
$outputParent = Split-Path -Parent $output
if (-not (Test-Path -LiteralPath $outputParent -PathType Container)) {
    throw "HFN detail candidate output parent does not exist: $outputParent"
}

$python = Resolve-BodyRigPython
& $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "HFN detail candidate preparation requires Python 3.11+." }

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $repoRoot
    $imported = (& $python -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Could not import BodyRig from the operator checkout." }
    $expectedRoot = [System.IO.Path]::GetFullPath($repoRoot).TrimEnd('\') + '\'
    $actualModule = [System.IO.Path]::GetFullPath($imported)
    if (-not $actualModule.StartsWith($expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Python imported BodyRig outside the current checkout: $actualModule"
    }

    $json = & $python -m bodyrig.hands_feet_nails_detail_candidate_cli `
        --person-id $PersonId `
        --body-revision $BodyRevision `
        --capture-id $CaptureId `
        --landmark-bodyrig-revision $landmarkRevision `
        --source-package $sourcePackage `
        --output-dir $output `
        --bodyrig-revision $revision
    if ($LASTEXITCODE -ne 0) { throw "HFN detail candidate generation failed." }
    $result = ($json | Select-Object -Last 1) | ConvertFrom-Json
    if ($result.ok -ne $true -or $result.production_activation -ne $false -or $result.comparison_only -ne $true) {
        throw "HFN detail candidate CLI returned a non-canonical authority result."
    }
    if ([string]$result.candidate_bodyrig_revision -ne $revision) {
        throw "HFN detail candidate result is not bound to the exact operator checkout revision."
    }
    $candidatePackage = (Resolve-Path -LiteralPath ([string]$result.package_path) -ErrorAction Stop).Path
    $expectedPackage = [System.IO.Path]::GetFullPath((Join-Path $output "candidate.mrbody"))
    if ($candidatePackage -ne $expectedPackage) {
        throw "HFN detail candidate package escaped the requested output directory."
    }

    [pscustomobject]@{
        ok = $true
        person_id = [string]$result.person_id
        body_revision = [string]$result.body_revision
        capture_id = [string]$result.capture_id
        bodyrig_revision = $revision
        package_path = $candidatePackage
        candidate_package_sha256 = [string]$result.candidate_package_sha256
        receipt_path = [string]$result.receipt_path
        next_gate = "prepare-hands-feet-nails-render-review.ps1"
        comparison_only = $true
        human_review_required = $true
        production_activation = $false
    } | ConvertTo-Json -Compress
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
