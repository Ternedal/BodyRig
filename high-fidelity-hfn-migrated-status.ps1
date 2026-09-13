param(
    [Parameter(Mandatory = $true)][ValidatePattern('^hfpreview-[0-9a-f]{32}$')][string]$PreviewJobId,
    [string]$Serial = '',
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7+ (pwsh) is required.' }
$repoRoot = (Resolve-Path $PSScriptRoot).Path
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
        throw "Migrated HFN status imported BodyRig from another checkout: $actualModule"
    }

    $argsList = @(
        '-m', 'bodyrig.high_fidelity_hfn_migrated_readiness_cli',
        '--preview-job-id', $PreviewJobId,
        '--operator-root', $repoRoot
    )
    if (-not [string]::IsNullOrWhiteSpace($Serial)) { $argsList += @('--quest-serial', $Serial) }
    if ($Json) { $argsList += '--json' }
    Push-Location $repoRoot
    try {
        & $pythonExe @argsList
        $exitCode = $LASTEXITCODE
    } finally { Pop-Location }
} finally {
    if ([string]::IsNullOrEmpty($previousPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $previousPythonPath }
}
exit $exitCode
