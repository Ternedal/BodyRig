param(
    [Parameter(Mandatory = $true)][string]$CandidateRoot,
    [Parameter(Mandatory = $true)][string[]]$SampleId,
    [Parameter(Mandatory = $true)][switch]$ConfirmTargetIsolation,
    [Parameter(Mandatory = $true)][ValidateLength(10,1000)][string]$QualityNote,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference="Stop"
Set-StrictMode -Version Latest
function Need-File { param([string]$Path,[string]$Label); if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){throw "$Label not found: $Path"}; (Resolve-Path -LiteralPath $Path).Path }
function Need-Directory { param([string]$Path,[string]$Label); if(-not(Test-Path -LiteralPath $Path -PathType Container)){throw "$Label not found: $Path"}; (Resolve-Path -LiteralPath $Path).Path }

if([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT){throw "BodyRig target-isolation attestation is Windows-only."}
if($PSVersionTable.PSVersion.Major -lt 7){throw "PowerShell 7+ is required."}
$repoRoot=(Resolve-Path $PSScriptRoot).Path
$headRaw=@(& git -C $repoRoot rev-parse HEAD 2>&1)
if($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$'){throw "Could not bind target-isolation attestation to exact BodyRig Git HEAD."}
$head=([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty=@(& git -C $repoRoot status --porcelain 2>&1)
if($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0){throw "Target-isolation attestation requires an exact clean BodyRig checkout."}
$CandidateRoot=Need-Directory -Path $CandidateRoot -Label "Target-isolation candidate root"
$null=Need-File -Path (Join-Path $CandidateRoot "multiperformer-target-isolation-candidates.json") -Label "Target-isolation candidate manifest"

if([string]::IsNullOrWhiteSpace($BodyRigPython)){$BodyRigPython=Join-Path $repoRoot ".venv\Scripts\python.exe"}
$BodyRigPython=Need-File -Path $BodyRigPython -Label "BodyRig Python"
$expected=Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "Checkout BodyRig module"
$actual=@(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if($LASTEXITCODE -ne 0 -or $actual.Count -ne 1){throw "Could not verify checkout-bound BodyRig Python."}
if(-not [string]::Equals([IO.Path]::GetFullPath(([string]$actual[0]).Trim()),$expected,[StringComparison]::OrdinalIgnoreCase)){throw "BodyRig Python imports from a different checkout."}

$argsList=@("-m","bodyrig.photoidentity_multiperformer_target_attestation","--candidate-root",$CandidateRoot,"--current-revision",$head,"--quality-note",$QualityNote,"--confirm-target-isolation")
foreach($id in $SampleId){ if([string]::IsNullOrWhiteSpace($id)){throw "SampleId cannot be empty."}; $argsList += @("--sample-id",$id) }
& $BodyRigPython @argsList
if($LASTEXITCODE -ne 0){throw "Target-isolation human attestation failed with exit code $LASTEXITCODE."}

$receipt=Need-File -Path (Join-Path $CandidateRoot "photoidentity-multiperformer-target-isolation-attestation.json") -Label "Target-isolation human receipt"
$raw=Get-Content -LiteralPath $receipt -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50
if([string]$raw.bodyrig_revision -ne $head -or $raw.human_target_isolation_attested -ne $true -or $raw.target_isolated_source_authority -ne $true){throw "Target-isolation receipt lacks required human authority."}
if($raw.photoidentity_source_evidence_authority -ne $false -or $raw.reconstruction_permitted -ne $false -or $raw.production_activation -ne $false){throw "Target-isolation receipt crossed downstream authority boundary."}
Write-Host "BodyRig target isolation human attestation: RECORDED"
Write-Host "Accepted samples: $([int]$raw.accepted_sample_count)"
Write-Host "Authority scope: accepted-samples-only"
Write-Host "Photoidentity source sufficiency: FALSE"
Write-Host "Reconstruction permitted: FALSE"
