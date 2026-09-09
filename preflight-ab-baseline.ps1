param(
    [ValidatePattern('^$|^person-[0-9a-f]{32}$')]
    [string]$PersonId = "",

    [string]$PerformerId = "",

    [ValidatePattern('^https?://(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?$')]
    [string]$BaseUri = "http://127.0.0.1:8775",

    [string]$BodyRigPython = "",
    [string]$RigSetupReport = "",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$WslExe = "wsl.exe",
    [string]$Ffmpeg = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-Executable {
    param(
        [string]$Value,
        [Parameter(Mandatory = $true)][string]$Fallback,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $candidate = $(if ([string]::IsNullOrWhiteSpace($Value)) { $Fallback } else { $Value })
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        return (Resolve-Path -LiteralPath $candidate).Path
    }
    $resolved = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -eq $resolved) { throw "$Label executable not found: $candidate" }
    return $resolved.Source
}

function Invoke-CandidateAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Python,
        [string]$ExpectedMainRevision = "",
        [string]$ExpectedPbrRevision = "",
        [string]$ExpectedThroughputRevision = ""
    )

    $oldPythonPath = [string]$env:PYTHONPATH
    $oldNoBytecode = [string]$env:PYTHONDONTWRITEBYTECODE
    try {
        $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$oldPythonPath" })
        $env:PYTHONDONTWRITEBYTECODE = "1"

        $moduleRaw = @(& $Python -c "import pathlib,bodyrig.ab_baseline_candidates as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
        if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) {
            throw "Could not prove checkout-bound dual-candidate A/B validator: $($moduleRaw -join ' ')"
        }
        $expectedModule = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\ab_baseline_candidates.py"))
        $actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
        if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Dual-candidate A/B validator imported from wrong checkout: $actualModule"
        }

        $pythonArgs = @("-m", "bodyrig.ab_baseline_candidates", "--repo-root", $RepoRoot)
        if (-not [string]::IsNullOrWhiteSpace($ExpectedMainRevision)) {
            $pythonArgs += @("--expected-main-revision", $ExpectedMainRevision)
        }
        if (-not [string]::IsNullOrWhiteSpace($ExpectedPbrRevision)) {
            $pythonArgs += @("--expected-pbr-revision", $ExpectedPbrRevision)
        }
        if (-not [string]::IsNullOrWhiteSpace($ExpectedThroughputRevision)) {
            $pythonArgs += @("--expected-throughput-revision", $ExpectedThroughputRevision)
        }
        $raw = @(& $Python @pythonArgs 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) {
            throw "Dual-candidate A/B authority validation failed: $($raw -join ' ')"
        }
        try { $result = ([string]$raw[0]) | ConvertFrom-Json }
        catch { throw "Dual-candidate A/B validator returned unreadable JSON." }
        if (
            [string]$result.format -ne "bodyrig-ab-baseline-candidate-authority" -or
            [int]$result.version -ne 1 -or
            $result.comparison_only -ne $true -or
            $result.human_visual_authority_required -ne $true -or
            $result.physical_acceptance_authority -ne $false -or
            $result.promotion_authority -ne $false -or
            $result.production_activation -ne $false
        ) {
            throw "Dual-candidate A/B validator returned unexpected authority semantics."
        }
        return $result
    }
    finally {
        if ([string]::IsNullOrEmpty($oldPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
        if ([string]::IsNullOrEmpty($oldNoBytecode)) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue } else { $env:PYTHONDONTWRITEBYTECODE = $oldNoBytecode }
    }
}

function Read-ServiceAuthority {
    param([Parameter(Mandatory = $true)][string]$UriBase)
    try {
        $health = Invoke-RestMethod -Method Get -Uri "$UriBase/api/v1/health" -TimeoutSec 3
    }
    catch {
        throw "BodyRig local service is not ready at $UriBase. Start/restart it from exact clean current main before A/B preflight."
    }
    if ($health.ok -ne $true -or [string]$health.service -ne "bodyrig") {
        throw "The configured endpoint did not identify a healthy BodyRig service."
    }
    try {
        $authority = Invoke-RestMethod -Method Get -Uri "$UriBase/api/v1/operator-authority" -TimeoutSec 3
    }
    catch {
        throw "BodyRig service does not expose exact operator checkout authority."
    }
    if ($authority.ok -ne $true) {
        throw "Running BodyRig service is not ready for physical work: $([string]$authority.reason)"
    }
    $revision = ([string]$authority.bodyrig_revision).Trim().ToLowerInvariant()
    if ($revision -notmatch '^[0-9a-f]{40}$') {
        throw "Running BodyRig service did not return a canonical bodyrig_revision."
    }
    return $revision
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig A/B baseline preflight is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for A/B baseline preflight."
}
if ([string]::IsNullOrWhiteSpace($PersonId) -eq [string]::IsNullOrWhiteSpace($PerformerId)) {
    throw "Pass exactly one of -PersonId or -PerformerId."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $BodyRigPython = $venvPython }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$pwsh = Resolve-Executable -Value "" -Fallback "pwsh" -Label "PowerShell 7"
$Ffmpeg = Resolve-Executable -Value $Ffmpeg -Fallback "ffmpeg" -Label "FFmpeg"

if ([string]::IsNullOrWhiteSpace($StashUrl)) { $StashUrl = [string]$env:STASH_URL }
if ([string]::IsNullOrWhiteSpace($StashUrl)) {
    throw "Stash URL is required via -StashUrl or STASH_URL for exact performer preflight."
}

Write-Host "Validating current main and both active A/B candidate byte contracts..."
$pre = Invoke-CandidateAuthority -RepoRoot $repoRoot -Python $BodyRigPython
$mainRevision = [string]$pre.main_revision
$pbrRevision = [string]$pre.candidates.pbr_v2.revision
$throughputRevision = [string]$pre.candidates.recovery_throughput_v3.revision
$contractSha256 = [string]$pre.contract_sha256

$serviceRevision = Read-ServiceAuthority -UriBase $BaseUri
if ($serviceRevision -ne $mainRevision) {
    throw "Running BodyRig service revision differs from exact candidate-authority main: service=$serviceRevision, main=$mainRevision"
}

try {
    $people = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/people" -TimeoutSec 10
}
catch {
    throw "Could not inspect BodyRig Person/source bindings before A/B baseline."
}

if (-not [string]::IsNullOrWhiteSpace($PerformerId)) {
    $matches = @($people.people | Where-Object {
        $null -ne $_.source -and
        [string]$_.source.kind -eq "stash-performer" -and
        [string]$_.source.id -eq $PerformerId
    })
    if ($matches.Count -eq 0) { throw "No BodyRig Person is bound to Stash performer $PerformerId." }
    if ($matches.Count -gt 1) { throw "Multiple BodyRig Persons are bound to Stash performer $PerformerId. Pass -PersonId explicitly." }
    $resolvedPersonId = [string]$matches[0].person_id
    $resolvedPerformerId = $PerformerId
}
else {
    $matches = @($people.people | Where-Object { [string]$_.person_id -eq $PersonId })
    if ($matches.Count -ne 1) { throw "BodyRig Person $PersonId did not resolve exactly once." }
    $source = $matches[0].source
    if ($null -eq $source -or [string]$source.kind -ne "stash-performer" -or [string]::IsNullOrWhiteSpace([string]$source.id)) {
        throw "BodyRig Person $PersonId is not bound to one canonical Stash performer source."
    }
    $resolvedPersonId = $PersonId
    $resolvedPerformerId = [string]$source.id
}
if ($resolvedPersonId -notmatch '^person-[0-9a-f]{32}$') {
    throw "Resolved BodyRig Person id is not canonical: $resolvedPersonId"
}

try {
    $jobs = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/jobs?person_id=$([uri]::EscapeDataString($resolvedPersonId))" -TimeoutSec 10
}
catch {
    throw "Could not inspect existing BodyRig jobs for $resolvedPersonId."
}
$active = @($jobs.jobs | Where-Object {
    [string]$_.kind -eq "body-build" -and [string]$_.status -in @("queued", "running", "cancelling")
})
if ($active.Count -gt 0) {
    throw "A body-build is already active for ${resolvedPersonId}: $([string]$active[0].job_id) [$([string]$active[0].status)]"
}

$readinessScript = Need-File -Path (Join-Path $repoRoot "check-rig-ready.ps1") -Label "rig readiness script"
$readinessArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $readinessScript,
    "-BodyRigPython", $BodyRigPython,
    "-StashUrl", $StashUrl,
    "-ApiKeyEnv", $ApiKeyEnv,
    "-WslExe", $WslExe
)
if (-not [string]::IsNullOrWhiteSpace($RigSetupReport)) {
    $readinessArgs += @("-RigSetupReport", $RigSetupReport)
}

Write-Host "Running read-only rig/SiTH/CUDA/Stash readiness (no -Out; no physical evidence)..."
$readinessRaw = @(& $pwsh @readinessArgs 2>&1)
$readinessExit = $LASTEXITCODE
$readinessRaw | ForEach-Object { Write-Host $_ }
if ($readinessExit -ne 0) {
    throw "BodyRig A/B baseline rig readiness failed with exit code $readinessExit. No baseline job was enqueued."
}

Write-Host "Probing exact Stash performer source pool with ffmpeg-one-frame-v1..."
$probeRaw = @(& $BodyRigPython -m bodyrig.stash_cli probe --performer-id $resolvedPerformerId --url $StashUrl --api-key-env $ApiKeyEnv --ffmpeg $Ffmpeg 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "Selected Stash performer/source decode probe failed: $($probeRaw -join ' ')"
}
try { $probe = ($probeRaw -join "`n") | ConvertFrom-Json }
catch { throw "Selected Stash performer/source decode probe returned unreadable JSON." }
if ($probe.ok -ne $true -or [int]$probe.usable_source_count -lt 1) {
    throw "Selected Stash performer/source decode probe did not prove at least one decodable local video."
}
if ([string]$probe.decode_gate -ne "ffmpeg-one-frame-v1") {
    throw "Selected Stash performer/source probe did not use the canonical ffmpeg-one-frame-v1 decode gate."
}
if ([string]$probe.performer.id -ne $resolvedPerformerId) {
    throw "Selected Stash performer/source probe returned a different performer id."
}

Write-Host "Revalidating candidate refs and exact service/main authority after live readiness..."
$post = Invoke-CandidateAuthority `
    -RepoRoot $repoRoot `
    -Python $BodyRigPython `
    -ExpectedMainRevision $mainRevision `
    -ExpectedPbrRevision $pbrRevision `
    -ExpectedThroughputRevision $throughputRevision
if ([string]$post.contract_sha256 -ne $contractSha256) {
    throw "A/B candidate contract hash changed during physical preflight."
}
$serviceRevisionAfter = Read-ServiceAuthority -UriBase $BaseUri
if ($serviceRevisionAfter -ne $mainRevision) {
    throw "Running BodyRig service revision moved during physical preflight: service=$serviceRevisionAfter, main=$mainRevision"
}

Write-Host "BodyRig A/B baseline preflight: READY"
Write-Host "Main:                $mainRevision"
Write-Host "Person:              $resolvedPersonId"
Write-Host "Stash performer:     $resolvedPerformerId"
Write-Host "Decodable sources:   $([int]$probe.usable_source_count)"
Write-Host "PBR candidate:       $pbrRevision"
Write-Host "Throughput candidate:$throughputRevision"
Write-Host "Authority: read-only pre-enqueue readiness; no physical acceptance, promotion or production activation."

[pscustomobject]@{
    format = "bodyrig-ab-baseline-preflight"
    version = 1
    ready = $true
    main_revision = $mainRevision
    person_id = $resolvedPersonId
    performer_id = $resolvedPerformerId
    candidate_contract_sha256 = $contractSha256
    pbr_candidate_revision = $pbrRevision
    throughput_candidate_revision = $throughputRevision
    decode_gate = [string]$probe.decode_gate
    usable_source_count = [int]$probe.usable_source_count
    comparison_only = $true
    human_visual_authority_required = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
} | ConvertTo-Json -Depth 8 -Compress
