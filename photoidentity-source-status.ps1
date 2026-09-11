param(
    [Parameter(Mandatory = $true)][string]$SweepRoot,
    [string]$MultiperformerRoot = "",
    [string]$BaselineCloneOutput = "",
    [string]$BodyJobId = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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
function Need-Executable {
    param([string]$Value,[string]$Fallback,[string]$Label)
    $candidate = if ([string]::IsNullOrWhiteSpace($Value)) { $Fallback } else { $Value }
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "$Label executable not found: $candidate" }
    return $command.Source
}
function Quote-PS {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}
function Quote-PSArray {
    param([object[]]$Values)
    $items = @($Values | ForEach-Object { Quote-PS ([string]$_) })
    return "@(" + ($items -join ", ") + ")"
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig photoidentity source status is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not establish exact BodyRig Git authority." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig Git HEAD is not canonical." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Photoidentity source status requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { $BodyRigPython = Need-Executable -Value "" -Fallback "python" -Label "BodyRig Python" }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$expectedModule = Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "Checkout BodyRig module"
$moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "BodyRig Python could not prove checkout-bound imports." }
$actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
if (-not [string]::Equals($actualModule,$expectedModule,[StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports from a different checkout: $actualModule"
}

$SweepRoot = Need-Directory -Path $SweepRoot -Label "Photoidentity sweep root"
$argsList = @("-m", "bodyrig.photoidentity_source_status", "--sweep-root", $SweepRoot)
if (-not [string]::IsNullOrWhiteSpace($MultiperformerRoot)) {
    $MultiperformerRoot = Need-Directory -Path $MultiperformerRoot -Label "Multi-performer workflow root"
    $argsList += @("--multiperformer-root", $MultiperformerRoot)
}
if (-not [string]::IsNullOrWhiteSpace($BodyJobId)) {
    if ($BodyJobId -notmatch '^job-[0-9a-f]{32}$') { throw "BodyJobId is not canonical." }
    $argsList += @("--body-job-id", $BodyJobId)
}
$statusRaw = @(& $BodyRigPython @argsList 2>&1)
if ($LASTEXITCODE -ne 0 -or $statusRaw.Count -ne 1) {
    throw "BodyRig photoidentity source status failed: $($statusRaw -join [Environment]::NewLine)"
}
try { $status = ([string]$statusRaw[0]) | ConvertFrom-Json -Depth 40 }
catch { throw "BodyRig photoidentity source status returned unreadable JSON." }
if ([string]$status.bodyrig_revision -ne $head) {
    throw "Photoidentity sweep belongs to BodyRig revision $($status.bodyrig_revision), current checkout is $head. Refusing cross-revision routing."
}
if ($status.generic_guessing_permitted -ne $false -or $status.production_activation -ne $false) {
    throw "Photoidentity status violated the no-guess/no-production authority boundary."
}

Write-Host "BodyRig photoidentity source status: $($status.stage)"
Write-Host "Revision:       $head"
Write-Host "Performer:      $($status.performer_id)"
Write-Host "Source enough:  $([string]::ToUpperInvariant([string][bool]$status.source_evidence_sufficient))"
Write-Host "Render allowed: $([string]::ToUpperInvariant([string][bool]$status.avatar_render_permitted))"
Write-Host "Generic guess:  FALSE"
Write-Host "Production:     FALSE"
Write-Host ""

switch ([string]$status.stage) {
    "multiperformer-discovery" {
        Write-Host "Target-detail source authority is incomplete. Multi-performer source discovery must happen before nails/anatomy."
        Write-Host "Next command:"
        Write-Host ("& " + (Quote-PS (Join-Path $repoRoot "discover-photoidentity-multiperformer-sources.ps1")) + " -PerformerId " + (Quote-PS ([string]$status.performer_id)))
        Write-Host "After discovery, re-run this status command with -MultiperformerRoot '<discovery-root>'."
    }
    "multiperformer-track-review-prepare" {
        Write-Host "Human identity selection is required; BodyRig will not choose a person/track automatically."
        Write-Host "Available source candidate ids:"
        foreach ($id in @($status.available_source_candidate_ids)) { Write-Host ("  " + [string]$id) }
        Write-Host "Next command template:"
        Write-Host ("& " + (Quote-PS (Join-Path $repoRoot "prepare-photoidentity-multiperformer-track-review.ps1")) + " -DiscoveryRoot " + (Quote-PS ([string]$status.multiperformer_root)) + " -SourceCandidateId '<multicand-id>'")
    }
    "multiperformer-track-human-review" {
        Write-Host "Human source-track identity review required. Review the source-derived sheets and choose exactly one target track yourself."
        foreach ($reviewRoot in @($status.pending_review_roots)) {
            Write-Host ("Review root: " + [string]$reviewRoot)
            Write-Host ("  & " + (Quote-PS (Join-Path $repoRoot "record-photoidentity-multiperformer-track-attestation.ps1")) + " -ReviewRoot " + (Quote-PS ([string]$reviewRoot)) + " -TrackCandidateId '<trackcand-id>' -QualityNote '<what proves this is the requested performer>' -ConfirmIdentity")
        }
    }
    "multiperformer-target-isolation-materialize" {
        Write-Host "The target track is human-attested. Materialize real source crops; no interpolation/generative pixels are allowed."
        foreach ($reviewRoot in @($status.pending_review_roots)) {
            Write-Host ("& " + (Quote-PS (Join-Path $repoRoot "materialize-photoidentity-multiperformer-target-source.ps1")) + " -ReviewRoot " + (Quote-PS ([string]$reviewRoot)))
        }
    }
    "multiperformer-target-isolation-human-review" {
        Write-Host "Human target-isolation review required. Accept only crops containing the requested performer with no cross-person contamination."
        foreach ($candidateRoot in @($status.pending_candidate_roots)) {
            Write-Host ("Candidate root: " + [string]$candidateRoot)
            Write-Host ("  & " + (Quote-PS (Join-Path $repoRoot "record-photoidentity-multiperformer-target-isolation.ps1")) + " -CandidateRoot " + (Quote-PS ([string]$candidateRoot)) + " -SampleId '<targetsample-id>' -ConfirmTargetIsolation -QualityNote '<what was visibly checked>'")
        }
    }
    "multiperformer-target-crop-enrich" {
        if ([string]::IsNullOrWhiteSpace($BaselineCloneOutput)) {
            Write-Host "Next: provide -BaselineCloneOutput so BodyRig can run pinned OpenPose/SCHP observability on the human-isolated crops."
            break
        }
        $baseline = Need-Directory -Path $BaselineCloneOutput -Label "Baseline clone output"
        foreach ($candidateRoot in @($status.pending_candidate_roots)) {
            Write-Host ("& " + (Quote-PS (Join-Path $repoRoot "enrich-photoidentity-multiperformer-target-crops.ps1")) + " -CandidateRoot " + (Quote-PS ([string]$candidateRoot)) + " -BaselineCloneOutput " + (Quote-PS $baseline))
        }
    }
    "multiperformer-target-detail-human-review" {
        Write-Host "Human source-detail quality review required."
        Write-Host "Machine-supported refs use '<sample>:<domain>'; eyebrows/facial/body hair require explicit '<sample>:<domain>:<quality>'."
        foreach ($candidateRoot in @($status.pending_candidate_roots)) {
            Write-Host ("Candidate root: " + [string]$candidateRoot)
            Write-Host ("  & " + (Quote-PS (Join-Path $repoRoot "record-photoidentity-target-crop-detail-quality.ps1")) + " -CandidateRoot " + (Quote-PS ([string]$candidateRoot)) + " -DetailRef '<reviewed-ref>' -QualityNote '<visible source detail and quality>' -ConfirmQuality")
        }
    }
    "multiperformer-more-detail" {
        Write-Host ("Still missing target-detail domains: " + (@($status.missing_target_domains) -join ", "))
        Write-Host "Choose another unreviewed source yourself; BodyRig will not auto-select identity evidence."
        foreach ($id in @($status.available_source_candidate_ids)) { Write-Host ("  candidate: " + [string]$id) }
        Write-Host "Next command template:"
        Write-Host ("& " + (Quote-PS (Join-Path $repoRoot "prepare-photoidentity-multiperformer-track-review.ps1")) + " -DiscoveryRoot " + (Quote-PS ([string]$status.multiperformer_root)) + " -SourceCandidateId '<multicand-id>'")
    }
    "multiperformer-source-insufficient" {
        Write-Host ("Fail-closed source blocker. Missing target-detail domains: " + (@($status.missing_target_domains) -join ", "))
        Write-Host "The exhaustive discovery has no unused source candidate able to fill the gap."
        Write-Host "Add/capture real source media, then run a new multi-performer discovery. Generic guessing remains forbidden."
    }
    "multiperformer-aggregation" {
        $receipts = @($status.quality_receipts)
        $candidateRoots = @($status.candidate_roots)
        if ($receipts.Count -lt 1 -or $receipts.Count -ne $candidateRoots.Count) {
            throw "Status returned a non-canonical aggregation input set."
        }
        Write-Host "All target-detail domains have enough reviewed source scenes for the create-only aggregation preflight."
        Write-Host "Next command:"
        Write-Host ("& " + (Quote-PS (Join-Path $repoRoot "aggregate-photoidentity-multiperformer-detail-evidence.ps1")) + " -SweepRoot " + (Quote-PS $SweepRoot) + " -QualityReceipt " + (Quote-PSArray $receipts) + " -CandidateRoot " + (Quote-PSArray $candidateRoots))
    }
    "nail-discovery" {
        if ([string]::IsNullOrWhiteSpace($BaselineCloneOutput)) {
            Write-Host "Next: provide -BaselineCloneOutput so BodyRig can discover source-only nail closeups."
            break
        }
        $baseline = Need-Directory -Path $BaselineCloneOutput -Label "Baseline clone output"
        Write-Host "Next command:"
        Write-Host ("& " + (Quote-PS (Join-Path $repoRoot "discover-photoidentity-nail-sources.ps1")) + " -SweepRoot " + (Quote-PS $SweepRoot) + " -BaselineCloneOutput " + (Quote-PS $baseline))
    }
    "nail-review-prepare" {
        Write-Host "Next command:"
        Write-Host ("& " + (Quote-PS (Join-Path $repoRoot "prepare-photoidentity-nail-source-review.ps1")) + " -SweepRoot " + (Quote-PS $SweepRoot))
    }
    "nail-human-review" {
        Write-Host "Human source review required. Review only the real source closeups in:"
        Write-Host (Join-Path $SweepRoot "private-nail-source-review")
        Write-Host "Use review-refs.txt to select real left/right fingernail and toenail refs from >=2 distinct scenes each."
        Write-Host "Do not record attestation unless both nail domains are genuinely visible at sufficient detail."
    }
    "anatomy-discovery" {
        if ([string]::IsNullOrWhiteSpace($BaselineCloneOutput)) {
            Write-Host "Next: provide -BaselineCloneOutput so BodyRig can discover source-only rear/torso/waist closeups."
            break
        }
        $baseline = Need-Directory -Path $BaselineCloneOutput -Label "Baseline clone output"
        Write-Host "Next command:"
        Write-Host ("& " + (Quote-PS (Join-Path $repoRoot "discover-photoidentity-anatomy-sources.ps1")) + " -SweepRoot " + (Quote-PS $SweepRoot) + " -BaselineCloneOutput " + (Quote-PS $baseline))
    }
    "anatomy-review-prepare" {
        Write-Host "Next command:"
        Write-Host ("& " + (Quote-PS (Join-Path $repoRoot "prepare-photoidentity-anatomy-source-review.ps1")) + " -SweepRoot " + (Quote-PS $SweepRoot))
    }
    "anatomy-human-review" {
        Write-Host "Human source review required. Review only the real source crops in:"
        Write-Host (Join-Path $SweepRoot "private-anatomy-source-review")
        Write-Host "Confirm rear orientation and actual observable torso/chest + waist/hips anatomy only when the source supports it."
        Write-Host "No hidden anatomy may be inferred through clothing or occlusion."
    }
    "ready-for-registration" {
        if ([string]::IsNullOrWhiteSpace($BodyJobId)) {
            Write-Host "Source chain is complete, but avatar render remains blocked until it is registered to the exact body-build."
            Write-Host "Re-run this status command with -BodyJobId 'job-...' to get the registration command."
            break
        }
        Write-Host "Next command:"
        Write-Host ("& " + (Quote-PS (Join-Path $repoRoot "register-photoidentity-source-authority.ps1")) + " -BodyJobId " + (Quote-PS $BodyJobId) + " -SweepRoot " + (Quote-PS $SweepRoot))
    }
    "registered" {
        Write-Host "Exact source-sufficiency authority is registered for this body-build."
        Write-Host "The high-fidelity preview gate may now be evaluated separately; this status command does not start it."
    }
    default { throw "Unknown photoidentity source status stage: $($status.stage)" }
}
