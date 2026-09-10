param(
    [Parameter(Mandatory = $true)][string]$CandidateRoot,
    [Parameter(Mandatory = $true)][string]$BaselineCloneOutput,
    [string]$OutputDir = "",
    [string]$BodyRigPython = "",
    [string]$SchpRuntimeRoot = ""
)

$ErrorActionPreference="Stop"
Set-StrictMode -Version Latest
function Need-File { param([string]$Path,[string]$Label); if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){throw "$Label not found: $Path"}; (Resolve-Path -LiteralPath $Path).Path }
function Need-Directory { param([string]$Path,[string]$Label); if(-not(Test-Path -LiteralPath $Path -PathType Container)){throw "$Label not found: $Path"}; (Resolve-Path -LiteralPath $Path).Path }
function Need-CommandArgument { param([object[]]$Command,[string]$Name,[string]$Label); $indices=@(); for($i=0;$i -lt $Command.Count;$i++){if([string]$Command[$i] -eq $Name){$indices += $i}}; if($indices.Count -ne 1){throw "$Label requires exactly one $Name binding."}; $valueIndex=[int]$indices[0]+1; if($valueIndex -ge $Command.Count){throw "$Label has incomplete $Name binding."}; $value=([string]$Command[$valueIndex]).Trim(); if([string]::IsNullOrWhiteSpace($value)){throw "$Label has empty $Name binding."}; return $value }

if([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT){throw "BodyRig target-crop enrichment is Windows-only."}
if($PSVersionTable.PSVersion.Major -lt 7){throw "PowerShell 7+ is required."}
$repoRoot=(Resolve-Path $PSScriptRoot).Path
$headRaw=@(& git -C $repoRoot rev-parse HEAD 2>&1)
if($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$'){throw "Could not bind target-crop enrichment to exact BodyRig Git HEAD."}
$head=([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty=@(& git -C $repoRoot status --porcelain 2>&1)
if($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0){throw "Target-crop enrichment requires an exact clean BodyRig checkout."}

$CandidateRoot=Need-Directory -Path $CandidateRoot -Label "Human-reviewed target-isolation candidate root"
$null=Need-File -Path (Join-Path $CandidateRoot "photoidentity-multiperformer-target-isolation-attestation.json") -Label "Human target-isolation receipt"
$BaselineCloneOutput=Need-Directory -Path $BaselineCloneOutput -Label "Baseline Stash clone output"
$fitterConfig=Need-File -Path (Join-Path $BaselineCloneOutput "bodyrig-sith-fitter-config.json") -Label "Baseline pinned SiTH fitter config"
$fitter=Get-Content -LiteralPath $fitterConfig -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20
if([string]$fitter.format -ne "bodyrig-external-fitter-config" -or [int]$fitter.version -ne 1 -or [string]$fitter.adapter -ne "sith-smplx-vrm" -or [string]$fitter.revision -ne "1"){throw "Target-crop enrichment requires exact built-in pinned SiTH fitter authority."}
$command=@($fitter.command)
$distribution=Need-CommandArgument -Command $command -Name "--distribution" -Label "SiTH/OpenPose runtime"
$sithRepo=Need-CommandArgument -Command $command -Name "--sith-repo" -Label "SiTH/OpenPose runtime"
$sithPython=Need-CommandArgument -Command $command -Name "--sith-python" -Label "SiTH/OpenPose runtime"
$openpose=Need-CommandArgument -Command $command -Name "--openpose" -Label "SiTH/OpenPose runtime"
$wslExe=Need-CommandArgument -Command $command -Name "--wsl-exe" -Label "SiTH/OpenPose runtime"
if(-not $sithRepo.StartsWith("/") -or -not $sithPython.StartsWith("/") -or -not $openpose.StartsWith("/")){throw "Pinned SiTH/OpenPose runtime paths must be absolute WSL paths."}
$opSuffix="/build/examples/openpose/openpose.bin"
if(-not $openpose.EndsWith($opSuffix,[StringComparison]::Ordinal)){throw "Pinned OpenPose path uses unexpected repository layout."}
$openposeRepo=$openpose.Substring(0,$openpose.Length-$opSuffix.Length)
$wslCommand=Get-Command $wslExe -ErrorAction SilentlyContinue
if($null -eq $wslCommand){throw "WSL executable not found: $wslExe"}
$wslExe=$wslCommand.Source

if([string]::IsNullOrWhiteSpace($BodyRigPython)){$BodyRigPython=Join-Path $repoRoot ".venv\Scripts\python.exe"}
$BodyRigPython=Need-File -Path $BodyRigPython -Label "BodyRig Python"
$expected=Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "Checkout BodyRig module"
$actual=@(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if($LASTEXITCODE -ne 0 -or $actual.Count -ne 1 -or -not [string]::Equals([IO.Path]::GetFullPath(([string]$actual[0]).Trim()),$expected,[StringComparison]::OrdinalIgnoreCase)){throw "BodyRig Python is not bound to this checkout."}

& $BodyRigPython -m bodyrig.sith_preflight --distribution $distribution --repo $sithRepo --python $sithPython --openpose $openpose --openpose-repo $openposeRepo --wsl-exe $wslExe
if($LASTEXITCODE -ne 0){throw "Pinned SiTH/OpenPose target-crop preflight failed."}

if([string]::IsNullOrWhiteSpace($SchpRuntimeRoot)){
    if([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)){throw "LOCALAPPDATA is required for default SCHP runtime."}
    $SchpRuntimeRoot=Join-Path $env:LOCALAPPDATA "BodyRig\runtimes\schp-atr18-v1"
}
$SchpRuntimeRoot=[IO.Path]::GetFullPath($SchpRuntimeRoot)
if(-not(Test-Path -LiteralPath $SchpRuntimeRoot -PathType Container)){
    & (Need-File -Path (Join-Path $repoRoot "setup-photoidentity-schp-windows.ps1") -Label "SCHP setup operator") -RuntimeRoot $SchpRuntimeRoot -BodyRigPython $BodyRigPython
    if($LASTEXITCODE -ne 0){throw "Pinned SCHP runtime provisioning failed."}
}
& $BodyRigPython -m bodyrig.photoidentity_schp_preflight --runtime-root $SchpRuntimeRoot
if($LASTEXITCODE -ne 0){throw "Pinned SCHP runtime preflight failed."}

if([string]::IsNullOrWhiteSpace($OutputDir)){$OutputDir=Join-Path $CandidateRoot "target-crop-detail-enrichment"}
$OutputDir=[IO.Path]::GetFullPath($OutputDir)
$repoBoundary=$repoRoot+[IO.Path]::DirectorySeparatorChar
if([string]::Equals($OutputDir,$repoRoot,[StringComparison]::OrdinalIgnoreCase) -or $OutputDir.StartsWith($repoBoundary,[StringComparison]::OrdinalIgnoreCase)){throw "Target-crop enrichment output must be outside the Git checkout."}
if(Test-Path -LiteralPath $OutputDir){throw "Target-crop enrichment output already exists: $OutputDir"}

Write-Host "BodyRig human-isolated target-crop detail enrichment"
Write-Host "Revision: $head"
Write-Host "Authority: machine observability candidates only"
Write-Host "Domains: eyes, hands, feet, hair/hairline, exposed skin"
Write-Host "Anatomy/rear/nails authority: NONE"
& $BodyRigPython -m bodyrig.photoidentity_target_crop_enrich --candidate-root $CandidateRoot --output-dir $OutputDir --current-revision $head --distribution $distribution --openpose $openpose --wsl-exe $wslExe --schp-runtime-root $SchpRuntimeRoot --repo-root $repoRoot
if($LASTEXITCODE -ne 0){throw "Target-crop detail enrichment failed with exit code $LASTEXITCODE."}

$receipt=Need-File -Path (Join-Path $OutputDir "target-crop-detail-enrichment.json") -Label "Target-crop detail enrichment receipt"
$result=Get-Content -LiteralPath $receipt -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 60
if([string]$result.bodyrig_revision -ne $head -or $result.machine_observability_only -ne $true -or $result.source_detail_quality_authority -ne $false -or $result.photoidentity_source_evidence_authority -ne $false -or $result.reconstruction_permitted -ne $false -or $result.production_activation -ne $false){throw "Target-crop detail receipt crossed authority boundary."}
Write-Host "Evidence: $receipt"
Write-Host "Source detail quality authority: FALSE"
Write-Host "Photoidentity sufficiency authority: FALSE"
Write-Host "Reconstruction permitted: FALSE"
