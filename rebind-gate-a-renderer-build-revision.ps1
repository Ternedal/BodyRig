param(
    [Parameter(Mandatory = $true)][string]$SourceAcceptanceDir,
    [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedPackageSha256,
    [Parameter(Mandatory = $true)][string]$OutputDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$allowedDelta = @(
    "reference-renderer/Assets/BodyRig/Editor/BodyRigReferenceBuild.cs",
    "tests/test_reference_renderer_contracts.py",
    "rebind-gate-a-renderer-build-revision.ps1",
    "tests/test_renderer_build_gate_a_rebind.py"
)

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

function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    $Path = Need-File -Path $Path -Label $Label
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "$Label is not valid JSON: $Path" }
}

function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Renderer build revision rebind is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for renderer build revision rebind."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$SourceAcceptanceDir = Need-Directory -Path $SourceAcceptanceDir -Label "Source renderer-build-bound Gate A acceptance directory"
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Renderer-build-rebound Gate A output already exists; refusing cross-attempt reuse: $OutputDir" }

$headLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) { throw "Could not resolve current BodyRig HEAD." }
$head = ([string]$headLines[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "Current BodyRig HEAD is not canonical." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig Git status." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; renderer build revision rebind requires an exact clean checkout." }

$ExpectedSourceRevision = $ExpectedSourceRevision.Trim().ToLowerInvariant()
$ExpectedPackageSha256 = $ExpectedPackageSha256.Trim().ToLowerInvariant()
if ($ExpectedSourceRevision -notmatch '^[0-9a-f]{40}$') { throw "ExpectedSourceRevision must be a canonical 40-character Git SHA." }

$sourceAcceptancePath = Join-Path $SourceAcceptanceDir "bodyrig-acceptance.json"
$sourceAcceptance = Read-Json -Path $sourceAcceptancePath -Label "Source renderer-build-bound Gate A acceptance report"
$sourceVersion = $sourceAcceptance.version
if (
    [string]$sourceAcceptance.format -ne "bodyrig-rig-acceptance" -or
    $null -eq $sourceVersion -or
    $sourceVersion -is [bool] -or
    $sourceVersion -isnot [ValueType] -or
    [decimal]$sourceVersion -ne [decimal]1
) { throw "Source Gate A acceptance format/version is unsupported." }
if ($sourceAcceptance.automated_pass -ne $true -or $sourceAcceptance.production_activation -ne $false -or [string]$sourceAcceptance.physical_renderer_acceptance -ne "pending") {
    throw "Source Gate A acceptance is not a pending non-activating automated PASS."
}
if (([string]$sourceAcceptance.bodyrig_revision).ToLowerInvariant() -ne $ExpectedSourceRevision) { throw "Source Gate A revision does not match ExpectedSourceRevision." }
if (([string]$sourceAcceptance.package.package_sha256).ToLowerInvariant() -ne $ExpectedPackageSha256) { throw "Source Gate A package hash does not match ExpectedPackageSha256." }
$physicalClone = $sourceAcceptance.physical_clone
if ($null -eq $physicalClone -or [string]$physicalClone.mode -ne "stash-sith-high-fidelity") {
    throw "Source Gate A does not contain canonical Stash/SiTH high-fidelity physical-clone lineage."
}
$sourceSessionSha = ([string]$physicalClone.session_sha256).Trim().ToLowerInvariant()
$sourceReadinessSha = ([string]$physicalClone.readiness_sha256).Trim().ToLowerInvariant()
if ($sourceSessionSha -notmatch '^[0-9a-f]{64}$' -or $sourceReadinessSha -notmatch '^[0-9a-f]{64}$') {
    throw "Source Gate A physical-clone lineage is missing canonical session/readiness SHA-256 authority."
}
$sourceSessionEvidence = Need-File -Path (Join-Path $SourceAcceptanceDir "bodyrig-physical-clone-session.json") -Label "Source physical clone session evidence"
$sourceReadinessEvidence = Need-File -Path (Join-Path $SourceAcceptanceDir "bodyrig-rig-readiness.json") -Label "Source rig readiness evidence"
if ((Sha256 $sourceSessionEvidence) -ne $sourceSessionSha) { throw "Source Gate A physical clone session bytes no longer match acceptance authority." }
if ((Sha256 $sourceReadinessEvidence) -ne $sourceReadinessSha) { throw "Source Gate A readiness bytes no longer match acceptance authority." }
$rendererBuildRebindSha = ([string]$physicalClone.renderer_build_revision_rebind_sha256).Trim().ToLowerInvariant()
if ($rendererBuildRebindSha -notmatch '^[0-9a-f]{64}$') {
    throw "Source Gate A is not the renderer-build-bound acceptance expected before successive build repair."
}
$rendererBuildRebindEvidence = Need-File -Path (Join-Path $SourceAcceptanceDir "bodyrig-renderer-build-revision-rebind.json") -Label "Source renderer build revision rebind evidence"
if ((Sha256 $rendererBuildRebindEvidence) -ne $rendererBuildRebindSha) {
    throw "Source Gate A renderer build revision rebind bytes no longer match acceptance authority."
}

& git -C $repoRoot cat-file -e "$ExpectedSourceRevision^{commit}" 2>$null
if ($LASTEXITCODE -ne 0) { throw "Source renderer build revision is not present in the local Git object database." }
& git -C $repoRoot merge-base --is-ancestor $ExpectedSourceRevision $head
if ($LASTEXITCODE -ne 0) { throw "Current HEAD is not a descendant of the source renderer revision." }

$deltaLines = @(& git -C $repoRoot diff --name-status "$ExpectedSourceRevision..$head")
if ($LASTEXITCODE -ne 0) { throw "Could not inspect renderer-build revision delta." }
$deltaNames = @()
foreach ($line in $deltaLines) {
    if ([string]::IsNullOrWhiteSpace([string]$line)) { continue }
    $parts = ([string]$line) -split "`t"
    if ($parts.Count -ne 2 -or $parts[0] -notin @("A", "M")) { throw "Unsupported renderer-build rebind revision delta: $line" }
    $deltaNames += $parts[1]
}
$deltaNames = @($deltaNames | Sort-Object -Unique)
$expectedNames = @($allowedDelta | Sort-Object -Unique)
if (@(Compare-Object -ReferenceObject $expectedNames -DifferenceObject $deltaNames).Count -ne 0) {
    throw "Revision delta is broader than the approved renderer-build repair/rebind set: $($deltaNames -join ', ')"
}

$sourceRuntimePath = Need-File -Path (Join-Path (Join-Path $SourceAcceptanceDir "runtime") "runtime-manifest.json") -Label "Source runtime manifest"
$sourceRuntimeHash = Sha256 $sourceRuntimePath
if ($sourceRuntimeHash -ne ([string]$sourceAcceptance.runtime.manifest_sha256).ToLowerInvariant()) { throw "Source runtime manifest bytes no longer match Gate A acceptance." }
$sourcePackages = @(Get-ChildItem -LiteralPath $SourceAcceptanceDir -Filter "*.mrbody" -File)
if ($sourcePackages.Count -ne 1) { throw "Source Gate A must contain exactly one .mrbody package." }
if ((Sha256 $sourcePackages[0].FullName) -ne $ExpectedPackageSha256) { throw "Source Gate A .mrbody bytes do not match ExpectedPackageSha256." }

$sourceAcceptanceHash = Sha256 $sourceAcceptancePath
$parent = Split-Path -Parent $OutputDir
if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw "Renderer-build-rebound output parent does not exist: $parent" }
$attempt = Join-Path $parent (".bodyrig-renderer-build-rebind-" + [Guid]::NewGuid().ToString("N"))
$committed = $false
try {
    Copy-Item -LiteralPath $SourceAcceptanceDir -Destination $attempt -Recurse

    $copiedPackage = @(Get-ChildItem -LiteralPath $attempt -Filter "*.mrbody" -File)
    if ($copiedPackage.Count -ne 1 -or (Sha256 $copiedPackage[0].FullName) -ne $ExpectedPackageSha256) { throw "Renderer build rebind changed package bytes." }
    $copiedRuntimePath = Need-File -Path (Join-Path (Join-Path $attempt "runtime") "runtime-manifest.json") -Label "Copied runtime manifest"
    if ((Sha256 $copiedRuntimePath) -ne $sourceRuntimeHash) { throw "Renderer build rebind changed runtime-manifest bytes." }
    foreach ($payloadName in @("avatar.vrm", "bodyprint.json")) {
        $sourcePayload = Need-File -Path (Join-Path (Join-Path $SourceAcceptanceDir "runtime") $payloadName) -Label "Source runtime $payloadName"
        $copiedPayload = Need-File -Path (Join-Path (Join-Path $attempt "runtime") $payloadName) -Label "Copied runtime $payloadName"
        if ((Sha256 $sourcePayload) -ne (Sha256 $copiedPayload)) { throw "Renderer build rebind changed runtime payload bytes: $payloadName" }
    }

    $rebind = [ordered]@{
        format = "bodyrig-renderer-build-revision-rebind"
        version = 1
        created_at = [DateTime]::UtcNow.ToString("o")
        source_bodyrig_revision = $ExpectedSourceRevision
        rebound_bodyrig_revision = $head
        source_acceptance_sha256 = $sourceAcceptanceHash
        package_sha256 = $ExpectedPackageSha256
        runtime_manifest_sha256 = $sourceRuntimeHash
        approved_revision_delta = $expectedNames
        repair_scope = "reference-renderer-build-only"
        package_bytes_preserved = $true
        runtime_bytes_preserved = $true
        recovery_rerun = $false
        clone_rerun = $false
    }
    $rebindPath = Join-Path $attempt "bodyrig-renderer-build-revision-rebind.json"
    $rebind | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $rebindPath -Encoding UTF8
    $rebindHash = Sha256 $rebindPath

    $acceptancePath = Join-Path $attempt "bodyrig-acceptance.json"
    $acceptance = Read-Json -Path $acceptancePath -Label "Copied Gate A acceptance report"
    $acceptance.bodyrig_revision = $head
    $acceptance.physical_clone | Add-Member -NotePropertyName renderer_build_revision_rebind_sha256 -NotePropertyValue $rebindHash -Force
    $acceptance.physical_clone | Add-Member -NotePropertyName renderer_build_revision_source_bodyrig_revision -NotePropertyValue $ExpectedSourceRevision -Force
    $tempAcceptance = Join-Path $attempt (".bodyrig-acceptance-renderer-assembly-rebind-" + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $acceptance | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $tempAcceptance -Encoding UTF8
        Move-Item -LiteralPath $tempAcceptance -Destination $acceptancePath -Force
    } finally {
        if (Test-Path -LiteralPath $tempAcceptance) { Remove-Item -LiteralPath $tempAcceptance -Force }
    }

    $check = Read-Json -Path $acceptancePath -Label "Renderer-build-rebound Gate A acceptance report"
    if (([string]$check.bodyrig_revision).ToLowerInvariant() -ne $head) { throw "Renderer-build-rebound acceptance revision did not persist." }
    if (([string]$check.package.package_sha256).ToLowerInvariant() -ne $ExpectedPackageSha256) { throw "Renderer-build-rebound acceptance changed package identity." }
    if (([string]$check.runtime.manifest_sha256).ToLowerInvariant() -ne $sourceRuntimeHash) { throw "Renderer-build-rebound acceptance changed runtime identity." }
    if (([string]$check.physical_clone.renderer_build_revision_rebind_sha256).ToLowerInvariant() -ne $rebindHash) { throw "Renderer-build-rebound acceptance is not bound to rebind evidence." }

    Move-Item -LiteralPath $attempt -Destination $OutputDir
    $committed = $true
} finally {
    if (-not $committed -and (Test-Path -LiteralPath $attempt -PathType Container)) {
        Remove-Item -LiteralPath $attempt -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$dirtyAfter = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirtyAfter.Count -gt 0) { throw "Renderer build revision rebind did not preserve a clean BodyRig checkout." }
$currentHead = (@(& git -C $repoRoot rev-parse HEAD 2>&1)[0]).Trim().ToLowerInvariant()
if ($currentHead -ne $head) { throw "BodyRig HEAD changed during renderer build revision rebind." }

Write-Host "BodyRig renderer build revision rebind: PASS"
Write-Host "Source renderer build revision: $ExpectedSourceRevision"
Write-Host "Renderer revision:        $head"
Write-Host "Package SHA-256:          $ExpectedPackageSha256"
Write-Host "Runtime SHA-256:          $sourceRuntimeHash"
Write-Host "Output:                   $OutputDir"
Write-Host "Recovery rerun:           NO"
Write-Host "Clone rerun:              NO"
exit 0
