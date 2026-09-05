param(
    [Parameter(Mandatory = $true)][string]$SourceEyeAppearanceDir,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [Parameter(Mandatory = $true)][int]$LeftCx,
    [Parameter(Mandatory = $true)][int]$LeftCy,
    [Parameter(Mandatory = $true)][int]$LeftRadius,
    [Parameter(Mandatory = $true)][int]$RightCx,
    [Parameter(Mandatory = $true)][int]$RightCy,
    [Parameter(Mandatory = $true)][int]$RightRadius
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig iris-isolation candidate path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

function Assert-CheckoutAuthority {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[string]$ExpectedHead = "")
    $headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
    $head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Iris isolation requires an exact clean BodyRig checkout." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig checkout changed during iris isolation."
    }
    return $head
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Assert-CheckoutAuthority -RepoRoot $repoRoot
$sourceDir = (Resolve-Path -LiteralPath $SourceEyeAppearanceDir).Path
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Iris isolation output already exists: $OutputDir" }
$python = (Get-Command python -ErrorAction Stop).Source
$version = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or [version]$version -lt [version]"3.11") { throw "BodyRig Python 3.11+ is required." }

$previousPythonPath = $env:PYTHONPATH
$created = $false
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    $raw = @(& $python -m bodyrig.source_iris_isolation_cli candidate `
        --source-eye-appearance-dir $sourceDir `
        --output-dir $OutputDir `
        --bodyrig-revision $head `
        --left-cx $LeftCx --left-cy $LeftCy --left-radius $LeftRadius `
        --right-cx $RightCx --right-cy $RightCy --right-radius $RightRadius)
    if ($LASTEXITCODE -ne 0) { throw "Iris isolation candidate CLI failed with exit code $LASTEXITCODE." }
    try { $result = (($raw -join "`n").Trim() | ConvertFrom-Json -Depth 20) }
    catch { throw "Iris isolation candidate CLI returned unreadable JSON." }
    if ($result.ok -ne $true -or [string]$result.mode -ne "candidate") { throw "Iris isolation candidate CLI did not report canonical PASS." }
    if ([string]$result.bodyrig_revision -ne $head) { throw "Iris candidate was produced by a different BodyRig revision." }
    if ($result.iris_identity_isolated -ne $false -or $result.human_review_required -ne $true) {
        throw "Iris candidate crossed the pre-review authority boundary."
    }
    if ($result.eye_component_authority -ne $false -or $result.production_activation -ne $false) {
        throw "Iris candidate crossed component/production authority."
    }
    foreach ($path in @([string]$result.candidate_path,[string]$result.left_path,[string]$result.right_path)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Iris candidate artifact missing: $path" }
    }
    $created = $true
    try { [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head) }
    catch {
        if ($created -and (Test-Path -LiteralPath $OutputDir -PathType Container)) {
            Remove-Item -LiteralPath $OutputDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw "BodyRig checkout changed after iris candidate creation; removed newly created candidate directory. $($_.Exception.Message)"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig source iris isolation: CANDIDATE READY"
Write-Host "Output:          $OutputDir"
Write-Host "Revision:        $head"
Write-Host "Human review:    REQUIRED"
Write-Host "Iris authority:  FALSE until explicit review"
Write-Host "Eyes authority:  FALSE"
Write-Host "Production:      FALSE"
exit 0
