param(
    [Parameter(Mandatory = $true)][string]$LeftPackage,
    [Parameter(Mandatory = $true)][string]$RightPackage,
    [Parameter(Mandatory = $true)][string]$Output,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$left = Resolve-InputFile -Path $LeftPackage -Label "Left .mrbody package"
$right = Resolve-InputFile -Path $RightPackage -Label "Right .mrbody package"
$outputPath = [IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $outputPath) { throw "A/B evidence output already exists: $outputPath" }

if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $python = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"
} else {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $python = (Resolve-Path -LiteralPath $venvPython).Path
    } else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $command) { throw "BodyRig Python not found. Pass -BodyRigPython from the rig checkout when using a separate helper worktree." }
        $python = $command.Source
    }
}

$previousPythonPath = [string]$env:PYTHONPATH
try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$previousPythonPath" })
    $resolvedModule = @(& $python -c "import pathlib,bodyrig.fidelity_ab as m; print(pathlib.Path(m.__file__).resolve())")
    if ($LASTEXITCODE -ne 0 -or $resolvedModule.Count -ne 1) { throw "Could not resolve BodyRig fidelity A/B module." }
    $modulePath = ([string]$resolvedModule[0]).Trim()
    if (-not $modulePath.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "BodyRig fidelity A/B module did not resolve from this checkout: $modulePath"
    }

    & $python -m bodyrig.fidelity_ab_cli `
        $left `
        $right `
        --require-clean-appearance-ab `
        --out $outputPath
    if ($LASTEXITCODE -ne 0) { throw "BodyRig clean appearance A/B evidence failed." }
} finally {
    if ([string]::IsNullOrEmpty($previousPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $previousPythonPath }
}

Write-Host "BodyRig clean appearance A/B: PASS"
Write-Host "Left:     $left"
Write-Host "Right:    $right"
Write-Host "Evidence: $outputPath"
Write-Host "NEXT: human visual review remains mandatory; this evidence cannot grant production activation."
exit 0
