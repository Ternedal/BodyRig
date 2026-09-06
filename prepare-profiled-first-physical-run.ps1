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
foreach ($required in @($doctor, $profiledLauncher)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "BodyRig profiled physical preflight dependency is missing: $required"
    }
}

# Keep the existing first-run doctor as the sole readiness/source-probe authority.
# Capture its human-readable output so only the emitted production command is
# rewritten; no readiness result or physical evidence is synthesized here.
$captured = @(& $doctor -PerformerId $PerformerId -BodyId $BodyId 6>&1)
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 0 }
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
