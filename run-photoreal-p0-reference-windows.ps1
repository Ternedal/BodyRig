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

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$runner = Need-File -Path (Join-Path $repoRoot "run-photoreal-p0-windows.ps1") -Label "Photoreal P0 runner"
$adapter = Need-File -Path (Join-Path $repoRoot "tools\photoreal_reference_vision_adapter.py") -Label "Photoreal reference vision adapter"
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

    $runnerArgs = @{
        PerformerId = $PerformerId
        OutputRoot = $OutputRoot
        ApiKeyEnv = $ApiKeyEnv
        BodyRigPython = $BodyRigPython
        EvalFraction = $EvalFraction
        SplitSeed = $SplitSeed
        ModelRoot = $ModelRoot
        IdentityExtractorConfig = $identityConfig
        FrameAnalyzerConfig = $frameConfig
    }
    if (-not [string]::IsNullOrWhiteSpace($StashUrl)) { $runnerArgs.StashUrl = $StashUrl }
    if (-not [string]::IsNullOrWhiteSpace($PathMap)) { $runnerArgs.PathMap = $PathMap }

    & $runner @runnerArgs
    $exitCode = $LASTEXITCODE
    exit $exitCode
} finally {
    $env:PYTHONPATH = $priorPythonPath
    if (Test-Path -LiteralPath $tempRoot -PathType Container) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
