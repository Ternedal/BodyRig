param(
    [Parameter(Mandatory = $true)]
    [string]$PackagePath,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir,

    [string]$UnityExe = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path $PSScriptRoot).Path

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Hands/feet/nails render review is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for hands/feet/nails render review."
}

$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout state." }
if ($dirty.Count -gt 0) { throw "Hands/feet/nails render review requires a clean BodyRig checkout." }
$revision = (@(& git -C $repoRoot rev-parse HEAD 2>&1) | Select-Object -First 1).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve canonical BodyRig checkout revision."
}

$package = (Resolve-Path -LiteralPath $PackagePath -ErrorAction Stop).Path
if ([System.IO.Path]::GetExtension($package) -ne ".mrbody") {
    throw "Hands/feet/nails render review requires an exact .mrbody package."
}
$output = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $output) {
    throw "Hands/feet/nails render output already exists; refusing cross-attempt reuse."
}

$renderScript = Join-Path $repoRoot "run-fidelity-windows-render-probe.ps1"
if (-not (Test-Path -LiteralPath $renderScript -PathType Leaf)) {
    throw "Canonical fidelity renderer wrapper is missing: $renderScript"
}

$params = @{
    PackagePath = $package
    OutputDir = $output
}
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $params.UnityExe = $UnityExe }
if ($SkipBuild) { $params.SkipBuild = $true }

& $renderScript @params
if ($LASTEXITCODE -ne 0) { throw "Canonical fidelity renderer failed." }

$manifest = Join-Path (Join-Path $output "snapshots") "hands-feet-nails-render-set.json"
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
    throw "Reference renderer did not produce the canonical hands/feet/nails detail manifest."
}
$value = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
$views = @($value.snapshots | ForEach-Object { [string]$_.view })
$expected = @("left_hand", "right_hand", "left_foot", "right_foot")
if ([string]$value.format -ne "bodyrig-hands-feet-nails-render-set" -or [int]$value.version -ne 1 -or
    [string]$value.semantics -ne "human-review-diagnostic-not-physical-pass" -or
    @(Compare-Object -ReferenceObject $expected -DifferenceObject $views -SyncWindow 0).Count -ne 0) {
    throw "Reference renderer produced a non-canonical hands/feet/nails detail manifest."
}

[pscustomobject]@{
    ok = $true
    bodyrig_revision = $revision
    package = $package
    output_dir = $output
    render_manifest = (Resolve-Path -LiteralPath $manifest).Path
    production_activation = $false
} | ConvertTo-Json -Compress
