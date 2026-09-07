param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$UnityExe = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [IO.Path]::GetFullPath($AcceptanceDir)
$inner = Join-Path $repoRoot "run-reference-windows-renderer-probe.ps1"
if (-not (Test-Path -LiteralPath $inner -PathType Leaf)) { throw "Reference Windows renderer wrapper not found: $inner" }

$previous = [Environment]::GetEnvironmentVariable("BODYRIG_AUTO_EXIT_AFTER_QUALITY", "Process")
try {
    [Environment]::SetEnvironmentVariable("BODYRIG_AUTO_EXIT_AFTER_QUALITY", "1", "Process")
    $args = @{ AcceptanceDir = $AcceptanceDir }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $args.UnityExe = $UnityExe }
    & $inner @args
    if ($LASTEXITCODE -ne 0) { throw "Reference Windows renderer probe failed with exit code $LASTEXITCODE." }
} finally {
    [Environment]::SetEnvironmentVariable("BODYRIG_AUTO_EXIT_AFTER_QUALITY", $previous, "Process")
}

$qualityPath = Join-Path $AcceptanceDir "windows-evidence\windows-deformation-quality.json"
if (-not (Test-Path -LiteralPath $qualityPath -PathType Leaf)) { throw "Windows automatic quality receipt was not produced: $qualityPath" }
try { $quality = Get-Content -LiteralPath $qualityPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Windows automatic quality receipt is invalid JSON: $qualityPath" }
if ([string]$quality.format -ne "bodyrig-deformation-quality" -or [int]$quality.version -ne 1 -or [string]$quality.platform -ne "windows-unity-univrm" -or $quality.machine_quality_pass -ne $true -or $quality.production_activation -ne $false) {
    throw "Windows automatic quality receipt is not a valid non-activating machine PASS."
}

Write-Host "BODYRIG WINDOWS AUTOMATIC PHYSICAL PROOF: PASS"
Write-Host "Quality receipt: $qualityPath"
exit 0
