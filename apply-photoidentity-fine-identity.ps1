param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^hfpreview-[0-9a-f]{32}$')]
    [string]$PreviewJobId,
    [Parameter(Mandatory = $true)][string]$SweepRoot,
    [Parameter(Mandatory = $true)][string]$AdapterConfig,
    [string]$BodyRigPython = ""
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
    throw "BodyRig terminal fine-identity operator is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ is required."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not establish exact BodyRig Git authority."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($head -notmatch '^[0-9a-f]{40}$' -or $LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Terminal fine-identity application requires an exact clean BodyRig checkout."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { $BodyRigPython = Need-Executable -Value "" -Fallback "python" -Label "BodyRig Python" }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$SweepRoot = Need-Directory -Path $SweepRoot -Label "PhotoIdentity sweep root"
$AdapterConfig = Need-File -Path $AdapterConfig -Label "Pinned fine-identity adapter config"

$expectedModule = (Resolve-Path (Join-Path $repoRoot "bodyrig\__init__.py")).Path
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    $moduleLines = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $moduleLines.Count -ne 1) {
        throw "BodyRig Python could not prove imported module authority."
    }
    $actualModule = [System.IO.Path]::GetFullPath(([string]$moduleLines[0]).Trim())
    if (-not [string]::Equals($actualModule, $expectedModule, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "BodyRig Python imports bodyrig from a different checkout/package: $actualModule"
    }

    Write-Host "BodyRig terminal source-grounded fine-identity application"
    Write-Host "Preview: $PreviewJobId"
    Write-Host "Operator revision: $head"
    Write-Host "Generic fallback: FALSE"
    Write-Host "Generative identity synthesis: FALSE"
    Write-Host "Human review remains required: TRUE"
    Write-Host "Production activation: FALSE"
    Write-Host ""

    $argsList = @(
        "-m", "bodyrig.photoidentity_fine_identity_operator",
        "--preview-job-id", $PreviewJobId,
        "--sweep-root", $SweepRoot,
        "--adapter-config", $AdapterConfig,
        "--operator-root", $repoRoot
    )
    Push-Location $repoRoot
    try {
        & $BodyRigPython @argsList
        if ($LASTEXITCODE -ne 0) {
            throw "Terminal fine-identity operator failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }

    Write-Host ""
    & (Join-Path $repoRoot "high-fidelity-physical-status.ps1") -PreviewJobId $PreviewJobId
    if ($LASTEXITCODE -ne 0) {
        throw "Post-application high-fidelity status failed with exit code $LASTEXITCODE."
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
