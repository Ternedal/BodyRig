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

function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $normalized
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
$packageSha = (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant()
$output = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $output) {
    throw "Hands/feet/nails render output already exists; refusing cross-attempt reuse."
}
$parent = Split-Path -Parent $output
if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
    throw "Hands/feet/nails render output parent does not exist: $parent"
}
$attempt = Join-Path $parent (".bodyrig-hfn-render-" + [Guid]::NewGuid().ToString("N"))
$committed = $false

$renderScript = Join-Path $repoRoot "run-fidelity-windows-render-probe.ps1"
if (-not (Test-Path -LiteralPath $renderScript -PathType Leaf)) {
    throw "Canonical fidelity renderer wrapper is missing: $renderScript"
}

try {
    $params = @{
        PackagePath = $package
        OutputDir = $attempt
    }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $params.UnityExe = $UnityExe }
    if ($SkipBuild) { $params.SkipBuild = $true }

    & $renderScript @params
    if ($LASTEXITCODE -ne 0) { throw "Canonical fidelity renderer failed." }

    $comparisonPath = Join-Path $attempt "comparison-authority.json"
    if (-not (Test-Path -LiteralPath $comparisonPath -PathType Leaf)) {
        throw "Canonical fidelity renderer did not produce comparison-authority.json."
    }
    $comparison = Get-Content -LiteralPath $comparisonPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $expectedComparisonFields = @(
        "format","version","authority","bodyrig_revision","runtime_manifest_sha256","package_sha256",
        "physical_acceptance_authority","comparison_only","production_activation"
    )
    if (@(Compare-Object -ReferenceObject $expectedComparisonFields -DifferenceObject @($comparison.PSObject.Properties.Name)).Count -ne 0) {
        throw "M2 requires the exact validated-package comparison-authority contract."
    }
    $runtimeSha = Need-Sha256 ([string]$comparison.runtime_manifest_sha256) "comparison.runtime_manifest_sha256"
    $comparisonPackageSha = Need-Sha256 ([string]$comparison.package_sha256) "comparison.package_sha256"
    if ([string]$comparison.format -ne "bodyrig-fidelity-comparison-authority" -or [int]$comparison.version -ne 1 -or
        [string]$comparison.authority -ne "validated-package-comparison-only" -or
        [string]$comparison.bodyrig_revision -ne $revision -or
        $comparisonPackageSha -ne $packageSha -or
        $comparison.physical_acceptance_authority -ne $false -or $comparison.comparison_only -ne $true -or
        $comparison.production_activation -ne $false) {
        throw "M2 comparison authority is stale, mismatched or crossed the review-only boundary."
    }

    $snapshotRoot = Join-Path $attempt "snapshots"
    $manifest = Join-Path $snapshotRoot "hands-feet-nails-render-set.json"
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
        throw "Reference renderer did not produce the canonical hands/feet/nails detail manifest."
    }
    $value = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
    $views = @($value.snapshots | ForEach-Object { [string]$_.view })
    $expected = @("left_hand", "right_hand", "left_foot", "right_foot")
    if ([string]$value.format -ne "bodyrig-hands-feet-nails-render-set" -or [int]$value.version -ne 1 -or
        [string]$value.semantics -ne "human-review-diagnostic-not-physical-pass" -or
        (Need-Sha256 ([string]$value.package_sha256) "detail.package_sha256") -ne $packageSha -or
        @(Compare-Object -ReferenceObject $expected -DifferenceObject $views -SyncWindow 0).Count -ne 0) {
        throw "Reference renderer produced a non-canonical hands/feet/nails detail manifest."
    }
    if ([string]::IsNullOrWhiteSpace([string]$value.body_id)) {
        throw "Hands/feet/nails detail manifest has no body id."
    }

    $regionHashes = [ordered]@{}
    foreach ($snapshot in @($value.snapshots)) {
        $view = [string]$snapshot.view
        $filename = [string]$snapshot.file
        if ($filename -ne ($view + ".png") -or [int]$snapshot.width -ne 1024 -or [int]$snapshot.height -ne 1024) {
            throw "Hands/feet/nails detail snapshot metadata is non-canonical: $view"
        }
        $image = Join-Path $snapshotRoot $filename
        if (-not (Test-Path -LiteralPath $image -PathType Leaf)) { throw "Missing M2 detail snapshot: $filename" }
        $expectedSha = Need-Sha256 ([string]$snapshot.sha256) "$view snapshot SHA-256"
        $actualSha = (Get-FileHash -LiteralPath $image -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSha -ne $expectedSha) { throw "M2 detail snapshot changed after capture: $filename" }
        $regionHashes[$view] = $actualSha
    }

    $comparisonSha = (Get-FileHash -LiteralPath $comparisonPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifestSha = (Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant()
    $renderAuthority = [ordered]@{
        format = "bodyrig-hands-feet-nails-render-authority"
        version = 1
        bodyrig_revision = $revision
        body_id = [string]$value.body_id
        package_sha256 = $packageSha
        runtime_manifest_sha256 = $runtimeSha
        comparison_authority_sha256 = $comparisonSha
        render_manifest_sha256 = $manifestSha
        render_region_sha256 = $regionHashes
        comparison_only = $true
        human_review_required = $true
        production_activation = $false
    }
    $renderAuthorityPath = Join-Path $attempt "hands-feet-nails-render-authority.json"
    $renderAuthority | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $renderAuthorityPath -Encoding UTF8

    Move-Item -LiteralPath $attempt -Destination $output
    $committed = $true

    [pscustomobject]@{
        ok = $true
        bodyrig_revision = $revision
        package = $package
        output_dir = $output
        render_manifest = (Join-Path (Join-Path $output "snapshots") "hands-feet-nails-render-set.json")
        render_authority = (Join-Path $output "hands-feet-nails-render-authority.json")
        comparison_authority = (Join-Path $output "comparison-authority.json")
        production_activation = $false
    } | ConvertTo-Json -Compress
}
finally {
    if (-not $committed -and (Test-Path -LiteralPath $attempt -PathType Container)) {
        Remove-Item -LiteralPath $attempt -Recurse -Force
    }
}
