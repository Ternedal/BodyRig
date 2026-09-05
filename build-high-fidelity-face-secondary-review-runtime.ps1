param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$OutputDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig face-secondary review runtime is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

function Assert-CheckoutAuthority {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[string]$ExpectedHead = "")
    $headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
    $head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Face-secondary review runtime requires an exact clean BodyRig checkout." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig checkout changed during face-secondary runtime creation."
    }
    return $head
}
function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Assert-CheckoutAuthority -RepoRoot $repoRoot
$PackagePath = Need-File -Path $PackagePath -Label "Promoted BodyRig package"
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Face-secondary output is create-only and already exists: $OutputDir" }
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) { throw "Python 3.11+ executable 'python' was not found." }
$python = $pythonCommand.Source
$versionText = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^(\d+)\.(\d+)$') { throw "Could not verify BodyRig Python runtime." }
if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 11)) { throw "BodyRig face-secondary runtime requires Python 3.11+." }

$priorPythonPath = $env:PYTHONPATH
$created = $false
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($priorPythonPath)) { $repoRoot } else { "$repoRoot;$priorPythonPath" }
    Push-Location $repoRoot
    try {
        $raw = @(& $python -m bodyrig.high_fidelity_face_secondary_runtime_cli build `
            --package $PackagePath `
            --output-dir $OutputDir `
            --bodyrig-revision $head)
        if ($LASTEXITCODE -ne 0) { throw "Face-secondary runtime CLI failed with exit code $LASTEXITCODE." }
    } finally { Pop-Location }
    $created = Test-Path -LiteralPath $OutputDir -PathType Container
    try { $result = (($raw -join "`n").Trim() | ConvertFrom-Json -Depth 30) }
    catch { throw "Face-secondary runtime CLI returned unreadable JSON." }
    if ($result.ok -ne $true -or [string]$result.mode -ne "build") { throw "Face-secondary runtime did not report canonical PASS." }
    if ($result.face_secondary_component_authority -ne $false -or $result.package_mutation_performed -ne $false -or $result.production_activation -ne $false) {
        throw "Face-secondary review runtime crossed component/package/production authority."
    }
    $expected = @("eyebrow_appearance", "lip_boundary", "mouth_interior", "teeth", "eyelashes")
    foreach ($name in $expected) {
        if ([string]$result.candidate_components.$name -ne "partial") { throw "Face-secondary candidate component $name is not review-pending partial." }
    }
    [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head)
} catch {
    if ($created -and (Test-Path -LiteralPath $OutputDir -PathType Container)) {
        Remove-Item -LiteralPath $OutputDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
} finally {
    $env:PYTHONPATH = $priorPythonPath
}

Write-Host "BodyRig face-secondary review runtime: READY"
Write-Host "Output:           $OutputDir"
Write-Host "Revision:         $head"
Write-Host "Eyebrows:         SOURCE APPEARANCE / REVIEW REQUIRED"
Write-Host "Lip boundary:     SOURCE APPEARANCE / REVIEW REQUIRED"
Write-Host "Mouth interior:   GENERIC SECONDARY ANATOMY / REVIEW REQUIRED"
Write-Host "Teeth:            GENERIC SECONDARY ANATOMY / REVIEW REQUIRED"
Write-Host "Eyelashes:        SMPL-X ANCHORED / REVIEW REQUIRED"
Write-Host "Component auth:   FALSE"
Write-Host "Production:       FALSE"
exit 0
