param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [Parameter(Mandatory = $true)][string]$CompositionAuthorityDir,
    [string]$UnityExe = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig M5 physical evidence path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for canonical BodyRig M5 physical evidence."
}
if ($null -eq (Get-Command pwsh -ErrorAction SilentlyContinue)) {
    throw "PowerShell 7 executable (pwsh) was not found."
}

function Need-Revision([string]$Value, [string]$Label) {
    $normalized = $Value.ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not a canonical 40-character Git SHA." }
    return $normalized
}
function Resolve-BodyRigPython {
    $venv = Join-Path $script:RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { return (Resolve-Path -LiteralPath $venv).Path }
    return (Get-Command python -ErrorAction Stop).Source
}
function Invoke-NativeProcessWait {
    param([Parameter(Mandatory = $true)][string]$FilePath, [Parameter(Mandatory = $true)][string[]]$ArgumentList)
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.UseShellExecute = $false
    foreach ($argument in $ArgumentList) { [void]$startInfo.ArgumentList.Add($argument) }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) { throw "Failed to start Windows reference renderer: $FilePath" }
        $process.WaitForExit()
        return $process.ExitCode
    } finally { $process.Dispose() }
}

$script:RepoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [System.IO.Path]::GetFullPath($AcceptanceDir)
$CompositionAuthorityDir = [System.IO.Path]::GetFullPath($CompositionAuthorityDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Acceptance directory not found: $AcceptanceDir" }
if (-not (Test-Path -LiteralPath $CompositionAuthorityDir -PathType Container)) { throw "M4 composition authority directory not found: $CompositionAuthorityDir" }

$acceptancePath = Join-Path $AcceptanceDir "bodyrig-acceptance.json"
$runtimeManifest = Join-Path (Join-Path $AcceptanceDir "runtime") "runtime-manifest.json"
$authorityPath = Join-Path $CompositionAuthorityDir "authority.json"
$embodimentPath = Join-Path $CompositionAuthorityDir "embodiment-probe.json"
foreach ($required in @($acceptancePath, $runtimeManifest, $authorityPath, $embodimentPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required M5 evidence input missing: $required" }
}

try { $acceptance = Get-Content -LiteralPath $acceptancePath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Gate A acceptance report is not valid JSON: $acceptancePath" }
$acceptedRevision = Need-Revision ([string]$acceptance.bodyrig_revision) "acceptance.bodyrig_revision"
$currentHeadLines = @(& git -C $script:RepoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $currentHeadLines.Count -ne 1) { throw "Could not resolve current BodyRig Git revision." }
$currentHead = Need-Revision ([string]$currentHeadLines[0].Trim()) "current BodyRig HEAD"
if ($currentHead -ne $acceptedRevision) { throw "Current BodyRig checkout does not match Gate A revision; refusing M5 Windows evidence." }
$dirty = @(& git -C $script:RepoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; M5 Windows evidence requires the exact clean Gate A revision." }

$contractPath = Join-Path $script:RepoRoot "reference-renderer\renderer-contract.json"
try { $contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Reference renderer contract is not valid JSON: $contractPath" }
if ([string]$contract.format -ne "bodyrig-reference-renderer-contract" -or [int]$contract.version -ne 1) { throw "Unsupported reference renderer contract format/version." }
$rendererName = [string]$contract.renderer_name
$rendererVersion = [string]$contract.renderer_version
if ([string]::IsNullOrWhiteSpace($rendererName) -or [string]::IsNullOrWhiteSpace($rendererVersion)) { throw "Reference renderer identity is incomplete." }

$finalEvidence = Join-Path $AcceptanceDir "digital-twin-windows-evidence"
if (Test-Path -LiteralPath $finalEvidence) { throw "M5 Windows evidence is create-only: $finalEvidence" }
$attemptDir = Join-Path $AcceptanceDir (".bodyrig-m5-windows-attempt-" + [Guid]::NewGuid().ToString("N"))
$python = Resolve-BodyRigPython
$previousPythonPath = $env:PYTHONPATH
$committed = $false
try {
    $env:PYTHONPATH = $script:RepoRoot
    $imported = (& $python -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Could not import BodyRig from the operator checkout." }
    $expectedRoot = [System.IO.Path]::GetFullPath($script:RepoRoot).TrimEnd('\') + '\'
    if (-not ([System.IO.Path]::GetFullPath($imported)).StartsWith($expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Python imported BodyRig outside the current checkout: $imported"
    }

    & $python -m bodyrig.digital_twin_platform_acceptance_cli prepare `
        --composition-authority-dir $CompositionAuthorityDir `
        --acceptance-dir $AcceptanceDir `
        --platform windows-unity-univrm `
        --output-dir $attemptDir
    if ($LASTEXITCODE -ne 0) { throw "Could not create exact M5 Windows platform input." }

    $rendererRoot = Join-Path $script:RepoRoot "reference-renderer"
    $buildScript = Join-Path $rendererRoot "build-reference-renderer.ps1"
    $playerExe = Join-Path $rendererRoot "Builds\Windows\BodyRigReferenceProbe.exe"
    if (-not $SkipBuild) {
        $buildDir = Split-Path -Parent $playerExe
        if (Test-Path -LiteralPath $buildDir) { Remove-Item -LiteralPath $buildDir -Recurse -Force }
        $buildArgs = @{ Platform = "Windows"; Output = $playerExe }
        if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $buildArgs.UnityExe = $UnityExe }
        & $buildScript @buildArgs
        if ($LASTEXITCODE -ne 0) { throw "BodyRig Windows reference renderer build failed with exit code $LASTEXITCODE" }
    }
    if (-not (Test-Path -LiteralPath $playerExe -PathType Leaf)) { throw "Built Windows reference renderer not found: $playerExe" }

    $inputManifest = Join-Path $attemptDir "platform-input.json"
    $motorState = Join-Path $attemptDir "motor-state.json"
    $realization = Join-Path $attemptDir "realization.json"
    $diagnosticProbe = Join-Path $attemptDir "runtime-probe.json"
    $diagnosticDeformation = Join-Path $attemptDir "runtime-deformation-probe.json"

    Write-Host "BodyRig M5 Windows digital-twin realization"
    Write-Host "Revision:    $acceptedRevision"
    Write-Host "M4 authority: $CompositionAuthorityDir"
    Write-Host "Staging:     $attemptDir"

    $playerArgs = @(
        "--bodyrig-runtime-manifest", $runtimeManifest,
        "--bodyrig-probe-output", $diagnosticProbe,
        "--bodyrig-deformation-output", $diagnosticDeformation,
        "--bodyrig-digital-twin-input", $inputManifest,
        "--bodyrig-digital-twin-authority", $authorityPath,
        "--bodyrig-embodiment-probe", $embodimentPath,
        "--bodyrig-motor-state", $motorState,
        "--bodyrig-digital-twin-output", $realization,
        "--bodyrig-renderer-name", $rendererName,
        "--bodyrig-renderer-version", $rendererVersion,
        "--bodyrig-quit-after-probe"
    )
    $exitCode = Invoke-NativeProcessWait -FilePath $playerExe -ArgumentList $playerArgs
    if ($exitCode -ne 0) { throw "Windows player exited with non-zero code $exitCode; M5 evidence was not committed." }
    foreach ($required in @($realization, $diagnosticProbe, $diagnosticDeformation)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Windows player did not produce complete M5 physical evidence: $required" }
    }

    & $python -m bodyrig.digital_twin_platform_acceptance_cli validate `
        --composition-authority-dir $CompositionAuthorityDir `
        --acceptance-dir $AcceptanceDir `
        --platform windows-unity-univrm `
        --evidence-dir $attemptDir
    if ($LASTEXITCODE -ne 0) { throw "M5 Windows realization failed transitive readback validation." }

    Move-Item -LiteralPath $attemptDir -Destination $finalEvidence
    $committed = $true
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    if (-not $committed -and (Test-Path -LiteralPath $attemptDir -PathType Container)) {
        Remove-Item -LiteralPath $attemptDir -Recurse -Force
    }
}

Write-Host "BodyRig M5 Windows digital-twin evidence: PASS"
Write-Host "Evidence directory: $finalEvidence"
Write-Host "This is non-activating M5 machine evidence; M6 remains required."
exit 0
