param(
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$DonorObj,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$InstallRoot = "",
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$cards = Join-Path $PSScriptRoot "extract-retained-hair-cards.ps1"
if (-not (Test-Path -LiteralPath $cards -PathType Leaf)) {
    throw "Source-guided hair-card operator not found: $cards"
}

& $cards @PSBoundParameters
if ($LASTEXITCODE -ne 0) {
    throw "Source-guided retained hair-card operator failed with exit code $LASTEXITCODE."
}
exit 0
