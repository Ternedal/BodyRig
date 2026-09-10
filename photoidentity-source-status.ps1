param(
    [Parameter(Mandatory = $true)][string]$SweepRoot,
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
if (-not [string]::IsNullOrWhiteSpace($BodyJobId)) {
    if ($BodyJobId -notmatch '^job-[0-9a-f]{32}$') { throw "BodyJobId is not canonical." }
    $argsList += @("--body-job-id", $BodyJobId)
}
$statusRaw = @(& $BodyRigPython @argsList 2>&1)
if ($LASTEXITCODE -ne 0 -or $statusRaw.Count -ne 1) {
    throw "BodyRig photoidentity source status failed: $($statusRaw -join [Environment]::NewLine)"
}
try { $status = ([string]$statusRaw[0]) | ConvertFrom-Json -Depth 30 }
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
