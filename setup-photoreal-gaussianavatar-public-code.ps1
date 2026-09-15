param(
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxDependencyRoot = "/opt/bodyrig-gaussianavatar/deps",
    [string]$WslExe = "wsl.exe",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$gaRepository = "https://github.com/aipixel/GaussianAvatar.git"
$gaCommit = "d981c62238ef64e89dcc04719d2ebbb4758b080a"
$iaRepository = "https://github.com/tijiang13/InstantAvatar.git"
$iaCommit = "3cdfd49d00a5e6c1ebde4d6ae2784b5d6f7cd2bc"

if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "Distribution is required." }
if ([string]::IsNullOrWhiteSpace($LinuxDependencyRoot) -or -not $LinuxDependencyRoot.StartsWith('/')) {
    throw "LinuxDependencyRoot must be an absolute Linux path."
}
if ($LinuxDependencyRoot -eq "/") { throw "LinuxDependencyRoot may not be '/'." }

function Invoke-Wsl {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$Root,
        [switch]$Capture
    )
    $prefix = @("-d", $Distribution)
    if ($Root) { $prefix += @("-u", "root") }
    $prefix += "--"
    if ($Capture) {
        $output = @(& $WslExe @prefix @Arguments 2>&1)
        $code = $LASTEXITCODE
        if ($code -ne 0) {
            throw "WSL command failed ($code): $($Arguments -join ' ')`n$($output -join [Environment]::NewLine)"
        }
        return ,$output
    }
    & $WslExe @prefix @Arguments
    $code = $LASTEXITCODE
    if ($code -ne 0) { throw "WSL command failed ($code): $($Arguments -join ' ')" }
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL GAUSSIANAVATAR PUBLIC CODE"
Write-Host "Distribution:       $Distribution"
Write-Host "Dependency root:    $LinuxDependencyRoot"
Write-Host "GaussianAvatar:     $gaCommit"
Write-Host "InstantAvatar:      $iaCommit"
Write-Host "Model assets:       NOT DOWNLOADED"
Write-Host "Photoreal authority: FALSE"
Write-Host "Production:          FALSE"
Write-Host "============================================================"

Invoke-Wsl -Arguments @("/usr/bin/env", "true")
Invoke-Wsl -Root -Arguments @("/usr/bin/apt-get", "update")
Invoke-Wsl -Root -Arguments @("/usr/bin/apt-get", "install", "-y", "git")

$parent = ($LinuxDependencyRoot.TrimEnd('/') -replace '/[^/]+$', '')
if ([string]::IsNullOrWhiteSpace($parent)) { $parent = "/" }
$leaf = ($LinuxDependencyRoot.TrimEnd('/') -split '/')[-1]
$stage = "$parent/.$leaf.stage-$PID"

& $WslExe -d $Distribution -- /usr/bin/test -e $LinuxDependencyRoot 2>$null
$exists = $LASTEXITCODE -eq 0
if ($exists -and -not $Force) {
    throw "GaussianAvatar dependency root already exists: $LinuxDependencyRoot. Use -Force only for an intentional replacement."
}

Invoke-Wsl -Root -Arguments @("/bin/rm", "-rf", $stage)
Invoke-Wsl -Root -Arguments @("/bin/mkdir", "-p", $stage)

try {
    $ga = "$stage/GaussianAvatar"
    $ia = "$stage/InstantAvatar"

    Invoke-Wsl -Root -Arguments @("git", "clone", "--no-checkout", $gaRepository, $ga)
    Invoke-Wsl -Root -Arguments @("git", "-C", $ga, "checkout", "--detach", $gaCommit)
    Invoke-Wsl -Root -Arguments @("git", "clone", "--no-checkout", $iaRepository, $ia)
    Invoke-Wsl -Root -Arguments @("git", "-C", $ia, "checkout", "--detach", $iaCommit)

    foreach ($pair in @(@($ga, $gaCommit, "GaussianAvatar"), @($ia, $iaCommit, "InstantAvatar"))) {
        $observed = ((Invoke-Wsl -Arguments @("git", "-C", [string]$pair[0], "rev-parse", "HEAD") -Capture | Select-Object -Last 1).ToString().Trim()).ToLowerInvariant()
        if ($observed -ne [string]$pair[1]) { throw "$($pair[2]) commit mismatch: $observed" }
        $dirty = @(Invoke-Wsl -Arguments @("git", "-C", [string]$pair[0], "status", "--porcelain") -Capture)
        if (($dirty -join "").Trim().Length -ne 0) { throw "$($pair[2]) checkout is dirty immediately after setup." }
    }

    $receiptCode = @'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
payload = {
    "format": "bodyrig-photoreal-gaussianavatar-public-code",
    "version": 1,
    "gaussianavatar_commit": sys.argv[2],
    "instantavatar_commit": sys.argv[3],
    "automatic_model_asset_download": False,
    "photoreal_acceptance_authority": False,
    "build_only": True,
    "production_dependency_authorized": False,
    "production_activation": False,
}
raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
payload["public_code_sha256"] = hashlib.sha256(raw).hexdigest()
(root / "bodyrig-gaussianavatar-public-code.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
    encoding="utf-8",
)
'@
    Invoke-Wsl -Root -Arguments @("/usr/bin/python3", "-c", $receiptCode, $stage, $gaCommit, $iaCommit)

    if ($exists) {
        Invoke-Wsl -Root -Arguments @("/bin/rm", "-rf", $LinuxDependencyRoot)
    }
    Invoke-Wsl -Root -Arguments @("/bin/mv", $stage, $LinuxDependencyRoot)
}
catch {
    try { Invoke-Wsl -Root -Arguments @("/bin/rm", "-rf", $stage) } catch {}
    throw
}

Write-Host ""
Write-Host "BodyRig GaussianAvatar public code: READY"
Write-Host "Dependency root:     $LinuxDependencyRoot"
Write-Host "Model assets:        OPERATOR-SUPPLIED"
Write-Host "Photoreal authority: FALSE"
Write-Host "Production:          FALSE"
