param(
    [Parameter(Mandatory = $true)][ValidatePattern('^hfpreview-[0-9a-f]{32}$')][string]$PreviewJobId
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw 'The migrated high-fidelity physical handoff is Windows-only.'
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7+ (pwsh) is required.' }

$minimumRevision = '7196ceafbbc9d6eaf35cc561f90c18203c4e853a'
$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) { throw 'Could not resolve current BodyRig revision.' }
$head = ([string]$headLines[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw 'Current BodyRig revision is not canonical.' }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw 'Migrated physical handoff requires exact clean checkout authority.' }
& git -C $repoRoot merge-base --is-ancestor $minimumRevision $head
if ($LASTEXITCODE -ne 0) { throw "Checkout $head predates minimum safe physical handoff revision $minimumRevision." }

$pythonCandidate = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $pythonCandidate -PathType Leaf) { $pythonExe = (Resolve-Path $pythonCandidate).Path }
else {
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
        throw "Migrated physical handoff imported BodyRig from another checkout: $actualModule"
    }
    Push-Location $repoRoot
    try {
        $raw = @(& $pythonExe -m bodyrig.high_fidelity_hfn_migrated_physical_acceptance_cli `
            --preview-job-id $PreviewJobId `
            --bodyrig-revision $head)
        if ($LASTEXITCODE -ne 0) { throw 'Migrated high-fidelity physical handoff CLI failed.' }
    } finally { Pop-Location }
} finally {
    if ([string]::IsNullOrEmpty($previousPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $previousPythonPath }
}

try { $result = ($raw -join "`n") | ConvertFrom-Json }
catch { throw 'Migrated high-fidelity physical handoff CLI returned unreadable JSON.' }
if ([string]$result.bodyrig_revision -ne $head) { throw 'Fresh Gate A did not bind the current HFN integration revision.' }
if ([string]$result.next_gate -ne 'windows-probe' -or $result.production_activation -ne $false) {
    throw 'Fresh migrated Gate A crossed its expected non-activating Windows-probe boundary.'
}

Write-Host 'BodyRig migrated high-fidelity physical handoff: PASS'
Write-Host "Preview:      $PreviewJobId"
Write-Host "Revision:     $head"
Write-Host "Body:         $([string]$result.body_id)"
Write-Host "Package SHA:  $([string]$result.package_sha256)"
Write-Host "Acceptance:   $([string]$result.acceptance_dir)"
Write-Host 'Production:   FALSE'
Write-Host 'Next command:'
Write-Host ".\high-fidelity-hfn-migrated-status.ps1 -PreviewJobId '$PreviewJobId'"
exit 0
