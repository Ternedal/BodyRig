param(
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [string]$BaseUrl = "http://127.0.0.1:8775"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path $PSScriptRoot).Path

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Runtime speech-timing evidence export is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for runtime speech-timing evidence export."
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is unavailable; exact BodyRig launcher authority cannot be verified."
}

$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout state." }
if ($dirty.Count -ne 0) { throw "Runtime timing evidence export requires a clean BodyRig checkout." }
$revision = (@(& git -C $repoRoot rev-parse HEAD 2>&1) | Select-Object -First 1).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve exact BodyRig revision." }

$base = $BaseUrl.TrimEnd('/')
try { $health = Invoke-RestMethod -Uri "$base/api/v1/health" -TimeoutSec 3 }
catch { throw "BodyRig runtime health is unavailable at $base." }
if ($health.ok -ne $true -or [string]$health.service -ne "bodyrig") {
    throw "Runtime endpoint does not identify as BodyRig."
}

$launchStatePath = Join-Path $env:LOCALAPPDATA "BodyRig\ui-service.json"
if (-not (Test-Path -LiteralPath $launchStatePath -PathType Leaf)) {
    throw "Verified BodyRig launcher state is missing. Start BodyRig with start-windows.ps1 first."
}
try { $launch = Get-Content -LiteralPath $launchStatePath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "BodyRig launcher state is unreadable." }
if ([string]$launch.format -ne "bodyrig-ui-service" -or [int]$launch.version -ne 1) {
    throw "BodyRig launcher state format/version mismatch."
}
$currentRoot = [System.IO.Path]::GetFullPath($repoRoot).TrimEnd('\')
$launchRoot = [System.IO.Path]::GetFullPath([string]$launch.root).TrimEnd('\')
if (-not [string]::Equals($currentRoot, $launchRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    [string]$launch.revision -ne $revision) {
    throw "Running BodyRig service belongs to a different checkout or revision."
}
$pidValue = [int]$launch.pid
if ($pidValue -le 0 -or $null -eq (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
    throw "BodyRig launcher process authority is stale."
}

try { $state = Invoke-RestMethod -Uri "$base/api/v1/runtime/state" -TimeoutSec 3 }
catch { throw "BodyRig runtime state is unavailable." }
$evidence = $state.speech_timing_evidence
if ($null -eq $evidence) {
    throw "No complete canonical VoiceRig timing evidence is available. Run one start/update*/stop utterance first."
}
$expectedFields = @("format","version","utterance_id","source","events","complete","human_review_required","production_activation")
if (@(Compare-Object -ReferenceObject $expectedFields -DifferenceObject @($evidence.PSObject.Properties.Name)).Count -ne 0 -or
    [string]$evidence.format -ne "bodyrig-speech-timing-evidence" -or [int]$evidence.version -ne 1 -or
    [string]$evidence.source -ne "voicerig-runtime" -or $evidence.complete -ne $true -or
    $evidence.human_review_required -ne $true -or $evidence.production_activation -ne $false) {
    throw "BodyRig runtime returned non-canonical speech timing evidence."
}
$events = @($evidence.events)
if ($events.Count -lt 2 -or [string]$events[0].state -ne "start" -or [int]$events[0].elapsed_ms -ne 0 -or
    [string]$events[-1].state -ne "stop" -or [int]$events[-1].elapsed_ms -le 0) {
    throw "BodyRig runtime timing evidence does not contain a canonical completed timeline."
}

$output = [System.IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $output) { throw "Refusing to overwrite existing runtime timing evidence: $output" }
$parent = Split-Path -Parent $output
if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw "Output parent does not exist: $parent" }
$json = ($evidence | ConvertTo-Json -Depth 8) + "`n"
$encoding = [System.Text.UTF8Encoding]::new($false)
$stream = [System.IO.File]::Open($output, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
try {
    $writer = [System.IO.StreamWriter]::new($stream, $encoding)
    try { $writer.Write($json) } finally { $writer.Dispose() }
} finally {
    $stream.Dispose()
}
$sha = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
[pscustomobject]@{
    ok = $true
    bodyrig_revision = $revision
    utterance_id = [string]$evidence.utterance_id
    evidence_path = $output
    evidence_sha256 = $sha
    human_review_required = $true
    production_activation = $false
} | ConvertTo-Json -Compress
