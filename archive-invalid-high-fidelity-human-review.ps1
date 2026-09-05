param(
    [Parameter(Mandatory = $true)][string]$PackagePath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig high-fidelity human review recovery path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the canonical BodyRig high-fidelity human review recovery path."
}
if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) {
    throw "High-fidelity package not found: $PackagePath"
}
$PackagePath = (Resolve-Path -LiteralPath $PackagePath).Path

function Assert-CheckoutAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [string]$ExpectedHead = ""
    )
    $headLines = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) { throw "Could not resolve current BodyRig Git revision." }
    $head = ([string]$headLines[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "Current BodyRig Git revision is not canonical." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig checkout revision changed while invalid human-review evidence was being archived; expected $ExpectedHead, got $head."
    }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
    if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; invalid human-review recovery requires a clean checkout." }
    return $head
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$initialHead = Assert-CheckoutAuthority -RepoRoot $repoRoot
$expectedPackageSha = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()

$pythonCandidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $pythonCandidate -PathType Leaf) {
    $pythonExe = (Resolve-Path -LiteralPath $pythonCandidate).Path
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "BodyRig Python was not found. Activate the validated BodyRig environment or create .venv first."
    }
    $pythonExe = $pythonCommand.Source
}
$versionText = (& $pythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^(\d+)\.(\d+)$') {
    throw "Could not verify Python runtime for BodyRig high-fidelity human review recovery."
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    throw "BodyRig high-fidelity human review recovery requires Python 3.11+; detected $versionText."
}

$previousPythonPath = $env:PYTHONPATH
$result = $null
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    $expectedModule = (Resolve-Path (Join-Path $repoRoot "bodyrig\__init__.py")).Path
    $moduleLines = @(& $pythonExe -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $moduleLines.Count -ne 1) {
        throw "BodyRig Python could not prove imported module authority."
    }
    $actualModule = [System.IO.Path]::GetFullPath(([string]$moduleLines[0]).Trim())
    if (-not [string]::Equals($actualModule, $expectedModule, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "BodyRig Python imports bodyrig from a different checkout/package: $actualModule"
    }

    Push-Location $repoRoot
    try {
        $output = @(& $pythonExe -m bodyrig.high_fidelity_human_review_recovery_cli --package $PackagePath)
        if ($LASTEXITCODE -ne 0) {
            throw "High-fidelity human review recovery CLI failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
    $jsonText = ($output -join "`n").Trim()
    try { $result = $jsonText | ConvertFrom-Json }
    catch { throw "High-fidelity human review recovery CLI did not return canonical JSON." }

    if ($result.ok -ne $true) { throw "High-fidelity human review recovery CLI did not report success." }
    if ([string]$result.package_sha256 -ne $expectedPackageSha) { throw "Human-review recovery was bound to different package bytes." }
    if ([string]$result.receipt_sha256 -notmatch '^[0-9a-f]{64}$') { throw "Human-review recovery returned an invalid receipt SHA." }
    if ($result.production_activation -ne $false) { throw "Human-review recovery must remain non-activating." }

    $archivePath = [string]$result.archived_review_path
    $canonicalPath = [string]$result.canonical_review_path
    if ([string]::IsNullOrWhiteSpace($archivePath) -or -not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
        throw "Human-review recovery archive was not persisted at the returned path."
    }
    if (-not [string]::IsNullOrWhiteSpace($canonicalPath) -and (Test-Path -LiteralPath $canonicalPath -PathType Leaf)) {
        throw "Invalid human-review receipt still exists at its canonical path after recovery."
    }
    if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$result.receipt_sha256) {
        throw "Archived invalid human-review bytes do not match the reported receipt SHA."
    }

    [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $initialHead)
    if ((Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedPackageSha) {
        throw "High-fidelity package bytes changed during human-review recovery."
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig high-fidelity human review recovery: PASS"
Write-Host "Revision:      $initialHead"
Write-Host "Python:        $pythonExe"
Write-Host "Package SHA:   $([string]$result.package_sha256)"
Write-Host "Receipt SHA:   $([string]$result.receipt_sha256)"
Write-Host "Archived to:   $([string]$result.archived_review_path)"
Write-Host "Invalid reason: $([string]$result.invalid_reason)"
Write-Host "Production:    FALSE"
Write-Host "Next: rerun high-fidelity-physical-status.ps1 and perform a new explicit package-bound human review."
exit 0
