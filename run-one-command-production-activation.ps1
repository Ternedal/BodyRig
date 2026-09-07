param(
    [Parameter(Mandatory = $true)][string]$PerformerId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9æøå_-]{1,160}$')][string]$BodyId,
    [string]$Name = "",
    [string]$RigSetupReport = "",
    [string]$BodyRigPython = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$WslExe = "wsl.exe",
    [ValidateRange(1, 10)][int]$MaxSources = 10,
    [ValidateRange(1, 1000)][int]$SceneLimit = 200,
    [ValidateRange(1, 10)][int]$MaxSegments = 10,
    [string]$TrackId = "",
    [string]$Ffmpeg = "",
    [ValidateRange(0, 2147483647)][int]$SithSeed = 1337,
    [string]$UnityExe = "",
    [string]$AdbExe = "",
    [string]$Serial = "",
    [string]$RunRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-AtomicJson {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Value)
    $temp = "$Path.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig one-command production activation is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required."
}
if ($null -eq (Get-Command pwsh -ErrorAction SilentlyContinue)) {
    throw "PowerShell 7 executable (pwsh) was not found."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout cleanliness." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; production activation requires an exact clean checkout." }

& git -C $repoRoot fetch --quiet origin main
if ($LASTEXITCODE -ne 0) { throw "Could not refresh origin/main authority." }
$head = ([string](& git -C $repoRoot rev-parse HEAD)).Trim().ToLowerInvariant()
$originMain = ([string](& git -C $repoRoot rev-parse origin/main)).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$' -or $originMain -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve canonical BodyRig Git authority."
}
if ($head -ne $originMain) {
    throw "Checkout is not exact current origin/main. HEAD=$head origin/main=$originMain"
}

$artifactBase = [string]$env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($artifactBase)) { $artifactBase = [IO.Path]::GetTempPath() }
if ([string]::IsNullOrWhiteSpace($RunRoot)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $RunRoot = Join-Path $artifactBase "BodyRig\automatic-production\$BodyId-$stamp-$suffix"
}
$RunRoot = [IO.Path]::GetFullPath($RunRoot)
if (Test-Path -LiteralPath $RunRoot) { throw "RunRoot already exists; refusing cross-attempt reuse: $RunRoot" }
New-Item -ItemType Directory -Path $RunRoot | Out-Null

$cloneOutput = Join-Path $RunRoot "clone-output"
$sessionReport = Join-Path $RunRoot "bodyrig-physical-clone-session.json"
$acceptanceDir = Join-Path $cloneOutput "acceptance"
$finalReceipt = Join-Path $acceptanceDir "bodyrig-release-acceptance.json"
$runAuthority = Join-Path $RunRoot "run-authority.json"
$recoveryPlanPath = Join-Path $RunRoot "interrupted-fit-recovery-plan.json"
$identityRoot = Join-Path $artifactBase "BodyRig\identity-workspaces"
$identityBefore = @{}
if (Test-Path -LiteralPath $identityRoot -PathType Container) {
    Get-ChildItem -LiteralPath $identityRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $identityBefore[$_.FullName.ToLowerInvariant()] = $true
    }
}

$authority = [ordered]@{
    format = "bodyrig-one-command-production-authority"
    version = 1
    started_at = [DateTime]::UtcNow.ToString("o")
    bodyrig_revision = $head
    performer_id = $PerformerId
    requested_body_alias = $BodyId
    session_report = $sessionReport
    clone_output = $cloneOutput
    acceptance_dir = $acceptanceDir
    production_activation = $false
}
Write-AtomicJson -Path $runAuthority -Value $authority

$cloneScript = Join-Path $repoRoot "clone-body-from-stash-ready.ps1"
$acceptScript = Join-Path $repoRoot "accept-physical-clone.ps1"
$activateScript = Join-Path $repoRoot "run-automatic-production-activation.ps1"
foreach ($script in @($cloneScript, $acceptScript, $activateScript)) {
    if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { throw "Required production script missing: $script" }
}

Write-Host "BodyRig one-command production activation"
Write-Host "Revision: $head"
Write-Host "Run root: $RunRoot"
Write-Host "Performer: $PerformerId"
Write-Host "Body alias: $BodyId"
Write-Host ""

$cloneArgs = @{
    PerformerId = $PerformerId
    BodyId = $BodyId
    ApiKeyEnv = $ApiKeyEnv
    WslExe = $WslExe
    MaxSources = $MaxSources
    SceneLimit = $SceneLimit
    MaxSegments = $MaxSegments
    SithSeed = $SithSeed
    OutputDir = $cloneOutput
    SessionReport = $sessionReport
}
if (-not [string]::IsNullOrWhiteSpace($Name)) { $cloneArgs.Name = $Name }
if (-not [string]::IsNullOrWhiteSpace($RigSetupReport)) { $cloneArgs.RigSetupReport = $RigSetupReport }
if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $cloneArgs.BodyRigPython = $BodyRigPython }
if (-not [string]::IsNullOrWhiteSpace($StashUrl)) { $cloneArgs.StashUrl = $StashUrl }
if (-not [string]::IsNullOrWhiteSpace($TrackId)) { $cloneArgs.TrackId = $TrackId }
if (-not [string]::IsNullOrWhiteSpace($Ffmpeg)) { $cloneArgs.Ffmpeg = $Ffmpeg }

try {
    & $cloneScript @cloneArgs
    if ($LASTEXITCODE -ne 0) { throw "Physical Stash clone failed." }
} catch {
    $cloneFailure = $_
    try {
        $recoveryPython = $BodyRigPython
        if ([string]::IsNullOrWhiteSpace($recoveryPython)) {
            $candidatePython = Join-Path $repoRoot ".venv\Scripts\python.exe"
            if (Test-Path -LiteralPath $candidatePython -PathType Leaf) {
                $recoveryPython = $candidatePython
            } else {
                $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
                if ($null -ne $pythonCommand) { $recoveryPython = $pythonCommand.Source }
            }
        }
        if ([string]::IsNullOrWhiteSpace($recoveryPython) -or -not (Test-Path -LiteralPath $recoveryPython -PathType Leaf)) {
            throw "BodyRig Python is unavailable for interrupted-fit assessment"
        }
        $recoveryPython = (Resolve-Path -LiteralPath $recoveryPython).Path
        $expectedModule = (Resolve-Path -LiteralPath (Join-Path $repoRoot "bodyrig\__init__.py")).Path
        $actualModuleRaw = @(& $recoveryPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())")
        if ($LASTEXITCODE -ne 0 -or $actualModuleRaw.Count -ne 1) {
            throw "could not prove checkout-bound BodyRig Python for interrupted-fit assessment"
        }
        $actualModule = (Resolve-Path -LiteralPath ([string]$actualModuleRaw[0]).Trim()).Path
        if (-not [string]::Equals($actualModule, $expectedModule, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "interrupted-fit assessment Python is not bound to this checkout"
        }
        if (-not (Test-Path -LiteralPath $sessionReport -PathType Leaf) -or -not (Test-Path -LiteralPath $cloneOutput -PathType Container)) {
            throw "failed clone did not preserve the session/clone-output authority required for fit recovery"
        }

        $newIdentityWorkspaces = @()
        if (Test-Path -LiteralPath $identityRoot -PathType Container) {
            $newIdentityWorkspaces = @(Get-ChildItem -LiteralPath $identityRoot -Directory -ErrorAction SilentlyContinue | Where-Object {
                -not $identityBefore.ContainsKey($_.FullName.ToLowerInvariant()) -and
                -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)
            })
        }
        $matches = @()
        foreach ($workspace in $newIdentityWorkspaces) {
            $planRaw = @(& $recoveryPython -m bodyrig.interrupted_fit_recovery plan `
                --failed-session $sessionReport `
                --clone-output $cloneOutput `
                --identity-workspace $workspace.FullName `
                --current-revision $head 2>$null)
            if ($LASTEXITCODE -ne 0 -or $planRaw.Count -ne 1) { continue }
            try { $plan = ([string]$planRaw[0]) | ConvertFrom-Json }
            catch { continue }
            if ([string]$plan.format -ne "bodyrig-interrupted-fit-recovery-plan" -or [int]$plan.version -ne 1) { continue }
            if (([string]$plan.bodyrig_revision).ToLowerInvariant() -ne $head) { continue }
            if ([string]$plan.performer_id -ne $PerformerId -or [string]$plan.body_alias -ne $BodyId) { continue }
            $matches += [pscustomobject]@{ Workspace = $workspace.FullName; Plan = $plan }
        }

        if ($matches.Count -eq 1) {
            if (Test-Path -LiteralPath $recoveryPlanPath) { throw "interrupted recovery plan output already exists" }
            $matches[0].Plan | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $recoveryPlanPath -Encoding UTF8
            $planHash = (Get-FileHash -LiteralPath $recoveryPlanPath -Algorithm SHA256).Hash.ToLowerInvariant()
            $authority["identity_workspace"] = [string]$matches[0].Workspace
            $authority["interrupted_fit_recovery_plan"] = $recoveryPlanPath
            $authority["interrupted_fit_recovery_plan_sha256"] = $planHash
            $authority["recovery_mode"] = [string]$matches[0].Plan.recovery_mode
            $authority["expensive_reconstruction_rerun"] = $false
            $authority["fitter_rerun"] = ([string]$matches[0].Plan.recovery_mode -eq "resume-fit-only")
            Write-AtomicJson -Path $runAuthority -Value $authority

            Write-Host ""
            Write-Warning "Physical clone failed, but reusable interrupted-fit authority was preserved."
            Write-Host "Recovery mode: $([string]$matches[0].Plan.recovery_mode)"
            Write-Host "Recovery plan: $recoveryPlanPath"
            Write-Host "Next command:"
            Write-Host (".\resume-interrupted-physical-fit.ps1 -FailedSessionReport '{0}' -CloneOutput '{1}' -IdentityWorkspace '{2}'" -f `
                $sessionReport.Replace("'", "''"), $cloneOutput.Replace("'", "''"), ([string]$matches[0].Workspace).Replace("'", "''"))
        } elseif ($matches.Count -gt 1) {
            Write-Warning "Multiple new identity workspaces validated against the same failed clone; no recovery receipt was published."
        } else {
            Write-Warning "No completed package/SiTH reconstruction authority was recoverable from the failed clone."
        }
    } catch {
        Write-Warning "Interrupted-fit assessment could not publish a recovery receipt: $($_.Exception.Message)"
    }
    throw $cloneFailure
}

if (-not (Test-Path -LiteralPath $sessionReport -PathType Leaf)) { throw "Physical clone PASS did not publish the expected session report." }

$acceptArgs = @{ SessionReport = $sessionReport }
if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $acceptArgs.BodyRigPython = $BodyRigPython }
& $acceptScript @acceptArgs
if ($LASTEXITCODE -ne 0) { throw "High-fidelity Gate A promotion failed." }
if (-not (Test-Path -LiteralPath (Join-Path $acceptanceDir "bodyrig-acceptance.json") -PathType Leaf)) {
    throw "Gate A PASS did not publish the expected acceptance report."
}

$activateArgs = @{ AcceptanceDir = $acceptanceDir; Output = $finalReceipt }
if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $activateArgs.BodyRigPython = $BodyRigPython }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $activateArgs.UnityExe = $UnityExe }
if (-not [string]::IsNullOrWhiteSpace($AdbExe)) { $activateArgs.AdbExe = $AdbExe }
if (-not [string]::IsNullOrWhiteSpace($Serial)) { $activateArgs.Serial = $Serial }
& $activateScript @activateArgs
if ($LASTEXITCODE -ne 0) { throw "Automatic Windows/Quest production gate failed." }

if (-not (Test-Path -LiteralPath $finalReceipt -PathType Leaf)) { throw "Final production receipt was not written: $finalReceipt" }
try { $release = Get-Content -LiteralPath $finalReceipt -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Final production receipt is invalid JSON: $finalReceipt" }
if ([string]$release.format -ne "bodyrig-release-acceptance" -or [int]$release.version -ne 2 -or $release.release_gate_pass -ne $true -or $release.production_activation -ne $true) {
    throw "Final receipt is not an automatic production PASS."
}
if (([string]$release.bodyrig_revision).ToLowerInvariant() -ne $head) {
    throw "Final production receipt is bound to a different BodyRig revision."
}

$finalAuthority = [ordered]@{
    format = "bodyrig-one-command-production-authority"
    version = 1
    started_at = [string]$authority.started_at
    completed_at = [DateTime]::UtcNow.ToString("o")
    bodyrig_revision = $head
    performer_id = $PerformerId
    requested_body_alias = $BodyId
    session_report = $sessionReport
    clone_output = $cloneOutput
    acceptance_dir = $acceptanceDir
    release_receipt = $finalReceipt
    production_activation = $true
}
Write-AtomicJson -Path $runAuthority -Value $finalAuthority

Write-Host ""
Write-Host "BODYRIG ONE-COMMAND PRODUCTION ACTIVATION: PASS"
Write-Host "production_activation=true"
Write-Host "Revision: $head"
Write-Host "Run authority: $runAuthority"
Write-Host "Release receipt: $finalReceipt"
exit 0