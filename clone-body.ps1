param(
    [string[]]$Source = @(),

    [string]$SourceManifest = "",

    [string[]]$SourceOverride = @(),

    [string]$SourceOverrideManifest = "",

    [Parameter(Mandatory = $true)]
    [string]$ExternalPython,

    [Parameter(Mandatory = $true)]
    [string]$FourDHumansRepo,

    [Parameter(Mandatory = $true)]
    [string]$IdentityCaptureConfig,

    [Parameter(Mandatory = $true)]
    [string]$FitterConfig,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId,

    [Parameter(Mandatory = $true)]
    [ValidateLength(1, 160)]
    [string]$Name,

    [string]$TrackId = "",
    [string]$OutputDir = "",
    [string]$PrivateWorkspace = "",
    [string]$BodyRigPython = "",
    [switch]$AllowCpu,
    [switch]$KeepPrivateWorkspace
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Step
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-InputDirectory {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$usingManifest = -not [string]::IsNullOrWhiteSpace($SourceManifest)
$usingOverrideManifest = -not [string]::IsNullOrWhiteSpace($SourceOverrideManifest)
if ($usingManifest -and $Source.Count -gt 0) {
    throw "Pass either -Source or -SourceManifest, never both."
}
if ($SourceOverride.Count -gt 0 -and $usingOverrideManifest) {
    throw "Pass either -SourceOverride or -SourceOverrideManifest, never both."
}
if (($SourceOverride.Count -gt 0 -or $usingOverrideManifest) -and -not $usingManifest) {
    throw "Source overrides are only valid together with -SourceManifest."
}
if (-not $usingManifest -and ($Source.Count -lt 1 -or $Source.Count -gt 10)) {
    throw "BodyRig accepts 1..10 source clips, or one -SourceManifest."
}

$sourceOrigin = "direct-local-media"
$sourcePerformerId = ""
$sourcePerformerName = ""
$usingSourceOverride = $false
$sourceOverrideManifestSha256 = ""
if ($usingManifest) {
    $SourceManifest = Resolve-InputFile -Path $SourceManifest -Label "BodyRig source manifest"
    try {
        $manifest = Get-Content -LiteralPath $SourceManifest -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "BodyRig source manifest is not valid JSON: $SourceManifest"
    }
    if ([string]$manifest.format -ne "bodyrig-stash-source-manifest" -or [int]$manifest.version -ne 1) {
        throw "Unsupported BodyRig source manifest format/version."
    }
    if ([string]$manifest.source_kind -ne "stash-local") {
        throw "Unsupported BodyRig source manifest source_kind."
    }
    $selected = @($manifest.selected)
    if ($selected.Count -lt 1 -or $selected.Count -gt 10) {
        throw "Stash source manifest must contain 1..10 selected files."
    }
    $manifestSources = @()
    foreach ($item in $selected) {
        $path = [string]$item.path
        if ([string]::IsNullOrWhiteSpace($path)) {
            throw "Stash source manifest contains an empty selected path."
        }
        $manifestSources += $path
    }

    if ($usingOverrideManifest) {
        $SourceOverrideManifest = Resolve-InputFile -Path $SourceOverrideManifest -Label "BodyRig observation segment manifest"
        try {
            $overrideManifest = Get-Content -LiteralPath $SourceOverrideManifest -Raw -Encoding UTF8 | ConvertFrom-Json
        } catch {
            throw "BodyRig observation segment manifest is not valid JSON."
        }
        if ([string]$overrideManifest.format -ne "bodyrig-observation-segments" -or [int]$overrideManifest.version -ne 1) {
            throw "Unsupported BodyRig observation segment manifest format/version."
        }
        $segments = @($overrideManifest.segments)
        if ($segments.Count -lt 1 -or $segments.Count -gt 10) {
            throw "BodyRig observation segment manifest must contain 1..10 segments."
        }
        $SourceOverride = @()
        foreach ($segment in $segments) {
            $segmentPath = Resolve-InputFile -Path ([string]$segment.path) -Label "Observation segment"
            $expectedHash = ([string]$segment.sha256).ToLowerInvariant()
            if ($expectedHash -notmatch '^[0-9a-f]{64}$') {
                throw "Observation segment manifest contains an invalid SHA-256."
            }
            $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $segmentPath).Hash.ToLowerInvariant()
            if ($actualHash -ne $expectedHash) {
                throw "Observation segment SHA-256 mismatch: $segmentPath"
            }
            $SourceOverride += $segmentPath
        }
        $sourceOverrideManifestSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $SourceOverrideManifest).Hash.ToLowerInvariant()
    }

    if ($SourceOverride.Count -gt 0) {
        if ($SourceOverride.Count -lt 1 -or $SourceOverride.Count -gt 10) {
            throw "BodyRig source override must contain 1..10 private observation segments."
        }
        $Source = @($SourceOverride)
        $usingSourceOverride = $true
    } else {
        $Source = $manifestSources
    }
    $sourceOrigin = "stash-local"
    $sourcePerformerId = [string]$manifest.performer.id
    $sourcePerformerName = [string]$manifest.performer.name
    if ([string]::IsNullOrWhiteSpace($sourcePerformerId) -or [string]::IsNullOrWhiteSpace($sourcePerformerName)) {
        throw "Stash source manifest performer binding is incomplete."
    }
}

$resolvedSources = @()
foreach ($item in $Source) {
    $resolvedSources += Resolve-InputFile -Path $item -Label "Source clip"
}
if ($resolvedSources.Count -lt 1 -or $resolvedSources.Count -gt 10) {
    throw "BodyRig resolved source count must be 1..10."
}
if (($resolvedSources | Select-Object -Unique).Count -ne $resolvedSources.Count) {
    throw "BodyRig source list contains duplicate local files."
}

$ExternalPython = Resolve-InputFile -Path $ExternalPython -Label "External recovery Python"
$FourDHumansRepo = Resolve-InputDirectory -Path $FourDHumansRepo -Label "4D-Humans repository"
$IdentityCaptureConfig = Resolve-InputFile -Path $IdentityCaptureConfig -Label "Identity capture config"
$FitterConfig = Resolve-InputFile -Path $FitterConfig -Label "High-fidelity fitter config"

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $BodyRigPython = $venvPython
    } else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $pythonCommand) {
            throw "BodyRig Python not found. Create .venv or pass -BodyRigPython."
        }
        $BodyRigPython = $pythonCommand.Source
    }
}
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"

$stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path (Get-Location).Path "bodyrig-clone-$BodyId-$stamp"
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) {
    throw "Clone output directory already exists; refusing cross-run reuse: $OutputDir"
}
New-Item -ItemType Directory -Path $OutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($PrivateWorkspace)) {
    $privateBase = $env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($privateBase)) {
        $privateBase = [System.IO.Path]::GetTempPath()
    }
    $PrivateWorkspace = Join-Path $privateBase ("BodyRig\identity-workspaces\$BodyId-$stamp-" + [Guid]::NewGuid().ToString("N"))
}
$PrivateWorkspace = [System.IO.Path]::GetFullPath($PrivateWorkspace)
if (Test-Path -LiteralPath $PrivateWorkspace) {
    throw "Private identity workspace already exists; refusing cross-run reuse: $PrivateWorkspace"
}

$preflightPath = Join-Path $OutputDir "bodyrig-recovery-preflight.json"
$proofPath = Join-Path $OutputDir "bodyrig-recovery-proof.json"
$identityPath = Join-Path $OutputDir "bodyrig-visual-identity.json"
$portableIdentityPath = Join-Path $OutputDir "bodyrig-portable-identity.json"
$packagePath = Join-Path $OutputDir "$BodyId.mrbody"
$sourceEvidencePath = Join-Path $OutputDir "bodyrig-source-evidence.json"

$sourceEvidence = [ordered]@{
    format = "bodyrig-source-evidence"
    version = 1
    source_kind = $sourceOrigin
    source_count = $resolvedSources.Count
    input_selection = $(if ($usingSourceOverride) { "private-observation-segments" } else { "source-files" })
}
if ($usingManifest) {
    $sourceEvidence.stash_performer_id = $sourcePerformerId
    $sourceEvidence.stash_performer_name = $sourcePerformerName
    $sourceEvidence.stash_source_manifest = [System.IO.Path]::GetFileName($SourceManifest)
}
if ($usingOverrideManifest) {
    $sourceEvidence.observation_segment_manifest = [System.IO.Path]::GetFileName($SourceOverrideManifest)
    $sourceEvidence.observation_segment_manifest_sha256 = $sourceOverrideManifestSha256
}
$sourceEvidence | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $sourceEvidencePath -Encoding UTF8

$success = $false
try {
    Write-Host "BodyRig clone | $Name | alias=$BodyId"
    Write-Host "Source clips: $($resolvedSources.Count)"
    Write-Host "Source kind: $sourceOrigin"
    if ($usingManifest) {
        Write-Host "Stash performer: $sourcePerformerName [$sourcePerformerId]"
    }
    if ($usingSourceOverride) {
        Write-Host "Input selection: private observation segments"
    }
    Write-Host "Portable artifacts: $OutputDir"
    Write-Host "Private identity workspace: $PrivateWorkspace"
    Write-Host ""

    $preflightArgs = @(
        "-m", "bodyrig.preflight_cli",
        "--python", $ExternalPython,
        "--repo", $FourDHumansRepo,
        "--out", $preflightPath
    )
    if ($AllowCpu) { $preflightArgs += "--allow-cpu" }
    Invoke-Checked -Executable $BodyRigPython -Arguments $preflightArgs -Step "Recovery preflight"

    $recoverArgs = @(
        "-m", "bodyrig.recover_cli",
        "--python", $ExternalPython,
        "--repo", $FourDHumansRepo,
        "--out", $proofPath
    )
    if (-not [string]::IsNullOrWhiteSpace($TrackId)) {
        $recoverArgs += @("--track-id", $TrackId)
    }
    $recoverArgs += $resolvedSources
    Invoke-Checked -Executable $BodyRigPython -Arguments $recoverArgs -Step "Video recovery"

    $captureArgs = @(
        "-m", "bodyrig.identity_capture_cli",
        $proofPath
    )
    $captureArgs += $resolvedSources
    $captureArgs += @(
        "--config", $IdentityCaptureConfig,
        "--workspace", $PrivateWorkspace,
        "--out", $identityPath
    )
    Invoke-Checked -Executable $BodyRigPython -Arguments $captureArgs -Step "Visual identity capture"

    $portableIdentityArgs = @(
        "-m", "bodyrig.portable_identity",
        $proofPath
    )
    $portableIdentityArgs += $resolvedSources
    $portableIdentityArgs += @(
        "--identity-profile", $identityPath,
        "--requested-alias", $BodyId,
        "--out", $portableIdentityPath
    )
    Invoke-Checked -Executable $BodyRigPython -Arguments $portableIdentityArgs -Step "Portable identity binding"

    $identityInspectCode = @'
import json, sys
from bodyrig.portable_identity import load_portable_identity
r = load_portable_identity(sys.argv[1])
print(json.dumps({"body_id": r["body_id"], "requested_alias": r["requested_alias"]}, separators=(",", ":")))
'@
    $portableIdentityRaw = & $BodyRigPython -c $identityInspectCode $portableIdentityPath
    if ($LASTEXITCODE -ne 0) { throw "Portable identity receipt failed strict reload." }
    try { $portableIdentity = $portableIdentityRaw | ConvertFrom-Json }
    catch { throw "Portable identity strict reload returned unreadable JSON." }
    $canonicalBodyId = [string]$portableIdentity.body_id
    if ($canonicalBodyId -notmatch '^bodyid-[0-9a-f]{24}$') {
        throw "Portable identity did not produce a canonical bodyid."
    }
    if ([string]$portableIdentity.requested_alias -ne $BodyId) {
        throw "Portable identity requested alias does not match clone alias."
    }

    $fitArgs = @(
        "-m", "bodyrig.external_fitter_cli",
        $proofPath,
        "--identity-profile", $identityPath,
        "--identity-workspace", $PrivateWorkspace,
        "--config", $FitterConfig,
        "--body-id", $BodyId,
        "--portable-identity", $portableIdentityPath,
        "--name", $Name,
        "--out", $packagePath
    )
    Invoke-Checked -Executable $BodyRigPython -Arguments $fitArgs -Step "High-fidelity avatar fitting"

    $validateCode = @'
import hashlib, json, pathlib, sys
from bodyrig.package import validate_package
p = pathlib.Path(sys.argv[1]).resolve()
v = validate_package(p)
identity_stages = [s for s in v.provenance["pipeline"] if s.get("stage") == "identity_content"]
print(json.dumps({
  "body_id": v.manifest["id"],
  "package_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
  "payloads": list(v.payload_names),
  "pipeline": v.provenance["pipeline"],
  "identity_stages": identity_stages,
}, separators=(",", ":")))
'@
    $validatedRaw = & $BodyRigPython -c $validateCode $packagePath
    if ($LASTEXITCODE -ne 0) {
        throw "Final .mrbody validation failed with exit code $LASTEXITCODE"
    }
    try { $validated = $validatedRaw | ConvertFrom-Json }
    catch { throw "Final .mrbody validation returned unreadable JSON." }
    if ([string]$validated.body_id -ne $canonicalBodyId) {
        throw "Final .mrbody canonical body id mismatch."
    }
    $identityStages = @($validated.identity_stages)
    if ($identityStages.Count -ne 1) {
        throw "Final .mrbody must contain exactly one identity_content provenance stage."
    }
    $identityStage = $identityStages[0]
    if ([string]$identityStage.adapter -ne "bodyrig.portable_identity" -or [string]$identityStage.revision -ne $canonicalBodyId.Substring(7)) {
        throw "Final .mrbody portable identity provenance mismatch."
    }

    $success = $true
    Write-Host ""
    Write-Host "BodyRig clone: PASS"
    Write-Host "Requested alias: $BodyId"
    Write-Host "Canonical body id: $canonicalBodyId"
    Write-Host "Package: $packagePath"
    Write-Host "Package SHA-256: $($validated.package_sha256)"
    Write-Host "Portable identity: $portableIdentityPath"
    Write-Host "Recovery proof: $proofPath"
    Write-Host "Visual identity profile: $identityPath"
    Write-Host "Source evidence: $sourceEvidencePath"
} finally {
    if (-not $KeepPrivateWorkspace -and (Test-Path -LiteralPath $PrivateWorkspace -PathType Container)) {
        Remove-Item -LiteralPath $PrivateWorkspace -Recurse -Force -ErrorAction SilentlyContinue
        if ($success) {
            Write-Host "Private identity workspace deleted after successful package build."
        } else {
            Write-Host "Private identity workspace deleted after failed build."
        }
    } elseif ($KeepPrivateWorkspace -and (Test-Path -LiteralPath $PrivateWorkspace -PathType Container)) {
        Write-Host "Private identity workspace retained by explicit request: $PrivateWorkspace"
    }
}

if (-not $success) { exit 1 }
exit 0
