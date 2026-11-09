<#
.SYNOPSIS
Install the pinned Blender add-ons for the VRM export inside WSL2.

.DESCRIPTION
Needs the WSL scene inspector set up first (.\setup-scene-inspector-wsl.ps1): the
VRM export reuses its bpy venv, its bubblewrap and its state file. This script
runs scripts/vrm_export_setup.py inside the WSL distro (wsl.exe --exec, no shell),
which fetches the VRM Add-on for Blender and XNALara-io-Tools at the commits
pinned in bodyrig/vrm_export.py (ADDON_PINS), applies the XPS root-bone patch and
writes ~/.local/share/bodyrig/vrm-addons. Safe to re-run; needs network once.
It ends with "VRM-EXPORT-WSL: PASS" or throws.
#>
param(
    [string]$Distro = "",
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if ($null -eq (Get-Command $WslExe -ErrorAction SilentlyContinue)) {
    throw "WSL not found ($WslExe). Install WSL2 and run .\setup-scene-inspector-wsl.ps1 first."
}
$distroArgs = @()
if ($Distro) { $distroArgs = @("-d", $Distro) }

$repo = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$convertArgs = $distroArgs + @("--exec", "wslpath", "-a", $repo)
$repoWsl = (& $WslExe @convertArgs | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repoWsl.StartsWith("/")) {
    throw "Could not translate the checkout path into WSL: $repo"
}

$stateArgs = $distroArgs + @("--exec", "sh", "-c", 'cat "$HOME/.cache/bodyrig/scene-inspector-wsl.json"')
$stateText = (& $WslExe @stateArgs 2>$null | Out-String)
if ($LASTEXITCODE -ne 0 -or -not $stateText.Trim()) {
    throw "The WSL scene inspector is not set up. Run .\setup-scene-inspector-wsl.ps1 first."
}
$state = $stateText | ConvertFrom-Json
$homeArgs = $distroArgs + @("--exec", "printenv", "HOME")
$homeWsl = (& $WslExe @homeArgs | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $homeWsl.StartsWith("/")) { throw "Could not read the WSL home directory." }

$setupArgs = $distroArgs + @(
    "--cd", $repoWsl, "--exec", "env", "PYTHONPATH=$repoWsl", "PYTHONDONTWRITEBYTECODE=1",
    $state.host_python, "scripts/vrm_export_setup.py", "--addons", "$homeWsl/.local/share/bodyrig/vrm-addons"
)
& $WslExe @setupArgs
if ($LASTEXITCODE -ne 0) { throw "VRM add-on setup failed (exit $LASTEXITCODE)." }
Write-Host "VRM-EXPORT-WSL: PASS (add-ons installed)"
