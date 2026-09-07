param(
    [Parameter(Mandatory = $true)][string]$PerformerId,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$doctor = Join-Path $repoRoot "prepare-first-physical-run.ps1"
$profiledLauncher = Join-Path $repoRoot "clone-body-from-stash-profiled-ready.ps1"
$pathMapConfig = Join-Path $repoRoot "configure-stash-path-map.ps1"
foreach ($required in @($doctor, $profiledLauncher, $pathMapConfig)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "BodyRig profiled physical preflight dependency is missing: $required"
    }
}
$pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
if ($null -eq $pwsh) {
    throw "PowerShell 7 executable (pwsh) is required for isolated profiled physical preflight."
}

function Invoke-CanonicalDoctorProcess {
    $doctorArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $doctor,
        "-PerformerId", $PerformerId,
        "-BodyId", $BodyId
    )
    $output = @(& $pwsh.Source @doctorArgs 2>&1)
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) { $exitCode = 1 }
    return [pscustomobject]@{
        Output = @($output)
        ExitCode = [int]$exitCode
    }
}

# Scope path-map cache/discovery to the one performer this physical window is
# about. A cache hit is cheap; a miss discovers only this performer instead of
# scanning every Stash-bound Person profile before the canonical doctor runs.
& $pathMapConfig -PerformerId $PerformerId

# Keep the existing first-run doctor as the sole readiness/source-probe authority.
# Run it in an isolated pwsh process: the canonical doctor deliberately uses
# `exit`, so child-process isolation makes both output and exit status safe to
# inspect without letting a failed first attempt terminate this retry wrapper.
# The child inherits the performer-scoped BODYRIG_STASH_PATH_MAP environment.
$attempt = Invoke-CanonicalDoctorProcess
$captured = @($attempt.Output)
$code = [int]$attempt.ExitCode

# A recently cached mapping can remain structurally/live-share valid while the
# selected performer's Stash path layout changed. Only that narrow source-map
# failure gets one forced performer-scoped refresh and one doctor retry. Other
# readiness/auth/renderer failures remain fail-fast and are never retried here.
if ($code -ne 0) {
    $failureText = ($captured | ForEach-Object { [string]$_ }) -join "`n"
    $sourceMapRetryEligible = (
        $failureText.Contains("Selected Stash performer/source decode probe failed", [System.StringComparison]::Ordinal) -or
        $failureText.Contains("Selected Stash performer/source decode probe did not prove at least one decodable local video", [System.StringComparison]::Ordinal)
    )
    if ($sourceMapRetryEligible) {
        Write-Host "BodyRig profiled preflight: selected-source probe failed; forcing one performer-scoped Stash path-map refresh before retry."
        & $pathMapConfig -PerformerId $PerformerId -ForceRefresh
        $attempt = Invoke-CanonicalDoctorProcess
        $captured = @($attempt.Output)
        $code = [int]$attempt.ExitCode
    }
}

if ($code -ne 0) {
    foreach ($entry in $captured) { Write-Host ([string]$entry) }
    exit $code
}

$oldPrefix = ".\clone-body-from-stash-ready.ps1 "
$newPrefix = ".\clone-body-from-stash-profiled-ready.ps1 "
$rewritten = 0
foreach ($entry in $captured) {
    $line = [string]$entry
    if ($line.StartsWith($oldPrefix, [System.StringComparison]::Ordinal)) {
        $line = $newPrefix + $line.Substring($oldPrefix.Length) + " -KeepPrivateWorkspace"
        $rewritten += 1
    }
    Write-Host $line
}
if ($rewritten -ne 1) {
    throw "BodyRig profiled physical preflight expected exactly one canonical clone command from the first-run doctor; found $rewritten."
}

Write-Host "Profiled physical policy: performer metadata selects/asserts SMPL-X family and the private reconstruction workspace is retained for high-fidelity continuation."
exit 0
