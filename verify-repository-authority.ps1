param(
    [switch]$Json,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Revision {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not an exact Git revision." }
    return $normalized
}

function Invoke-GhJson {
    param(
        [Parameter(Mandatory = $true)][string]$ApiPath,
        [switch]$AllowFailure
    )
    $raw = @(& gh api $ApiPath 2>&1)
    if ($LASTEXITCODE -ne 0) {
        if ($AllowFailure) { return $null }
        throw "GitHub API read failed for repository-authority endpoint: $ApiPath"
    }
    $text = $raw -join "`n"
    try { return ($text | ConvertFrom-Json -Depth 60) }
    catch { throw "GitHub API returned unreadable JSON for repository-authority endpoint: $ApiPath" }
}

function Write-TempJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    $Value | ConvertTo-Json -Depth 60 | Set-Content -LiteralPath $Path -Encoding UTF8
}

if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") {
    throw "Repository-authority verification must run from branch main."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Repository-authority verification requires an exact clean main checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = Need-Revision -Value ([string]$headRaw[0]) -Label "BodyRig HEAD"

$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($null -eq $gh) { throw "GitHub CLI (gh) is required for authoritative repository-settings verification." }
@(& gh auth status -h github.com 2>&1) | Out-Null
if ($LASTEXITCODE -ne 0) { throw "GitHub CLI is not authenticated for github.com." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $BodyRigPython = $venvPython }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = (Resolve-Path -LiteralPath $BodyRigPython).Path

$oldPythonPath = [string]$env:PYTHONPATH
$oldNoBytecode = [string]$env:PYTHONDONTWRITEBYTECODE
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-repository-authority-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$oldPythonPath" })
    $env:PYTHONDONTWRITEBYTECODE = "1"

    $moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig.repository_authority as m; print(pathlib.Path(m.__file__).resolve())" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw "Could not prove checkout-bound repository-authority evaluator." }
    $expectedModule = [IO.Path]::GetFullPath((Join-Path $repoRoot "bodyrig\repository_authority.py"))
    $actualModule = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
    if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Repository-authority evaluator imported from wrong checkout: $actualModule"
    }

    $branch = Invoke-GhJson -ApiPath "repos/Ternedal/BodyRig/branches/main"
    $classic = Invoke-GhJson -ApiPath "repos/Ternedal/BodyRig/branches/main/protection" -AllowFailure
    $rulesetSummaries = Invoke-GhJson -ApiPath "repos/Ternedal/BodyRig/rulesets?includes_parents=true" -AllowFailure
    $rulesets = @()
    if ($null -ne $rulesetSummaries) {
        foreach ($summary in @($rulesetSummaries)) {
            $id = [string]$summary.id
            if ($id -notmatch '^[0-9]+$') { continue }
            $detail = Invoke-GhJson -ApiPath "repos/Ternedal/BodyRig/rulesets/$id" -AllowFailure
            if ($null -ne $detail) { $rulesets += $detail }
        }
    }

    $branchPath = Join-Path $tempRoot "branch.json"
    $classicPath = Join-Path $tempRoot "classic.json"
    $rulesetsPath = Join-Path $tempRoot "rulesets.json"
    Write-TempJson -Path $branchPath -Value $branch
    if ($null -ne $classic) { Write-TempJson -Path $classicPath -Value $classic }
    Write-TempJson -Path $rulesetsPath -Value $rulesets

    $args = @("-m", "bodyrig.repository_authority", "--branch-json", $branchPath, "--rulesets-json", $rulesetsPath, "--expected-head", $head)
    if ($null -ne $classic) { $args += @("--classic-json", $classicPath) }
    $resultRaw = @(& $BodyRigPython @args 2>&1)
    $exitCode = $LASTEXITCODE
    if ($resultRaw.Count -ne 1) { throw "Repository-authority evaluator did not return exactly one JSON result." }
    try { $result = ([string]$resultRaw[0]) | ConvertFrom-Json -Depth 60 }
    catch { throw "Repository-authority evaluator returned unreadable JSON." }
    if ([string]$result.format -ne "bodyrig-repository-authority" -or [int]$result.version -ne 1) {
        throw "Repository-authority evaluator returned unexpected format/version."
    }

    if ($Json) {
        $result | ConvertTo-Json -Depth 60 -Compress
    } else {
        Write-Host "BodyRig repository authority: $(if ($result.passed) { 'PASS' } else { 'FAIL' })"
        Write-Host "Repository: Ternedal/BodyRig"
        Write-Host "Branch:     main"
        Write-Host "Head:       $head"
        Write-Host "Protected:  $($result.protected)"
        Write-Host "Mode:       $(if ($null -ne $result.authority_mode) { $result.authority_mode } else { '<none>' })"
        if (@($result.errors).Count -gt 0) {
            Write-Host "Errors:"
            foreach ($item in @($result.errors)) { Write-Host "  - $item" }
        }
        if (@($result.warnings).Count -gt 0) {
            Write-Host "Warnings:"
            foreach ($item in @($result.warnings)) { Write-Host "  - $item" }
        }
        Write-Host "Authority: repository settings only; no physical acceptance or production activation."
    }
    if ($exitCode -ne 0 -or $result.passed -ne $true) { exit 2 }
    exit 0
}
finally {
    if (Test-Path -LiteralPath $tempRoot -PathType Container) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
    if ([string]::IsNullOrEmpty($oldPythonPath)) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
    if ([string]::IsNullOrEmpty($oldNoBytecode)) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue } else { $env:PYTHONDONTWRITEBYTECODE = $oldNoBytecode }
}
