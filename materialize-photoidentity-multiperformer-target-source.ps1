param(
    [Parameter(Mandatory = $true)][string]$ReviewRoot,
    [string]$OutputDir = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File { param([string]$Path,[string]$Label); if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }; return (Resolve-Path -LiteralPath $Path).Path }
function Need-Directory { param([string]$Path,[string]$Label); if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }; return (Resolve-Path -LiteralPath $Path).Path }
function Read-ExactHead { param([string]$RepoRoot); $raw=@(& git -C $RepoRoot rev-parse HEAD 2>&1); if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1 -or ([string]$raw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') { throw "Could not bind target-isolation candidates to exact BodyRig Git HEAD." }; return ([string]$raw[0]).Trim().ToLowerInvariant() }
function Assert-CleanCheckout { param([string]$RepoRoot); $dirty=@(& git -C $RepoRoot status --porcelain 2>&1); if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Target-isolation candidate materialization requires an exact clean BodyRig checkout." } }

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig multi-performer target source materialization is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
$repoRoot=(Resolve-Path $PSScriptRoot).Path
$head=Read-ExactHead -RepoRoot $repoRoot
Assert-CleanCheckout -RepoRoot $repoRoot
$ReviewRoot=Need-Directory -Path $ReviewRoot -Label "Multi-performer track review root"
$null=Need-File -Path (Join-Path $ReviewRoot "photoidentity-multiperformer-track-attestation.json") -Label "Human multi-performer track attestation"

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) { $BodyRigPython=Join-Path $repoRoot ".venv\Scripts\python.exe" }
$BodyRigPython=Need-File -Path $BodyRigPython -Label "BodyRig Python"
$expectedModule=Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "Checkout BodyRig module"
$actualRaw=@(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $actualRaw.Count -ne 1) { throw "Could not verify checkout-bound BodyRig Python." }
$actualModule=[IO.Path]::GetFullPath(([string]$actualRaw[0]).Trim())
if (-not [string]::Equals($actualModule,$expectedModule,[StringComparison]::OrdinalIgnoreCase)) { throw "BodyRig Python imports from a different checkout: $actualModule" }

if ([string]::IsNullOrWhiteSpace($OutputDir)) { $OutputDir=Join-Path $ReviewRoot "target-isolation-candidates" }
$OutputDir=[IO.Path]::GetFullPath($OutputDir)
$repoBoundary=$repoRoot+[IO.Path]::DirectorySeparatorChar
if ([string]::Equals($OutputDir,$repoRoot,[StringComparison]::OrdinalIgnoreCase) -or $OutputDir.StartsWith($repoBoundary,[StringComparison]::OrdinalIgnoreCase)) { throw "Target-isolation output must be outside the BodyRig Git checkout." }
if (Test-Path -LiteralPath $OutputDir) { throw "Target-isolation output already exists: $OutputDir" }

Write-Host "BodyRig multi-performer target-isolation candidate materialization"
Write-Host "Revision: $head"
Write-Host "Interpolation: FALSE | Resize: FALSE | Generative pixels: FALSE"
Write-Host "Authority before human isolation review: FALSE"
& $BodyRigPython -m bodyrig.photoidentity_multiperformer_target_isolation --review-root $ReviewRoot --output-dir $OutputDir --current-revision $head
if ($LASTEXITCODE -ne 0) { throw "Target-isolation candidate materialization failed with exit code $LASTEXITCODE." }

$manifestPath=Need-File -Path (Join-Path $OutputDir "multiperformer-target-isolation-candidates.json") -Label "Target-isolation candidate manifest"
$privatePath=Need-File -Path (Join-Path $OutputDir "private-target-source\private-target-source-index.json") -Label "Private target-isolation index"
$manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50
$private=Get-Content -LiteralPath $privatePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50
if ([string]$manifest.bodyrig_revision -ne $head -or $manifest.target_isolated_source_authority -ne $false -or $manifest.target_isolation_human_review_required -ne $true) { throw "Target-isolation candidate manifest crossed authority boundary." }
foreach ($row in @($private.samples)) { Write-Host ("{0} | crop={1} | source-frame={2}" -f [string]$row.sample_id,[string]$row.target_track_crop,[string]$row.reviewed_source_frame) }
Write-Host ""
Write-Host "Review only the real source crops above. Record only samples containing the requested performer with no cross-person contamination."
Write-Host "Next: .\record-photoidentity-multiperformer-target-isolation.ps1 -CandidateRoot '$OutputDir' -SampleId <ids> -ConfirmTargetIsolation -QualityNote '<note>'"
Write-Host "Target-isolated source authority: FALSE"
Write-Host "Reconstruction permitted: FALSE"
