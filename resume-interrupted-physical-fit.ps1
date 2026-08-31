param(
    [Parameter(Mandatory = $true)][string]$FailedSessionReport,
    [Parameter(Mandatory = $true)][string]$CloneOutput,
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [string]$RigSetupReport = "",
    [string]$BodyRigPython = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$WslExe = "wsl.exe",
    [string]$RecoveredSessionReport = "",
    [string]$RecoveryReceipt = "",
    [string]$GateAOutputDir = ""
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
function Invoke-Checked {
    param([Parameter(Mandatory = $true)][string]$Executable,[Parameter(Mandatory = $true)][object[]]$Arguments,[Parameter(Mandatory = $true)][string]$Step)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" }
}
function Copy-AuthorityFile {
    param([Parameter(Mandatory = $true)][string]$Source,[Parameter(Mandatory = $true)][string]$Destination)
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { return }
    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        $sourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
        $destinationHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($sourceHash -ne $destinationHash) { throw "Recovery copy destination already exists with different bytes: $Destination" }
        return
    }
    Copy-Item -LiteralPath $Source -Destination $Destination
}
function Write-CreateOnlyJson {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)]$Value)
    if (Test-Path -LiteralPath $Path) { throw "Recovery evidence already exists: $Path" }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Interrupted physical fit recovery is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Interrupted fit recovery requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$FailedSessionReport = Need-File -Path $FailedSessionReport -Label "Failed physical clone session"
$CloneOutput = Need-Directory -Path $CloneOutput -Label "Interrupted Stash clone output"
$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Private identity workspace"

if ([string]::IsNullOrWhiteSpace($RigSetupReport)) { $RigSetupReport = [string]$env:BODYRIG_RIG_SETUP_REPORT }
if ([string]::IsNullOrWhiteSpace($RigSetupReport) -and -not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $candidate = Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $RigSetupReport = $candidate }
}
if ([string]::IsNullOrWhiteSpace($RigSetupReport)) { throw "BodyRig rig setup report is required." }
$RigSetupReport = Need-File -Path $RigSetupReport -Label "BodyRig rig setup report"
Invoke-Checked -Executable $BodyRigPython -Arguments @("-m", "bodyrig.rig_setup", $RigSetupReport) -Step "Rig setup authority validation"

if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = [string]$env:STASH_URL }
if ([string]::IsNullOrWhiteSpace($StashUrl)) { throw "Stash URL is required via -StashUrl or STASH_URL." }
if ([string]::IsNullOrWhiteSpace($ApiKeyEnv)) { throw "ApiKeyEnv is required." }
if ([string]::IsNullOrWhiteSpace([string][Environment]::GetEnvironmentVariable($ApiKeyEnv))) {
    throw "Stash API key environment variable is empty: $ApiKeyEnv"
}

$failedRaw = @(& $BodyRigPython -m bodyrig.physical_session validate $FailedSessionReport)
if ($LASTEXITCODE -ne 0 -or $failedRaw.Count -ne 1) { throw "Failed physical session did not pass strict validation." }
try { $failed = ([string]$failedRaw[0]) | ConvertFrom-Json }
catch { throw "Failed physical session validator returned unreadable JSON." }
$rigSetupHash = (Get-FileHash -LiteralPath $RigSetupReport -Algorithm SHA256).Hash.ToLowerInvariant()
if ([string]$failed.rig_setup_sha256 -ne $rigSetupHash) {
    throw "Rig setup bytes differ from the failed physical session; refusing recovery."
}

$planRaw = @(& $BodyRigPython -m bodyrig.interrupted_fit_recovery plan `
    --failed-session $FailedSessionReport `
    --clone-output $CloneOutput `
    --identity-workspace $IdentityWorkspace `
    --current-revision $head)
if ($LASTEXITCODE -ne 0 -or $planRaw.Count -ne 1) { throw "Interrupted fit recovery plan failed." }
try { $plan = ([string]$planRaw[0]) | ConvertFrom-Json }
catch { throw "Interrupted fit recovery plan returned unreadable JSON." }
if ($plan.package_already_complete -eq $true) {
    throw "Interrupted clone already contains a complete package. This recovery path only resumes an interrupted fitter; refusing to overwrite existing package bytes."
}

$planPath = Join-Path ([System.IO.Path]::GetTempPath()) ("bodyrig-interrupted-fit-plan-" + [Guid]::NewGuid().ToString("N") + ".json")
$plan | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $planPath -Encoding UTF8
try {
    if ([string]::IsNullOrWhiteSpace($RecoveredSessionReport)) {
        $RecoveredSessionReport = Join-Path $CloneOutput "physical-session-recovered.json"
    }
    $RecoveredSessionReport = [IO.Path]::GetFullPath($RecoveredSessionReport)
    if (Test-Path -LiteralPath $RecoveredSessionReport) { throw "Recovered physical session output already exists: $RecoveredSessionReport" }
    $readinessReport = [IO.Path]::ChangeExtension($RecoveredSessionReport, "readiness.json")
    if (Test-Path -LiteralPath $readinessReport) { throw "Recovered readiness output already exists: $readinessReport" }

    Invoke-Checked -Executable $BodyRigPython -Arguments @(
        "-m", "bodyrig.physical_session", "start",
        "--out", $RecoveredSessionReport,
        "--performer-id", [string]$plan.performer_id,
        "--body-id", [string]$plan.body_alias,
        "--bodyrig-revision", $head,
        "--bodyrig-checkout-clean", "true",
        "--rig-setup-sha256", $rigSetupHash
    ) -Step "Recovered physical session start"

    $startedRaw = @(& $BodyRigPython -m bodyrig.physical_session validate $RecoveredSessionReport)
    if ($LASTEXITCODE -ne 0 -or $startedRaw.Count -ne 1) { throw "Recovered physical session failed immediate validation." }
    $started = ([string]$startedRaw[0]) | ConvertFrom-Json
    $sessionId = [string]$started.session_id

    $readinessScript = Need-File -Path (Join-Path $repoRoot "check-rig-ready.ps1") -Label "Rig readiness launcher"
    $readinessArgs = @(
        "-RigSetupReport", $RigSetupReport,
        "-BodyRigPython", $BodyRigPython,
        "-ApiKeyEnv", $ApiKeyEnv,
        "-WslExe", $WslExe,
        "-SessionId", $sessionId,
        "-BodyRigRevision", $head,
        "-Out", $readinessReport,
        "-StashUrl", $StashUrl
    )
    & $readinessScript @readinessArgs
    if ($LASTEXITCODE -ne 0) { throw "Live rig readiness failed; interrupted fit was not resumed." }
    $readinessHash = (Get-FileHash -LiteralPath $readinessReport -Algorithm SHA256).Hash.ToLowerInvariant()
    Invoke-Checked -Executable $BodyRigPython -Arguments @(
        "-m", "bodyrig.physical_session", "readiness-pass",
        $RecoveredSessionReport,
        "--readiness-sha256", $readinessHash
    ) -Step "Recovered session readiness binding"

    $packagePath = [string]$plan.paths.package
    Write-Host "BodyRig interrupted SiTH fit recovery"
    Write-Host "Failed session:     $([string]$plan.failed_session_id)"
    Write-Host "Recovered session:  $sessionId"
    Write-Host "Reconstruction SHA: $([string]$plan.authority.reconstruction_sha256)"
    Write-Host "Resume mode:         same completed SiTH reconstruction; no recovery/OpenPose/SMPL-X/diffusion reconstruction rerun"
    Write-Host ""

    Invoke-Checked -Executable $BodyRigPython -Arguments @(
        "-m", "bodyrig.external_fitter_cli",
        [string]$plan.paths.proof,
        "--identity-profile", [string]$plan.paths.visual_identity,
        "--identity-workspace", [string]$plan.paths.identity_workspace,
        "--config", [string]$plan.paths.fitter_config,
        "--body-id", [string]$plan.body_alias,
        "--portable-identity", [string]$plan.paths.portable_identity,
        "--name", [string]$plan.display_name,
        "--out", $packagePath
    ) -Step "Resume interrupted SiTH fitter"

    $verifyRaw = @(& $BodyRigPython -m bodyrig.interrupted_fit_recovery verify --plan $planPath --package $packagePath)
    if ($LASTEXITCODE -ne 0 -or $verifyRaw.Count -ne 1) { throw "Recovered package/reconstruction verification failed." }
    try { $verified = ([string]$verifyRaw[0]) | ConvertFrom-Json }
    catch { throw "Recovered fit verifier returned unreadable JSON." }

    $cloneDir = [string]$plan.paths.clone_dir
    foreach ($name in @(
        "bodyrig-stash-source-manifest.json",
        "bodyrig-observation-selection.json",
        "bodyrig-observation-evidence.json"
    )) {
        Copy-AuthorityFile -Source (Join-Path $CloneOutput $name) -Destination (Join-Path $cloneDir $name)
    }

    Invoke-Checked -Executable $BodyRigPython -Arguments @(
        "-m", "bodyrig.physical_session", "pass",
        $RecoveredSessionReport,
        "--clone-output", $CloneOutput
    ) -Step "Recovered physical clone PASS publication"
    $passedRaw = @(& $BodyRigPython -m bodyrig.physical_session validate $RecoveredSessionReport)
    if ($LASTEXITCODE -ne 0 -or $passedRaw.Count -ne 1) { throw "Recovered PASS session failed strict validation." }
    $passed = ([string]$passedRaw[0]) | ConvertFrom-Json

    $failedSessionSha = (Get-FileHash -LiteralPath $FailedSessionReport -Algorithm SHA256).Hash.ToLowerInvariant()
    $recoveredSessionSha = (Get-FileHash -LiteralPath $RecoveredSessionReport -Algorithm SHA256).Hash.ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($RecoveryReceipt)) { $RecoveryReceipt = Join-Path $CloneOutput "interrupted-fit-recovery.json" }
    $RecoveryReceipt = [IO.Path]::GetFullPath($RecoveryReceipt)
    $receipt = [ordered]@{
        format = "bodyrig-interrupted-physical-fit-recovery"
        version = 1
        bodyrig_revision = $head
        performer_id = [string]$plan.performer_id
        body_alias = [string]$plan.body_alias
        failed_session_id = [string]$plan.failed_session_id
        failed_session_sha256 = $failedSessionSha
        recovered_session_id = [string]$passed.session_id
        recovered_session_sha256 = $recoveredSessionSha
        package_sha256 = [string]$verified.package_sha256
        canonical_body_id = [string]$verified.canonical_body_id
        reconstruction_authority_sha256 = [string]$verified.reconstruction_sha256
        recovery_proof_sha256 = [string]$plan.authority.recovery_proof_sha256
        visual_identity_sha256 = [string]$plan.authority.visual_identity_sha256
        portable_identity_sha256 = [string]$plan.authority.portable_identity_sha256
        fitter_config_sha256 = [string]$plan.authority.fitter_config_sha256
        source_manifest_sha256 = [string]$plan.authority.source_manifest_sha256
        expensive_reconstruction_rerun = $false
        resumed_fit_only = $true
        human_visual_authority_required = $true
        production_activation = $false
    }
    Write-CreateOnlyJson -Path $RecoveryReceipt -Value $receipt

    if (-not [string]::IsNullOrWhiteSpace($GateAOutputDir)) {
        $gateA = Need-File -Path (Join-Path $repoRoot "accept-physical-clone.ps1") -Label "Gate A launcher"
        & $gateA -SessionReport $RecoveredSessionReport -BodyRigPython $BodyRigPython -OutputDir $GateAOutputDir
        if ($LASTEXITCODE -ne 0) { throw "Recovered fit succeeded but Gate A failed operationally." }
    }

    Write-Host ""
    Write-Host "BodyRig interrupted physical fit recovery: PASS"
    Write-Host "Package:          $packagePath"
    Write-Host "Package SHA:      $([string]$verified.package_sha256)"
    Write-Host "Recovered session:$RecoveredSessionReport"
    Write-Host "Recovery receipt: $RecoveryReceipt"
    Write-Host "Reconstruction:   reused unchanged"
    if ([string]::IsNullOrWhiteSpace($GateAOutputDir)) {
        Write-Host "NEXT: run Gate A against the recovered physical session; no visual/release acceptance was created here."
    } else {
        Write-Host "Gate A output:    $GateAOutputDir"
    }
    exit 0
} finally {
    Remove-Item -LiteralPath $planPath -Force -ErrorAction SilentlyContinue
}
