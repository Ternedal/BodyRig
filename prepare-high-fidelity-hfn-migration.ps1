param(
    [Parameter(Mandatory = $true)][ValidatePattern('^hfpreview-[0-9a-f]{32}$')][string]$PreviewJobId
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw 'The canonical HFN migration operator path is Windows-only.'
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'PowerShell 7+ (pwsh) is required for HFN migration.'
}

$minimumRevision = '7196ceafbbc9d6eaf35cc561f90c18203c4e853a'
$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) { throw 'Could not resolve current BodyRig revision.' }
$head = ([string]$headLines[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw 'Current BodyRig revision is not canonical.' }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw 'HFN migration requires an exact clean BodyRig checkout.'
}
& git -C $repoRoot cat-file -e ($minimumRevision + '^{commit}') 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Current checkout does not contain the minimum HFN-safe handoff revision $minimumRevision."
}
& git -C $repoRoot merge-base --is-ancestor $minimumRevision $head
if ($LASTEXITCODE -ne 0) {
    throw "Current checkout $head predates the minimum HFN-safe handoff revision $minimumRevision."
}

$pythonCandidate = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $pythonCandidate -PathType Leaf) {
    $pythonExe = (Resolve-Path -LiteralPath $pythonCandidate).Path
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $python) { throw 'BodyRig Python was not found.' }
    $pythonExe = $python.Source
}

$previousPythonPath = [string]$env:PYTHONPATH
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    $expectedModule = (Resolve-Path (Join-Path $repoRoot 'bodyrig\__init__.py')).Path
    $moduleLines = @(& $pythonExe -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $moduleLines.Count -ne 1) { throw 'Could not prove checkout-bound BodyRig Python authority.' }
    $actualModule = [IO.Path]::GetFullPath(([string]$moduleLines[0]).Trim())
    if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
        throw "HFN migration imported BodyRig from another checkout: $actualModule"
    }

    Push-Location $repoRoot
    try {
        $raw = @(& $pythonExe -m bodyrig.high_fidelity_hfn_migration_cli `
            --preview-job-id $PreviewJobId `
            --integration-bodyrig-revision $head)
        if ($LASTEXITCODE -ne 0) { throw 'BodyRig HFN migration CLI failed.' }
    } finally {
        Pop-Location
    }
} finally {
    if ([string]::IsNullOrEmpty($previousPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $previousPythonPath }
}

try { $result = ($raw -join "`n") | ConvertFrom-Json }
catch { throw 'BodyRig HFN migration CLI returned unreadable JSON.' }
if ([string]$result.integration_bodyrig_revision -ne $head) {
    throw 'Persisted HFN migration does not bind the current integration revision.'
}
if ($result.comparison_only -ne $true -or $result.human_review_required -ne $true -or
    $result.physical_acceptance_authority -ne $false -or $result.production_activation -ne $false) {
    throw 'Persisted HFN migration crossed its review-only authority boundary.'
}

Write-Host 'BodyRig HFN migration authority: RECORDED'
Write-Host "Preview:               $PreviewJobId"
Write-Host "Source revision:       $([string]$result.source_bodyrig_revision)"
Write-Host "Integration revision:  $([string]$result.integration_bodyrig_revision)"
Write-Host "Source package SHA:    $([string]$result.source_package_sha256)"
Write-Host "Receipt:               $([string]$result.path)"
Write-Host 'Physical authority:    FALSE'
Write-Host 'Production activation: FALSE'
Write-Host 'Next command:'
Write-Host ".\high-fidelity-hfn-migrated-status.ps1 -PreviewJobId '$PreviewJobId'"
exit 0
