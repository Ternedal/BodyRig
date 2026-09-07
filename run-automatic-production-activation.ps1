param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$UnityExe = "",
    [string]$AdbExe = "",
    [string]$Serial = "",
    [string]$Output = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [IO.Path]::GetFullPath($AcceptanceDir)
$gateA = Join-Path $AcceptanceDir "bodyrig-acceptance.json"
if (-not (Test-Path -LiteralPath $gateA -PathType Leaf)) {
    throw "Gate A acceptance is missing: $gateA. Complete the existing automatic physical clone/Gate A path first."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $BodyRigPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $BodyRigPython -PathType Leaf)) {
    throw "BodyRig Python not found: $BodyRigPython"
}
$BodyRigPython = (Resolve-Path -LiteralPath $BodyRigPython).Path
$expectedModule = (Resolve-Path -LiteralPath (Join-Path $repoRoot "bodyrig\__init__.py")).Path
$actualModuleRaw = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $actualModuleRaw.Count -ne 1) {
    throw "BodyRig Python could not prove a single checkout-bound bodyrig import for automatic activation."
}
$actualModulePath = ([string]$actualModuleRaw[0]).Trim()
if (-not (Test-Path -LiteralPath $actualModulePath -PathType Leaf)) {
    throw "BodyRig Python returned an invalid bodyrig import path for automatic activation."
}
$actualModule = (Resolve-Path -LiteralPath $actualModulePath).Path
if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports bodyrig from unexpected location: $actualModule. Expected checkout authority: $expectedModule"
}

$releaseOutput = if ([string]::IsNullOrWhiteSpace($Output)) {
    Join-Path $AcceptanceDir "bodyrig-release-acceptance.json"
} else {
    [IO.Path]::GetFullPath($Output)
}

$windows = Join-Path $repoRoot "run-automatic-reference-windows-proof.ps1"
$quest = Join-Path $repoRoot "run-automatic-reference-quest-proof.ps1"
$complete = Join-Path $repoRoot "complete-automatic-reference-acceptance.ps1"
foreach ($requiredScript in @($windows, $quest, $complete)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "Required automatic production script missing: $requiredScript"
    }
}

function Get-AutomaticActivationStatus {
    $statusArgs = @(
        "-m", "bodyrig.automatic_activation_status",
        "--acceptance-dir", $AcceptanceDir,
        "--repo-root", $repoRoot,
        "--release-output", $releaseOutput,
        "--json"
    )
    $raw = @(& $BodyRigPython @statusArgs 2>&1)
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Automatic activation status failed: $($raw -join [Environment]::NewLine)"
    }
    if ($raw.Count -ne 1) {
        throw "Automatic activation status returned unexpected output: $($raw -join [Environment]::NewLine)"
    }
    try { return ([string]$raw[0]) | ConvertFrom-Json }
    catch { throw "Automatic activation status returned invalid JSON: $($raw[0])" }
}

Write-Host "BodyRig resumable automatic production activation"
Write-Host "Acceptance: $AcceptanceDir"
Write-Host "Release:    $releaseOutput"

for ($transition = 0; $transition -lt 4; $transition++) {
    $status = Get-AutomaticActivationStatus
    $stage = [string]$status.stage
    Write-Host "Automatic stage: $stage | $([string]$status.message)"

    if ([string]$status.state -eq "complete" -and $stage -eq "complete") {
        Write-Host "BODYRIG AUTOMATIC PRODUCTION ACTIVATION: PASS"
        Write-Host "production_activation=true"
        Write-Host "Release receipt: $releaseOutput"
        exit 0
    }

    switch ($stage) {
        "windows" {
            $windowsArgs = @{ AcceptanceDir = $AcceptanceDir }
            if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $windowsArgs.UnityExe = $UnityExe }
            & $windows @windowsArgs
            if ($LASTEXITCODE -ne 0) { throw "Automatic Windows proof failed." }
        }
        "quest" {
            $questArgs = @{ AcceptanceDir = $AcceptanceDir; BodyRigPython = $BodyRigPython }
            if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $questArgs.UnityExe = $UnityExe }
            if (-not [string]::IsNullOrWhiteSpace($AdbExe)) { $questArgs.AdbExe = $AdbExe }
            if (-not [string]::IsNullOrWhiteSpace($Serial)) { $questArgs.Serial = $Serial }
            & $quest @questArgs
            if ($LASTEXITCODE -ne 0) { throw "Automatic Quest proof failed." }
        }
        "quest-quality" {
            $questArgs = @{ AcceptanceDir = $AcceptanceDir; BodyRigPython = $BodyRigPython }
            if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $questArgs.UnityExe = $UnityExe }
            if (-not [string]::IsNullOrWhiteSpace($AdbExe)) { $questArgs.AdbExe = $AdbExe }
            if (-not [string]::IsNullOrWhiteSpace($Serial)) { $questArgs.Serial = $Serial }
            & $quest @questArgs
            if ($LASTEXITCODE -ne 0) { throw "Automatic Quest quality recovery failed." }
        }
        "release" {
            $completeArgs = @{ AcceptanceDir = $AcceptanceDir; Output = $releaseOutput; BodyRigPython = $BodyRigPython }
            & $complete @completeArgs
            if ($LASTEXITCODE -ne 0) { throw "Automatic final production gate failed." }
        }
        default {
            throw "Unsupported automatic activation stage: $stage"
        }
    }

    $after = Get-AutomaticActivationStatus
    if ([string]$after.stage -eq $stage -and [string]$after.state -ne "complete") {
        throw "Automatic activation action did not advance stage '$stage'; refusing an unbounded retry."
    }
}

throw "Automatic production activation exceeded the bounded stage transition count."
