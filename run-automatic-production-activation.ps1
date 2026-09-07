param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$UnityExe = "",
    [string]$AdbExe = "",
    [string]$Serial = "",
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [IO.Path]::GetFullPath($AcceptanceDir)
$gateA = Join-Path $AcceptanceDir "bodyrig-acceptance.json"
if (-not (Test-Path -LiteralPath $gateA -PathType Leaf)) {
    throw "Gate A acceptance is missing: $gateA. Complete the existing automatic physical clone/Gate A path first."
}

$windows = Join-Path $repoRoot "run-automatic-reference-windows-proof.ps1"
$quest = Join-Path $repoRoot "run-automatic-reference-quest-proof.ps1"
$complete = Join-Path $repoRoot "complete-automatic-reference-acceptance.ps1"

$windowsArgs = @{ AcceptanceDir = $AcceptanceDir }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $windowsArgs.UnityExe = $UnityExe }
& $windows @windowsArgs
if ($LASTEXITCODE -ne 0) { throw "Automatic Windows proof failed." }

$questArgs = @{ AcceptanceDir = $AcceptanceDir }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $questArgs.UnityExe = $UnityExe }
if (-not [string]::IsNullOrWhiteSpace($AdbExe)) { $questArgs.AdbExe = $AdbExe }
if (-not [string]::IsNullOrWhiteSpace($Serial)) { $questArgs.Serial = $Serial }
& $quest @questArgs
if ($LASTEXITCODE -ne 0) { throw "Automatic Quest proof failed." }

$completeArgs = @{ AcceptanceDir = $AcceptanceDir }
if (-not [string]::IsNullOrWhiteSpace($Output)) { $completeArgs.Output = $Output }
& $complete @completeArgs
if ($LASTEXITCODE -ne 0) { throw "Automatic final production gate failed." }

Write-Host "BODYRIG AUTOMATIC PRODUCTION ACTIVATION: PASS"
Write-Host "production_activation=true"
exit 0
