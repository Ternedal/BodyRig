param(
    [ValidatePattern('^$|^person-[0-9a-f]{32}$')]
    [string]$PersonId = "",

    [string]$PerformerId = "",

    [ValidatePattern('^https?://(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?$')]
    [string]$BaseUri = "http://127.0.0.1:8775",

    [string]$BodyRigPython = ""
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
        [string]$_.source.performer_id -eq $PerformerId
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
    if ($null -eq $source -or [string]$source.kind -ne "stash-performer" -or [string]::IsNullOrWhiteSpace([string]$source.performer_id)) {
        throw "BodyRig Person $PersonId is not bound to one canonical Stash performer source."
    }
    $resolvedPersonId = $PersonId
    $resolvedPerformerId = [string]$source.performer_id
}
if ($resolvedPersonId -notmatch '^person-[0-9a-f]{32}$') {
    throw "Resolved BodyRig Person id is not canonical: $resolvedPersonId"
}

$payload = @{ expected_bodyrig_revision = $mainRevision } | ConvertTo-Json -Depth 4 -Compress
Write-Host "Running service-bound read-only renderer/rig/SiTH/CUDA/Stash/source preflight..."
try {
    $physical = Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUri/api/v1/people/$resolvedPersonId/body/ab-baseline-preflight" `
        -ContentType "application/json" `
        -Body $payload `
        -TimeoutSec 900
}
catch {
    throw "BodyRig service-bound A/B physical preflight failed: $($_.Exception.Message)"
}
if (
    [string]$physical.format -ne "bodyrig-ab-baseline-physical-preflight" -or
    [int]$physical.version -ne 1 -or
    $physical.ready -ne $true -or
    [string]$physical.person_id -ne $resolvedPersonId -or
    [string]$physical.performer_id -ne $resolvedPerformerId -or
    [string]$physical.bodyrig_revision -ne $mainRevision -or
    $physical.renderer_ready -ne $true -or
    [string]$physical.decode_gate -ne "ffmpeg-one-frame-v1" -or
    [int]$physical.usable_source_count -lt 1 -or
    $physical.service_environment_bound -ne $true -or
    $physical.readiness_output_persisted -ne $false -or
    $physical.physical_acceptance_authority -ne $false -or
    $physical.promotion_authority -ne $false -or
    $physical.production_activation -ne $false
) {
    throw "BodyRig service-bound A/B physical preflight returned unexpected readiness/authority semantics."
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
Write-Host "Renderer toolchain:  READY"
Write-Host "Decodable sources:   $([int]$physical.usable_source_count)"
Write-Host "PBR candidate:       $pbrRevision"
Write-Host "Throughput candidate:$throughputRevision"
Write-Host "Authority: service-bound read-only pre-enqueue readiness; no physical acceptance, promotion or production activation."

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
    renderer_ready = $true
    decode_gate = [string]$physical.decode_gate
    usable_source_count = [int]$physical.usable_source_count
    service_environment_bound = $true
    comparison_only = $true
    human_visual_authority_required = $true
    physical_acceptance_authority = $false
    promotion_authority = $false
    production_activation = $false
} | ConvertTo-Json -Depth 8 -Compress
