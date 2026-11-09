<#
.SYNOPSIS
Convert 3D assets (Open3DLab packs, XPS, FBX, BLEND, glTF) to VRM 1.0 inside WSL2,
always isolated with bubblewrap.

.DESCRIPTION
Windows front end for `bodyrig-vrm-export`. Blender runs in the WSL distro set up
by setup-scene-inspector-wsl.ps1 + setup-vrm-export-wsl.ps1. Inputs and the
output folder stay on Windows; the cache and private staging copies live on the
WSL file system. Each asset gives <Out>\<name>.vrm and <name>.vrm.json.

-Inbox keeps running: every file or folder dropped there is converted and moved to
Inbox\done or Inbox\failed. Stop it with Ctrl+C.

Isolation is fixed to bubblewrap; without it the run stops (exit 2).
Exit codes: 0 = every asset READY, 1 = at least one FAILED, 2 = setup error.

.EXAMPLE
.\run-vrm-export-wsl.ps1 -Asset C:\packs\model.zip, C:\packs\hero.fbx -Out C:\BodyRig\vrm-out

.EXAMPLE
.\run-vrm-export-wsl.ps1 -Inbox C:\BodyRig\vrm-inbox -Out C:\BodyRig\vrm-out
#>
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [string[]]$Asset = @(),
    [string]$Inbox = "",
    [double]$TimeoutSeconds = 300,
    [double]$MemoryGB = 8,
    [int]$MaxTexture = 2048,
    [string]$Distro = "",
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if ($null -eq (Get-Command $WslExe -ErrorAction SilentlyContinue)) {
    throw "WSL not found ($WslExe). Run setup-scene-inspector-wsl.ps1 after installing WSL2."
}
if (($Asset.Count -eq 0) -eq (-not $Inbox)) { throw "Give either -Asset (one or more) or -Inbox." }
New-Item -ItemType Directory -Force -Path $Out | Out-Null
if ($Inbox) { New-Item -ItemType Directory -Force -Path $Inbox | Out-Null }

$distroArgs = @()
if ($Distro) { $distroArgs = @("-d", $Distro) }

function ConvertTo-WslPath {
    param([Parameter(Mandatory = $true)][string]$WindowsPath)
    $full = (Resolve-Path -LiteralPath $WindowsPath).Path
    $convertArgs = $distroArgs + @("--exec", "wslpath", "-a", $full)
    $converted = (& $WslExe @convertArgs | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $converted.StartsWith("/")) { throw "Could not translate into WSL: $full" }
    return $converted
}

$repoWsl = ConvertTo-WslPath $PSScriptRoot
$outWsl = ConvertTo-WslPath $Out

$stateArgs = $distroArgs + @("--exec", "sh", "-c", 'cat "$HOME/.cache/bodyrig/scene-inspector-wsl.json"')
$stateText = (& $WslExe @stateArgs 2>$null | Out-String)
if ($LASTEXITCODE -ne 0 -or -not $stateText.Trim()) {
    throw "The WSL scene inspector is not set up. Run .\setup-scene-inspector-wsl.ps1 first."
}
$state = $stateText | ConvertFrom-Json
$homeArgs = $distroArgs + @("--exec", "printenv", "HOME")
$homeWsl = (& $WslExe @homeArgs | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $homeWsl.StartsWith("/")) { throw "Could not read the WSL home directory." }
$addonsWsl = "$homeWsl/.local/share/bodyrig/vrm-addons"
$cacheWsl = "$homeWsl/.cache/bodyrig/vrm-cache"

$common = @(
    "--out", $outWsl, "--addons", $addonsWsl, "--cache", $cacheWsl, "--work-root", $state.work_root,
    "--bpy-python", $state.bpy_python, "--isolation", "bwrap",
    "--timeout", "$TimeoutSeconds", "--memory-gb", "$MemoryGB", "--max-texture", "$MaxTexture"
)
$cli = @("--cd", $repoWsl, "--exec", "env", "PYTHONPATH=$repoWsl", "PYTHONDONTWRITEBYTECODE=1",
         $state.host_python, "-m", "bodyrig.vrm_export_cli")
if ($Inbox) {
    $cli += @("watch", "--inbox", (ConvertTo-WslPath $Inbox)) + $common
} else {
    $cli += @("export") + @($Asset | ForEach-Object { ConvertTo-WslPath $_ }) + $common
}

$allArgs = $distroArgs + $cli
& $WslExe @allArgs
exit $LASTEXITCODE
