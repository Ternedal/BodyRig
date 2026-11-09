<#
.SYNOPSIS
Install and self-test the Blender scene inspector inside WSL2, isolated with bubblewrap.

.DESCRIPTION
Runs scripts/wsl_scene_inspector_setup.py inside the WSL distro (the default one,
or -Distro). It installs bubblewrap and Python 3.11 with apt where missing,
creates the hash-locked bpy venv, and inspects a Blender-generated corpus under
bubblewrap. It ends with "SCENE-INSPECTOR-WSL: PASS" or "... FAIL (<reason>)".
Safe to re-run. sudo inside WSL may ask for the WSL user's password.

-AllowUsernsSysctl lets the setup set kernel.apparmor_restrict_unprivileged_userns=0
in that distro, if Ubuntu's AppArmor blocks bubblewrap. Without it, the setup
stops and explains instead.
#>
param(
    [string]$Distro = "",
    [switch]$AllowUsernsSysctl,
    [switch]$SkipSmoke,
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if ($null -eq (Get-Command $WslExe -ErrorAction SilentlyContinue)) {
    throw "WSL not found ($WslExe). Install WSL2 with an Ubuntu distro first."
}
$distroArgs = @()
if ($Distro) { $distroArgs = @("-d", $Distro) }

$repo = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$convertArgs = $distroArgs + @("--exec", "wslpath", "-a", $repo)
$repoWsl = (& $WslExe @convertArgs | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repoWsl.StartsWith("/")) {
    throw "Could not translate the checkout path into WSL: $repo"
}

$setupArgs = $distroArgs + @("--cd", $repoWsl, "--exec", "python3", "scripts/wsl_scene_inspector_setup.py", "--repo", $repoWsl)
if ($AllowUsernsSysctl) { $setupArgs += "--allow-userns-sysctl" }
if ($SkipSmoke) { $setupArgs += "--skip-smoke" }
& $WslExe @setupArgs
exit $LASTEXITCODE
