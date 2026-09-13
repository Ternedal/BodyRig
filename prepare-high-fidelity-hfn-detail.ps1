param(
    [Parameter(Mandatory = $true)][string]$PreviewJobId,
    [Parameter(Mandatory = $true)][string]$CaptureId,
    [Parameter(Mandatory = $true)][string]$LandmarkEvidence,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path $PSScriptRoot).Path

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "High-fidelity HFN continuation is Windows-operator-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for high-fidelity HFN continuation."
}

$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout state." }
if ($dirty.Count -ne 0) { throw "High-fidelity HFN continuation requires a clean BodyRig checkout." }
$head = (@(& git -C $repoRoot rev-parse HEAD 2>&1) | Select-Object -First 1).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig Git revision."
}

$landmarks = (Resolve-Path -LiteralPath $LandmarkEvidence -ErrorAction Stop).Path
if ([System.IO.Path]::GetExtension($landmarks) -ne ".json") {
    throw "HFN landmark evidence must be an exact JSON evidence file."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { $BodyRigPython = "python" }
}
$python = (Get-Command $BodyRigPython -ErrorAction Stop).Source
& $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "High-fidelity HFN continuation requires Python 3.11+." }

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

    & $python -m bodyrig.high_fidelity_hfn_detail_cli `
        --preview-job-id $PreviewJobId `
        --capture-id $CaptureId `
        --landmark-evidence $landmarks `
        --bodyrig-revision $head
    if ($LASTEXITCODE -ne 0) { throw "BodyRig high-fidelity HFN detail preparation failed." }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
