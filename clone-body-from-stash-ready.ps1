param(
    [Parameter(Mandatory = $true)]
    [string]$PerformerId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId,

    [string]$Name = "",
    [string]$RigSetupReport = "",
    [string]$BodyRigPython = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$WslExe = "wsl.exe",
    [ValidateRange(1, 10)]
    [int]$MaxSources = 10,
    [ValidateRange(1, 1000)]
    [int]$SceneLimit = 200,
    [ValidateRange(1, 10)]
    [int]$MaxSegments = 10,
    [string]$TrackId = "",
    [string]$OutputDir = "",
    [string]$SessionReport = "",
    [string]$Ffmpeg = "",
    [ValidateRange(0, 2147483647)]
    [int]$SithSeed = 1337,
    [switch]$SkipObservationSelection,
    [switch]$AllowCpu,
    [switch]$AllowDirty,
    [switch]$KeepPrivateWorkspace
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

function Set-RequiredEnvironment {
    param([Parameter(Mandatory = $true)][hashtable]$Values)
    foreach ($entry in $Values.GetEnumerator()) {
        $name = [string]$entry.Key
        $value = [string]$entry.Value
        if ([string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($value)) {
            throw "Ready-rig environment contains an empty setting."
        }
        Set-Item -Path "Env:$name" -Value $value
    }
}

function Invoke-SessionCommand {
    param([Parameter(Mandatory = $true)][object[]]$Arguments, [Parameter(Mandatory = $true)][string]$Step)
    & $BodyRigPython -m bodyrig.physical_session @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The production physical BodyRig run is Windows-only. Run this launcher on the target Windows rig."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the production physical BodyRig path. Reopen the checkout in pwsh and rerun the launcher."
}
$powerShellExe = Resolve-CommandPath "pwsh"
if ($null -eq $powerShellExe) {
    throw "PowerShell 7 executable (pwsh) was not found even though the current shell reports PowerShell 7+."
}
if ($SkipObservationSelection) {
    throw "-SkipObservationSelection is diagnostics-only and is not allowed by the canonical production physical launcher. Use clone-body-from-stash.ps1 directly for diagnostics."
}
if ($AllowDirty) {
    throw "-AllowDirty is diagnostics-only and is not allowed by the canonical production physical launcher. Use clone-body-from-stash.ps1 directly for diagnostics."
}
if ($AllowCpu) {
    throw "-AllowCpu is diagnostics-only and is not allowed by the canonical production physical launcher. Canonical recovery readiness requires CUDA; use clone-body-from-stash.ps1 directly for CPU diagnostics."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not bind physical clone session to BodyRig Git HEAD."
}
$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect BodyRig Git status."
}
$checkoutClean = ($dirty.Count -eq 0)
if (-not $checkoutClean) {
    throw "BodyRig checkout is dirty; the canonical production physical launcher requires an exact clean checkout."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { $BodyRigPython = $venv }
    else { $BodyRigPython = Resolve-CommandPath "python" }
}
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) { throw "BodyRig Python not found." }
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"

$expectedBodyRigModule = Resolve-InputFile -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "BodyRig checkout module"
$bodyRigAuthorityRaw = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())")
if ($LASTEXITCODE -ne 0 -or $bodyRigAuthorityRaw.Count -ne 1) {
    throw "BodyRig Python could not prove a single checkout-bound bodyrig import before physical session start."
}
$actualBodyRigModule = Resolve-InputFile -Path ([string]$bodyRigAuthorityRaw[0]).Trim() -Label "Imported BodyRig module"
if (-not [string]::Equals($actualBodyRigModule, $expectedBodyRigModule, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports bodyrig from unexpected location: $actualBodyRigModule. Expected checkout authority: $expectedBodyRigModule"
}

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

$stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
$runSuffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$artifactBase = [string]$env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($artifactBase)) { $artifactBase = [System.IO.Path]::GetTempPath() }
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $artifactBase "BodyRig\physical-clones\$BodyId-$stamp-$runSuffix"
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)

if ([string]::IsNullOrWhiteSpace($SessionReport)) {
    $SessionReport = Join-Path $artifactBase "BodyRig\physical-clone-sessions\$BodyId-$stamp-$runSuffix.json"
}
$SessionReport = [System.IO.Path]::GetFullPath($SessionReport)
$readinessReport = [System.IO.Path]::ChangeExtension($SessionReport, "readiness.json")
$rigSetupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $RigSetupReport).Hash.ToLowerInvariant()
$checkoutCleanText = "true"

Invoke-SessionCommand -Arguments @(
    "start",
    "--out", $SessionReport,
    "--performer-id", $PerformerId,
    "--body-id", $BodyId,
    "--bodyrig-revision", $head,
    "--bodyrig-checkout-clean", $checkoutCleanText,
    "--rig-setup-sha256", $rigSetupHash
) -Step "Physical clone session start"

$startedSessionRaw = @(& $BodyRigPython -m bodyrig.physical_session validate $SessionReport)
if ($LASTEXITCODE -ne 0 -or $startedSessionRaw.Count -ne 1) {
    throw "New physical clone session failed immediate strict validation."
}
try { $startedSession = ([string]$startedSessionRaw[0]) | ConvertFrom-Json }
catch { throw "New physical clone session validator returned unreadable JSON." }
$sessionId = [string]$startedSession.session_id
$parsedSessionId = [Guid]::Empty
if (-not [Guid]::TryParse($sessionId, [ref]$parsedSessionId)) {
    throw "New physical clone session did not contain a valid session UUID."
}
$sessionId = $parsedSessionId.ToString()
if (([string]$startedSession.bodyrig_revision).ToLowerInvariant() -ne $head) {
    throw "New physical clone session revision did not match current BodyRig HEAD."
}

$sessionStage = "initializing"
$sessionPassPublished = $false
try {
    $validatedRaw = & $BodyRigPython -m bodyrig.rig_setup $RigSetupReport
    if ($LASTEXITCODE -ne 0) { throw "BodyRig rig setup report failed live validation." }
    try { $rig = $validatedRaw | ConvertFrom-Json }
    catch { throw "BodyRig rig setup validator returned unreadable JSON." }
    if ([string]$rig.format -ne "bodyrig-rig-setup" -or [int]$rig.version -ne 1) {
        throw "BodyRig rig setup report format/version mismatch after validation."
    }

    $externalPython = Resolve-InputFile -Path ([string]$rig.recovery.external_python) -Label "Recovery Python from rig setup"
    $fourDHumansRepo = [string]$rig.recovery.four_d_humans_repo
    if ([string]::IsNullOrWhiteSpace($fourDHumansRepo) -or -not (Test-Path -LiteralPath $fourDHumansRepo -PathType Container)) {
        throw "4D-Humans repository from rig setup is unavailable: $fourDHumansRepo"
    }
    $fourDHumansRepo = (Resolve-Path -LiteralPath $fourDHumansRepo).Path
    $sithReport = Resolve-InputFile -Path ([string]$rig.high_fidelity.setup_report) -Label "SiTH setup report from rig setup"

    $sithValidatedRaw = & $BodyRigPython -m bodyrig.sith_setup $sithReport
    if ($LASTEXITCODE -ne 0) { throw "Nested SiTH setup report failed live validation." }
    try { $sith = $sithValidatedRaw | ConvertFrom-Json }
    catch { throw "SiTH setup validator returned unreadable JSON." }

    Set-RequiredEnvironment -Values @{
        BODYRIG_RIG_SETUP_REPORT = $RigSetupReport
        BODYRIG_SITH_SETUP_REPORT = $sithReport
        BODYRIG_SITH_DISTRIBUTION = [string]$sith.distribution
        BODYRIG_SITH_REPO = [string]$sith.sith.repository
        BODYRIG_SITH_PYTHON = [string]$sith.sith.python
        BODYRIG_SITH_OPENPOSE_REPO = [string]$sith.openpose.repository
        BODYRIG_SITH_OPENPOSE = [string]$sith.openpose.executable
        BODYRIG_SITH_OPENPOSE_SHA256 = ([string]$sith.openpose.sha256).ToLowerInvariant()
        BODYRIG_SITH_OPENPOSE_MODELS_SHA256 = ([string]$sith.openpose.models_sha256).ToLowerInvariant()
        BODYRIG_SITH_DIFFUSION_MODEL = [string]$sith.diffusion_model.path
        BODYRIG_SITH_DIFFUSION_SHA256 = ([string]$sith.diffusion_model.sha256).ToLowerInvariant()
    }

    $readinessScript = Join-Path $repoRoot "check-rig-ready.ps1"
    if (-not (Test-Path -LiteralPath $readinessScript -PathType Leaf)) { throw "check-rig-ready.ps1 not found." }
    $readinessArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $readinessScript,
        "-RigSetupReport", $RigSetupReport,
        "-BodyRigPython", $BodyRigPython,
        "-ApiKeyEnv", $ApiKeyEnv,
        "-WslExe", $WslExe,
        "-SessionId", $sessionId,
        "-BodyRigRevision", $head,
        "-Out", $readinessReport
    )
    if (-not [string]::IsNullOrWhiteSpace($StashUrl)) { $readinessArgs += @("-StashUrl", $StashUrl) }

    Write-Host "BodyRig ready-rig Stash clone"
    Write-Host "PowerShell: $($PSVersionTable.PSVersion) | pwsh: $powerShellExe"
    Write-Host "BodyRig revision: $head"
    Write-Host "Checkout clean: $checkoutClean"
    Write-Host "Rig setup: $RigSetupReport"
    Write-Host "Performer id: $PerformerId"
    Write-Host "Body id: $BodyId"
    Write-Host "Session id: $sessionId"
    Write-Host "Session report: $SessionReport"
    Write-Host "Clone output: $OutputDir"
    Write-Host "Live readiness: checking recovery, SiTH/OpenPose source + binary + models, diffusion model and Stash"
    Write-Host ""

    $sessionStage = "readiness"
    & $powerShellExe @readinessArgs
    if ($LASTEXITCODE -ne 0) { throw "BodyRig live rig readiness failed with exit code $LASTEXITCODE; clone not started." }
    if (-not (Test-Path -LiteralPath $readinessReport -PathType Leaf)) {
        throw "BodyRig live rig readiness passed without writing its evidence report."
    }
    $readinessValidatedRaw = @(& $BodyRigPython -m bodyrig.rig_readiness $readinessReport)
    if ($LASTEXITCODE -ne 0 -or $readinessValidatedRaw.Count -ne 1) {
        throw "BodyRig live rig readiness evidence failed strict validation after publication."
    }
    try { $readinessValidated = ([string]$readinessValidatedRaw[0]) | ConvertFrom-Json }
    catch { throw "BodyRig rig readiness validator returned unreadable JSON after publication." }
    if ([string]$readinessValidated.session_id -ne $sessionId) {
        throw "BodyRig rig readiness evidence is bound to a different physical session."
    }
    if (([string]$readinessValidated.bodyrig_revision).ToLowerInvariant() -ne $head) {
        throw "BodyRig rig readiness evidence is bound to a different BodyRig revision."
    }
    $readinessRigSetupHash = ([string]$readinessValidated.rig_setup_sha256).ToLowerInvariant()
    if ($readinessRigSetupHash -ne $rigSetupHash) {
        throw "BodyRig rig setup report changed between physical session start and readiness evidence."
    }
    $currentRigSetupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $RigSetupReport).Hash.ToLowerInvariant()
    if ($currentRigSetupHash -ne $rigSetupHash) {
        throw "BodyRig rig setup report changed after readiness publication; refusing readiness binding."
    }
    $readinessHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $readinessReport).Hash.ToLowerInvariant()
    Invoke-SessionCommand -Arguments @(
        "readiness-pass",
        $SessionReport,
        "--readiness-sha256", $readinessHash
    ) -Step "Physical clone readiness evidence binding"

    $cloneScript = Join-Path $repoRoot "clone-body-from-stash.ps1"
    if (-not (Test-Path -LiteralPath $cloneScript -PathType Leaf)) { throw "clone-body-from-stash.ps1 not found." }
    $cloneArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $cloneScript,
        "-PerformerId", $PerformerId,
        "-ExternalPython", $externalPython,
        "-FourDHumansRepo", $fourDHumansRepo,
        "-BodyId", $BodyId,
        "-BodyRigPython", $BodyRigPython,
        "-ApiKeyEnv", $ApiKeyEnv,
        "-MaxSources", [string]$MaxSources,
        "-SceneLimit", [string]$SceneLimit,
        "-MaxSegments", [string]$MaxSegments,
        "-SithSeed", [string]$SithSeed,
        "-OutputDir", $OutputDir
    )
    if (-not [string]::IsNullOrWhiteSpace($Name)) { $cloneArgs += @("-Name", $Name) }
    if (-not [string]::IsNullOrWhiteSpace($StashUrl)) { $cloneArgs += @("-StashUrl", $StashUrl) }
    if (-not [string]::IsNullOrWhiteSpace($TrackId)) { $cloneArgs += @("-TrackId", $TrackId) }
    if (-not [string]::IsNullOrWhiteSpace($Ffmpeg)) { $cloneArgs += @("-Ffmpeg", $Ffmpeg) }
    if ($SkipObservationSelection) { $cloneArgs += "-SkipObservationSelection" }
    if ($KeepPrivateWorkspace) { $cloneArgs += "-KeepPrivateWorkspace" }

    Write-Host ""
    Write-Host "Live readiness: PASS"
    Write-Host "Readiness evidence: $readinessReport"
    Write-Host "Starting Stash clone pipeline."
    $sessionStage = "clone"
    & $powerShellExe @cloneArgs
    if ($LASTEXITCODE -ne 0) { throw "BodyRig Stash clone failed with exit code $LASTEXITCODE" }

    $finalHeadRaw = @(& git -C $repoRoot rev-parse HEAD)
    if ($LASTEXITCODE -ne 0 -or $finalHeadRaw.Count -ne 1) {
        throw "Could not re-check BodyRig Git HEAD after physical clone."
    }
    $finalHead = ([string]$finalHeadRaw[0]).Trim().ToLowerInvariant()
    if ($finalHead -ne $head) {
        throw "BodyRig Git HEAD changed during the physical clone session; refusing PASS evidence."
    }
    $finalDirty = @(& git -C $repoRoot status --porcelain)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not re-check BodyRig Git status after physical clone."
    }
    if ($finalDirty.Count -gt 0) {
        throw "BodyRig checkout became dirty during the physical clone session; refusing PASS evidence."
    }
    $finalRigSetupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $RigSetupReport).Hash.ToLowerInvariant()
    if ($finalRigSetupHash -ne $rigSetupHash) {
        throw "BodyRig rig setup report changed during the physical clone session; refusing PASS evidence."
    }

    Invoke-SessionCommand -Arguments @(
        "pass",
        $SessionReport,
        "--clone-output", $OutputDir
    ) -Step "Physical clone session completion"
    $sessionPassPublished = $true

    $postPassHeadRaw = @(& git -C $repoRoot rev-parse HEAD)
    if ($LASTEXITCODE -ne 0 -or $postPassHeadRaw.Count -ne 1) {
        throw "Could not re-check BodyRig Git HEAD after physical clone PASS publication."
    }
    $postPassHead = ([string]$postPassHeadRaw[0]).Trim().ToLowerInvariant()
    if ($postPassHead -ne $head) {
        throw "BodyRig Git HEAD changed after physical clone PASS publication; removing non-authoritative PASS evidence."
    }
    $postPassDirty = @(& git -C $repoRoot status --porcelain)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not re-check BodyRig Git status after physical clone PASS publication."
    }
    if ($postPassDirty.Count -gt 0) {
        throw "BodyRig checkout became dirty after physical clone PASS publication; removing non-authoritative PASS evidence."
    }
    $postPassRigSetupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $RigSetupReport).Hash.ToLowerInvariant()
    if ($postPassRigSetupHash -ne $rigSetupHash) {
        throw "BodyRig rig setup report changed after physical clone PASS publication; removing non-authoritative PASS evidence."
    }

    Write-Host ""
    Write-Host "BodyRig ready-rig Stash clone: PASS"
    Write-Host "Session evidence: $SessionReport"
    Write-Host "Readiness evidence: $readinessReport"
    Write-Host "Clone output: $OutputDir"
    exit 0
} catch {
    $original = $_
    $message = [string]$original.Exception.Message
    if ([string]::IsNullOrWhiteSpace($message)) { $message = "BodyRig physical clone failed without an error message." }
    if ($message.Length -gt 4000) { $message = $message.Substring(0, 4000) }
    if ($sessionPassPublished) {
        try {
            if (Test-Path -LiteralPath $SessionReport -PathType Leaf) {
                Remove-Item -LiteralPath $SessionReport -Force
            }
            Write-Host "BodyRig removed non-authoritative physical clone PASS evidence: $SessionReport"
        } catch {
            Write-Warning "BodyRig could not remove non-authoritative physical clone PASS evidence: $($_.Exception.Message)"
        }
    } else {
        try {
            Invoke-SessionCommand -Arguments @(
                "fail",
                $SessionReport,
                "--stage", $sessionStage,
                "--message", $message
            ) -Step "Physical clone failure evidence"
            Write-Host "BodyRig physical clone session: FAIL evidence written to $SessionReport"
        } catch {
            Write-Warning "BodyRig could not update physical clone failure evidence: $($_.Exception.Message)"
        }
    }
    throw $original
}
