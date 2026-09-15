param(
    [Parameter(Mandatory = $true)][string]$PerformerId,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][string]$ModelRoot,
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$PathMap = "",
    [string]$BodyRigPython = "",
    [double]$EvalFraction = 0.20,
    [string]$SplitSeed = "bodyrig-photoreal-v2",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [string]$VisionDevice = "cuda:0"
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

function Write-UnexpectedFailureStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][int]$ExitCode,
        [Parameter(Mandatory = $true)][string]$CrashReceiptPath
    )
    $statusPath = Join-Path $Root "p0-status.json"
    if (Test-Path -LiteralPath $statusPath -PathType Leaf) { return }
    $payload = [ordered]@{
        format = "bodyrig-photoreal-p0-status"
        version = 1
        bodyrig_revision = $script:head
        performer_id = $PerformerId
        status = "unexpected-failure"
        teacher_training_authorized = $false
        blockers = @(
            "The isolated P0 child process failed unexpectedly with exit code $ExitCode. Partial outputs are diagnostic evidence only and grant no authority. Inspect the crash receipt: $CrashReceiptPath"
        )
        human_visual_acceptance_required = $true
        photoreal_acceptance_authority = $false
        production_activation = $false
        outputs = [ordered]@{
            source_inventory = (Join-Path $Root "source-inventory.json")
            dataset_plan = (Join-Path $Root "dataset-plan.json")
            source_receipt = (Join-Path $Root "source-receipt.json")
            scan_plan = (Join-Path $Root "scan-plan.json")
            identity_bootstrap = (Join-Path $Root "identity-bootstrap-plan.json")
            model_set = (Join-Path $Root "model-set.json")
            identity_bank = (Join-Path $Root "identity-bank.json")
            identity_negative_inventory = (Join-Path $Root "identity-negative-inventory.json")
            identity_negative_receipt = (Join-Path $Root "identity-negative-receipt.json")
            identity_calibration_plan = (Join-Path $Root "identity-calibration-plan.json")
            identity_calibration = (Join-Path $Root "identity-calibration.json")
            frame_measurements = (Join-Path $Root "frame-measurements.json")
            frame_authorized_observations = (Join-Path $Root "frame-authorized-observations.json")
            frame_index = (Join-Path $Root "frame-index.json")
        }
    }
    $payload | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $statusPath -Encoding UTF8
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$runner = Need-File -Path (Join-Path $repoRoot "run-photoreal-p0-windows.ps1") -Label "Photoreal P0 runner"
$adapter = Need-File -Path (Join-Path $repoRoot "tools\photoreal_reference_vision_adapter.py") -Label "Photoreal reference vision adapter"
$probe = Need-File -Path (Join-Path $repoRoot "tools\photoreal_reference_vision_probe.py") -Label "Photoreal reference vision probe"
$pwsh = Need-File -Path (Join-Path $PSHOME "pwsh.exe") -Label "PowerShell 7 executable"
$ModelRoot = Need-Directory -Path $ModelRoot -Label "Photoreal reference vision model root"

$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Photoreal reference P0 requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $localPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $localPython -PathType Leaf) {
        $BodyRigPython = (Resolve-Path -LiteralPath $localPython).Path
    } else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $command) { throw "BodyRig Python was not found." }
        $BodyRigPython = $command.Source
    }
} else {
    $BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
}

if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "WSL distribution is required." }
if ([string]::IsNullOrWhiteSpace($LinuxPython) -or -not $LinuxPython.StartsWith('/')) {
    throw "LinuxPython must be an absolute Linux path."
}
if ($VisionDevice -notin @("cpu", "cuda", "cuda:0")) { throw "VisionDevice must be cpu, cuda or cuda:0." }

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-photoreal-reference-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
$identityConfig = Join-Path $tempRoot "identity-extractor.json"
$frameConfig = Join-Path $tempRoot "frame-analyzer.json"

$priorPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($priorPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$priorPythonPath" })

    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - REFERENCE P0"
    Write-Host "Revision:          $head"
    Write-Host "Performer:         $PerformerId"
    Write-Host "Output:            $OutputRoot"
    Write-Host "Vision model root: $ModelRoot"
    Write-Host "WSL:               $Distribution"
    Write-Host "Vision device:     $VisionDevice"
    Write-Host "Reconstruction:    FALSE"
    Write-Host "Photoreal accept:  FALSE"
    Write-Host "Production:        FALSE"
    Write-Host "============================================================"

    Write-Host ""
    Write-Host "=== PRE-P0 PINNED VISION STACK PREFLIGHT ==="
    $preflightOutput = @(& $BodyRigPython -m bodyrig.photoreal_reference_vision_preflight `
        --adapter-path $adapter `
        --probe-path $probe `
        --model-root $ModelRoot `
        --distribution $Distribution `
        --linux-python $LinuxPython `
        --device $VisionDevice 2>&1)
    $preflightExit = $LASTEXITCODE
    foreach ($line in $preflightOutput) { Write-Host ([string]$line) }
    if ($preflightExit -ne 0) { throw "Photoreal reference vision preflight failed with exit code $preflightExit." }

    Write-Host ""
    Write-Host "=== GENERATE EXACT MEASUREMENT CONFIGS ==="
    $configOutput = @(& $BodyRigPython -m bodyrig.photoreal_reference_vision_config `
        --model-root $ModelRoot `
        --adapter-path $adapter `
        --windows-python $BodyRigPython `
        --distribution $Distribution `
        --linux-python $LinuxPython `
        --device $VisionDevice `
        --identity-out $identityConfig `
        --frame-out $frameConfig 2>&1)
    $configExit = $LASTEXITCODE
    foreach ($line in $configOutput) { Write-Host ([string]$line) }
    if ($configExit -ne 0) { throw "Photoreal reference vision config generation failed with exit code $configExit." }
    Need-File -Path $identityConfig -Label "Generated identity extractor config" | Out-Null
    Need-File -Path $frameConfig -Label "Generated frame analyzer config" | Out-Null

    $evalText = [string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0:0.####}", $EvalFraction)
    $runnerArgs = @(
        "-NoLogo", "-NoProfile", "-File", $runner,
        "-PerformerId", $PerformerId,
        "-OutputRoot", $OutputRoot,
        "-ApiKeyEnv", $ApiKeyEnv,
        "-BodyRigPython", $BodyRigPython,
        "-EvalFraction", $evalText,
        "-SplitSeed", $SplitSeed,
        "-ModelRoot", $ModelRoot,
        "-IdentityExtractorConfig", $identityConfig,
        "-FrameAnalyzerConfig", $frameConfig
    )
    if (-not [string]::IsNullOrWhiteSpace($StashUrl)) { $runnerArgs += @("-StashUrl", $StashUrl) }
    if (-not [string]::IsNullOrWhiteSpace($PathMap)) { $runnerArgs += @("-PathMap", $PathMap) }

    Write-Host ""
    Write-Host "=== START ISOLATED 16-STAGE P0 ==="
    & $pwsh @runnerArgs
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        Write-Host "BodyRig Photoreal reference P0 child process: PASS"
        return
    }
    if ($exitCode -eq 2) {
        throw "BodyRig Photoreal reference P0 was blocked by a fail-closed gate. Inspect '$OutputRoot\p0-status.json'."
    }

    if (Test-Path -LiteralPath $OutputRoot -PathType Container) {
        $crashReceiptPath = Join-Path $OutputRoot "p0-crash-receipt.json"
        if (-not (Test-Path -LiteralPath $crashReceiptPath)) {
            $crashMessage = "The isolated P0 child process exited unexpectedly with code $exitCode before returning a normal P0 gate result."
            $crashOutput = @(& $BodyRigPython -m bodyrig.photoreal_p0_crash_receipt_cli `
                --bodyrig-revision $head `
                --performer-id $PerformerId `
                --failed-stage-number 0 `
                --failed-stage-label "isolated-p0-child-process" `
                --error-message $crashMessage `
                --output-root $OutputRoot `
                --output $crashReceiptPath 2>&1)
            $crashExit = $LASTEXITCODE
            foreach ($line in $crashOutput) { Write-Host ([string]$line) }
            if ($crashExit -ne 0) {
                Write-Warning "Could not write the Photoreal P0 crash receipt; receipt CLI exited with code $crashExit."
            }
        }
        Write-UnexpectedFailureStatus -Root $OutputRoot -ExitCode $exitCode -CrashReceiptPath $crashReceiptPath
        throw "BodyRig Photoreal reference P0 failed unexpectedly with exit code $exitCode. Inspect '$OutputRoot\p0-status.json' and '$crashReceiptPath'. Do not reuse partial outputs as authority; rerun with a new empty output root after fixing the cause."
    }

    throw "BodyRig Photoreal reference P0 failed unexpectedly with exit code $exitCode before creating its output root. Fix the cause and run again with a new empty output root."
} finally {
    $env:PYTHONPATH = $priorPythonPath
    if (Test-Path -LiteralPath $tempRoot -PathType Container) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
