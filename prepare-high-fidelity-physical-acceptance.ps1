param(
    [Parameter(Mandatory = $true)][ValidatePattern('^hfpreview-[0-9a-f]{32}$')][string]$PreviewJobId
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical high-fidelity physical handoff is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the canonical high-fidelity physical handoff."
}

function Assert-CheckoutAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [string]$ExpectedHead = ""
    )
    $headLines = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) {
        throw "Could not resolve current BodyRig Git revision."
    }
    $head = ([string]$headLines[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') {
        throw "Current BodyRig Git revision is not canonical."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig checkout revision changed during physical handoff; expected $ExpectedHead, got $head."
    }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not verify BodyRig checkout cleanliness."
    }
    if ($dirty.Count -gt 0) {
        throw "BodyRig checkout is dirty; physical handoff requires an exact clean checkout."
    }
    return $head
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Assert-CheckoutAuthority -RepoRoot $repoRoot

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) {
    throw "Python 3.11+ executable 'python' was not found. Run this from the validated BodyRig operator environment."
}
$pythonExe = $pythonCommand.Source
$versionText = (& $pythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^(\d+)\.(\d+)$') {
    throw "Could not verify Python runtime for high-fidelity physical handoff."
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    throw "BodyRig high-fidelity physical handoff requires Python 3.11+; detected $versionText."
}

$expectedModule = (Resolve-Path (Join-Path $repoRoot "bodyrig\__init__.py")).Path
$moduleLines = @(& $pythonExe -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $moduleLines.Count -ne 1) {
    throw "BodyRig Python could not prove imported module authority."
}
$actualModule = [System.IO.Path]::GetFullPath(([string]$moduleLines[0]).Trim())
if (-not [string]::Equals($actualModule, $expectedModule, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports bodyrig from a different checkout/package: $actualModule"
}

$previousPythonPath = $env:PYTHONPATH
$result = $null
$createdAcceptance = ""
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    Push-Location $repoRoot
    try {
        $output = @(& $pythonExe -m bodyrig.high_fidelity_physical_acceptance `
            --preview-job-id $PreviewJobId `
            --bodyrig-revision $head)
        if ($LASTEXITCODE -ne 0) {
            throw "High-fidelity physical handoff CLI failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
    $jsonText = ($output -join "`n").Trim()
    try { $result = $jsonText | ConvertFrom-Json }
    catch { throw "High-fidelity physical handoff CLI did not return canonical JSON." }

    if ([string]$result.preview_job_id -ne $PreviewJobId) {
        throw "Physical handoff CLI returned a different preview job id."
    }
    if ([string]$result.bodyrig_revision -ne $head) {
        throw "Physical handoff CLI returned a different BodyRig revision."
    }
    if ([string]$result.package_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Physical handoff CLI returned an invalid package SHA."
    }
    if ([string]$result.next_gate -ne "windows-probe") {
        throw "Fresh promoted-package Gate A did not stop at Windows physical probe."
    }
    if ($result.production_activation -ne $false) {
        throw "Physical handoff must remain non-activating."
    }
    $createdAcceptance = [string]$result.acceptance_dir
    if ([string]::IsNullOrWhiteSpace($createdAcceptance) -or -not (Test-Path -LiteralPath $createdAcceptance -PathType Container)) {
        throw "Physical handoff acceptance directory was not persisted."
    }

    try {
        [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head)
    } catch {
        if (-not [string]::IsNullOrWhiteSpace($createdAcceptance) -and (Test-Path -LiteralPath $createdAcceptance -PathType Container)) {
            Remove-Item -LiteralPath $createdAcceptance -Recurse -Force
        }
        throw "BodyRig checkout authority changed after physical handoff; removed newly-created acceptance '$createdAcceptance'. $($_.Exception.Message)"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig high-fidelity physical handoff: PASS"
Write-Host "Preview:      $PreviewJobId"
Write-Host "Revision:     $head"
Write-Host "Body:         $([string]$result.body_id)"
Write-Host "Package SHA:  $([string]$result.package_sha256)"
Write-Host "Acceptance:   $createdAcceptance"
Write-Host "Next gate:    WindowsPlayer machine + deformation probe"
Write-Host "Production:   FALSE"
if (-not [string]::IsNullOrWhiteSpace([string]$result.next_command)) {
    Write-Host "Next command:"
    Write-Host ([string]$result.next_command)
}
exit 0
