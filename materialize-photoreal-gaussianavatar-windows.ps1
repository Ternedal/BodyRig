param(
    [Parameter(Mandatory = $true)][string]$ComparisonPlan,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$plan = (Resolve-Path $ComparisonPlan).Path
$tool = Join-Path $repo "tools\photoreal_gaussianavatar_materialize.py"
if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) { throw "GaussianAvatar materializer tool not found: $tool" }
if (Test-Path -LiteralPath $OutputRoot) { throw "OutputRoot already exists: $OutputRoot" }

$py = if (Test-Path (Join-Path $repo ".venv\Scripts\python.exe")) {
    (Resolve-Path (Join-Path $repo ".venv\Scripts\python.exe")).Path
} else {
    (Get-Command python).Source
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL GAUSSIANAVATAR MATERIALIZATION"
Write-Host "Comparison plan:    $plan"
Write-Host "Output:             $OutputRoot"
Write-Host "SMPL prior:         FEMALE"
Write-Host "SMPL type:          SMPL (benchmark v1)"
Write-Host "Held-out eval:      NOT DISCLOSED"
Write-Host "Original video:     NOT COPIED"
Write-Host "Photoreal authority: FALSE"
Write-Host "Production:          FALSE"
Write-Host "============================================================"

& $py -m bodyrig.photoreal_gaussianavatar_materializer_cli `
    --comparison-plan $plan `
    --workspace $OutputRoot `
    --tool $tool `
    --distribution $Distribution `
    --linux-python $LinuxPython `
    --wsl-exe $WslExe

if ($LASTEXITCODE -ne 0) {
    throw "BodyRig GaussianAvatar materialization failed with code $LASTEXITCODE"
}

Write-Host ""
Write-Host "BodyRig GaussianAvatar materialization: READY FOR INDEPENDENT PREPROCESSING"
Write-Host "Output:              $OutputRoot"
Write-Host "Held-out eval:       NOT DISCLOSED"
Write-Host "Photoreal authority: FALSE"
Write-Host "Production:          FALSE"
