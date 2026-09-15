param(
    [Parameter(Mandatory = $true)][string]$PerformerId,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$ModelRoot = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$PathMap = "",
    [string]$BodyRigPython = "",
    [double]$EvalFraction = 0.20,
    [string]$SplitSeed = "bodyrig-photoreal-v2",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [string]$VisionDevice = "cuda:0",
    [switch]$AcceptInsightFaceResearchLicense,
    [switch]$RepairReferenceModels,
    [switch]$RepairReferenceEnvironment
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 }
    catch { throw "$Label is unreadable JSON: $Path" }
}

function Test-NumericV1 {
    param([AllowNull()]$Value)
    if ($null -eq $Value -or $Value -is [bool]) { return $false }
    try { $typeCode = [Type]::GetTypeCode($Value.GetType()) } catch { return $false }
    $numericTypes = @([TypeCode]::Byte,[TypeCode]::Decimal,[TypeCode]::Double,[TypeCode]::Int16,[TypeCode]::Int32,[TypeCode]::Int64,[TypeCode]::SByte,[TypeCode]::Single,[TypeCode]::UInt16,[TypeCode]::UInt32,[TypeCode]::UInt64)
    if ($numericTypes -notcontains $typeCode) { return $false }
    $number = [double]$Value
    return (-not [double]::IsNaN($number)) -and (-not [double]::IsInfinity($number)) -and $number -eq 1.0
}

function Test-StrictBoolean {
    param([AllowNull()]$Value,[Parameter(Mandatory = $true)][bool]$Expected)
    return ($Value -is [bool]) -and ($Value -eq $Expected)
}

function Invoke-OperatorProbe {
    param([Parameter(Mandatory = $true)][string]$Label,[Parameter(Mandatory = $true)][scriptblock]$Command)
    $output = @(& $Command 2>&1)
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        $detail = (($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine).Trim()
        if ([string]::IsNullOrWhiteSpace($detail)) { $detail = "no diagnostic output" }
        throw "$Label failed before P0 output creation (exit $code): $detail"
    }
    return @($output)
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$modelSetup = Need-File -Path (Join-Path $repoRoot "setup-photoreal-reference-models.ps1") -Label "Photoreal model setup"
$wslSetup = Need-File -Path (Join-Path $repoRoot "setup-photoreal-reference-wsl.ps1") -Label "Photoreal WSL setup"
$runner = Need-File -Path (Join-Path $repoRoot "run-photoreal-p0-reference-windows.ps1") -Label "Photoreal reference P0 runner"

$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Photoreal V2 reference entrypoint requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($PerformerId)) { throw "PerformerId is required." }
if ([string]::IsNullOrWhiteSpace($OutputRoot)) { throw "OutputRoot is required." }
if ($EvalFraction -lt 0.10 -or $EvalFraction -gt 0.40) { throw "EvalFraction must be in 0.10..0.40." }
if ([string]::IsNullOrWhiteSpace($SplitSeed)) { throw "SplitSeed is required." }
if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "WSL distribution is required." }
if ([string]::IsNullOrWhiteSpace($LinuxPython) -or -not $LinuxPython.StartsWith('/')) { throw "LinuxPython must be an absolute Linux path." }
if ($VisionDevice -notin @("cpu", "cuda", "cuda:0")) { throw "VisionDevice must be cpu, cuda or cuda:0." }
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $OutputRoot) { throw "Photoreal P0 output root already exists: $OutputRoot. Use a new empty output root for every P0 attempt." }
if ([string]::IsNullOrWhiteSpace($ApiKeyEnv)) { throw "ApiKeyEnv is required." }
if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($ApiKeyEnv))) { throw "Stash API key environment variable '$ApiKeyEnv' is missing in this PowerShell process." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $localPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $localPython -PathType Leaf) { $BodyRigPython = (Resolve-Path -LiteralPath $localPython).Path }
    else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $pythonCommand) { throw "BodyRig Python was not found. Create .venv or pass -BodyRigPython explicitly." }
        $BodyRigPython = $pythonCommand.Source
    }
} else { $BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python" }

$wslCommand = Get-Command wsl.exe -ErrorAction SilentlyContinue
if ($null -eq $wslCommand) { throw "wsl.exe was not found. Install/enable WSL before starting Photoreal P0." }
$distributions = Invoke-OperatorProbe -Label "WSL distribution discovery" -Command { & $wslCommand.Source -l -q }
$distributionNames = @($distributions | ForEach-Object { ([string]$_).Trim().Trim([char]0) } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
if ($Distribution -notin $distributionNames) { throw "WSL distribution '$Distribution' is not installed. Installed distributions: $($distributionNames -join ', ')" }
Invoke-OperatorProbe -Label "WSL Linux Python probe" -Command { & $wslCommand.Source -d $Distribution -- $LinuxPython -c "import sys; print(sys.executable)" } | Out-Null
if ($VisionDevice -ne "cpu") {
    Invoke-OperatorProbe -Label "WSL NVIDIA GPU probe" -Command { & $wslCommand.Source -d $Distribution -- nvidia-smi -L } | Out-Null
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required on Windows." }
if ([string]::IsNullOrWhiteSpace($ModelRoot)) { $ModelRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\reference-models" }
$ModelRoot = [IO.Path]::GetFullPath($ModelRoot)
$manifestPath = Join-Path $ModelRoot "bodyrig-reference-vision-v1.json"
$provenancePath = Join-Path $ModelRoot "source-provenance.json"
$runtimeReceiptPath = Join-Path $ModelRoot "runtime-environment.json"
$modelReady = (Test-Path -LiteralPath $manifestPath -PathType Leaf) -and (Test-Path -LiteralPath $provenancePath -PathType Leaf)
if ($RepairReferenceModels -or -not $modelReady) {
    if ((Test-Path -LiteralPath $ModelRoot) -and -not $RepairReferenceModels -and -not $modelReady) { throw "Photoreal reference model root exists but is incomplete: $ModelRoot. Re-run with -RepairReferenceModels after reviewing the model license." }
    if (-not $AcceptInsightFaceResearchLicense) { throw "First-time/reference-model repair requires explicit -AcceptInsightFaceResearchLicense after you have reviewed and accepted the buffalo_l research/non-commercial model license." }
    $modelArgs = @{ ModelRoot = $ModelRoot; AcceptInsightFaceResearchLicense = $true }
    if ($RepairReferenceModels -and (Test-Path -LiteralPath $ModelRoot)) { $modelArgs.Force = $true }
    & $modelSetup @modelArgs
    if ($LASTEXITCODE -ne 0) { throw "Photoreal reference model setup failed with exit code $LASTEXITCODE." }
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or -not (Test-Path -LiteralPath $provenancePath -PathType Leaf)) { throw "Photoreal reference model setup returned without a complete model root." }
    if ($RepairReferenceModels) { $RepairReferenceEnvironment = $true }
}

$runtimeReady = Test-Path -LiteralPath $runtimeReceiptPath -PathType Leaf
if ($runtimeReady -and -not $RepairReferenceEnvironment) {
    $receipt = Read-Json -Path $runtimeReceiptPath -Label "Photoreal runtime environment receipt"
    if ([string]$receipt.format -ne "bodyrig-photoreal-reference-runtime-environment" -or -not (Test-NumericV1 -Value $receipt.version)) { throw "Photoreal runtime environment receipt format/version mismatch. Re-run with -RepairReferenceEnvironment." }
    if ([string]$receipt.distribution -ne $Distribution -or [string]$receipt.linux_python -ne $LinuxPython) { throw "Photoreal runtime environment receipt targets a different WSL/Python. Re-run with -RepairReferenceEnvironment to rebuild intentionally." }
    if (-not (Test-StrictBoolean -Value $receipt.build_only -Expected $true) -or -not (Test-StrictBoolean -Value $receipt.production_activation -Expected $false)) { throw "Photoreal runtime environment receipt crossed its authority boundary." }
} else {
    $wslArgs = @{ ModelRoot = $ModelRoot; Distribution = $Distribution; LinuxPython = $LinuxPython }
    if ($RepairReferenceEnvironment) { $wslArgs.Force = $true }
    & $wslSetup @wslArgs
    if ($LASTEXITCODE -ne 0) { throw "Photoreal reference WSL setup failed with exit code $LASTEXITCODE." }
    if (-not (Test-Path -LiteralPath $runtimeReceiptPath -PathType Leaf)) { throw "Photoreal reference WSL setup returned without a runtime environment receipt." }
}

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - ONE COMMAND ENTRYPOINT"
Write-Host "Revision:          $head"
Write-Host "Performer:         $PerformerId"
Write-Host "Model root:        $ModelRoot"
Write-Host "WSL:               $Distribution"
Write-Host "Linux Python:      $LinuxPython"
Write-Host "Operator preflight: PASS"
Write-Host "Reconstruction:    FALSE"
Write-Host "Photoreal accept:  FALSE"
Write-Host "Production:        FALSE"
Write-Host "============================================================"

$runArgs = @{ PerformerId=$PerformerId; OutputRoot=$OutputRoot; ModelRoot=$ModelRoot; ApiKeyEnv=$ApiKeyEnv; EvalFraction=$EvalFraction; SplitSeed=$SplitSeed; Distribution=$Distribution; LinuxPython=$LinuxPython; VisionDevice=$VisionDevice; BodyRigPython=$BodyRigPython }
if (-not [string]::IsNullOrWhiteSpace($StashUrl)) { $runArgs.StashUrl = $StashUrl }
if (-not [string]::IsNullOrWhiteSpace($PathMap)) { $runArgs.PathMap = $PathMap }
& $runner @runArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
