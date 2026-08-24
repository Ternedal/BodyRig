param(
    [string]$RigSetupReport = "",
    [string]$BodyRigPython = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$WslExe = "wsl.exe",
    [string]$Out = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Step
    )
    $raw = & $BodyRigPython @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" }
    return @($raw)
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { $BodyRigPython = $venv }
    else { $BodyRigPython = Resolve-CommandPath "python" }
}
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) { throw "BodyRig Python not found." }
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"

if ([string]::IsNullOrWhiteSpace($RigSetupReport)) {
    $RigSetupReport = [string][Environment]::GetEnvironmentVariable("BODYRIG_RIG_SETUP_REPORT")
}
if ([string]::IsNullOrWhiteSpace($RigSetupReport) -and -not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $candidate = Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $RigSetupReport = $candidate }
}
if ([string]::IsNullOrWhiteSpace($RigSetupReport)) {
    throw "BodyRig rig setup report is required. Run setup-rig-windows.ps1 or pass -RigSetupReport."
}
$RigSetupReport = Resolve-InputFile -Path $RigSetupReport -Label "BodyRig rig setup report"

$rigRaw = Invoke-Checked -Arguments @("-m", "bodyrig.rig_setup", $RigSetupReport) -Step "Master rig setup validation"
try { $rig = ($rigRaw -join "`n") | ConvertFrom-Json }
catch { throw "Master rig setup validator returned unreadable JSON." }

$sithReport = Resolve-InputFile -Path ([string]$rig.high_fidelity.setup_report) -Label "SiTH setup report"
$sithRaw = Invoke-Checked -Arguments @("-m", "bodyrig.sith_setup", $sithReport) -Step "SiTH setup report validation"
try { $sith = ($sithRaw -join "`n") | ConvertFrom-Json }
catch { throw "SiTH setup validator returned unreadable JSON." }

$recoveryArgs = @(
    "-m", "bodyrig.preflight_cli",
    "--python", [string]$rig.recovery.external_python,
    "--repo", [string]$rig.recovery.four_d_humans_repo,
    "--phalp-repo", [string]$rig.recovery.phalp_repo
)
Invoke-Checked -Arguments $recoveryArgs -Step "Live recovery preflight" | Out-Null

$sithArgs = @(
    "-m", "bodyrig.sith_preflight",
    "--distribution", [string]$sith.distribution,
    "--repo", [string]$sith.sith.repository,
    "--python", [string]$sith.sith.python,
    "--openpose", [string]$sith.openpose.executable,
    "--openpose-repo", [string]$sith.openpose.repository,
    "--wsl-exe", $WslExe
)
Invoke-Checked -Arguments $sithArgs -Step "Live SiTH/OpenPose preflight" | Out-Null

$modelRaw = Invoke-Checked -Arguments @(
    "-m", "bodyrig.sith_model",
    "--distribution", [string]$sith.distribution,
    "--python", [string]$sith.sith.python,
    "--model-path", [string]$sith.diffusion_model.path,
    "--wsl-exe", $WslExe
) -Step "Live diffusion model digest"
try { $model = ($modelRaw -join "`n") | ConvertFrom-Json }
catch { throw "Live diffusion model digest returned unreadable JSON." }
$expectedModelHash = ([string]$sith.diffusion_model.sha256).ToLowerInvariant()
$actualModelHash = ([string]$model.sha256).ToLowerInvariant()
if ($actualModelHash -ne $expectedModelHash) {
    throw "Live diffusion model SHA-256 mismatch: expected $expectedModelHash, got $actualModelHash"
}
if ([int64]$model.file_count -ne [int64]$sith.diffusion_model.file_count -or [int64]$model.byte_count -ne [int64]$sith.diffusion_model.byte_count) {
    throw "Live diffusion model tree counts differ from setup evidence."
}

if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = [string]$env:STASH_URL }
if ([string]::IsNullOrWhiteSpace($StashUrl)) { throw "Stash URL is required via -StashUrl or STASH_URL." }
$stashRaw = Invoke-Checked -Arguments @(
    "-m", "bodyrig.stash_cli", "health",
    "--url", $StashUrl,
    "--api-key-env", $ApiKeyEnv
) -Step "Stash GraphQL health probe"
try { $stash = ($stashRaw -join "`n") | ConvertFrom-Json }
catch { throw "Stash health probe returned unreadable JSON." }
if ($stash.ok -ne $true) { throw "Stash health probe did not report ok=true." }

$report = [ordered]@{
    format = "bodyrig-rig-readiness"
    version = 1
    rig_setup_report = $RigSetupReport
    rig_setup_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $RigSetupReport).Hash.ToLowerInvariant()
    checks = [ordered]@{
        master_setup = $true
        recovery = $true
        sith_openpose = $true
        diffusion_model = $true
        stash = $true
    }
    environment = [ordered]@{
        stash_version = [string]$stash.version
        diffusion_model_sha256 = $actualModelHash
        diffusion_model_file_count = [int64]$model.file_count
        diffusion_model_byte_count = [int64]$model.byte_count
    }
    ready = $true
}

if (-not [string]::IsNullOrWhiteSpace($Out)) {
    $Out = [System.IO.Path]::GetFullPath($Out)
    if (Test-Path -LiteralPath $Out) { throw "Readiness report output already exists: $Out" }
    $parent = Split-Path -Parent $Out
    if (-not [string]::IsNullOrWhiteSpace($parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temp = "$Out.tmp-$([Guid]::NewGuid().ToString('N'))"
    [System.IO.File]::WriteAllText($temp, ($report | ConvertTo-Json -Depth 8) + "`n", [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $Out
}

Write-Host "BodyRig rig readiness: READY"
Write-Host "Stash: $([string]$stash.version)"
Write-Host "Diffusion model SHA-256: $actualModelHash"
if (-not [string]::IsNullOrWhiteSpace($Out)) { Write-Host "Report: $Out" }
exit 0
