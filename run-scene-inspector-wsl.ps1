<#
.SYNOPSIS
Inspect 3D assets with Blender inside WSL2, always isolated with bubblewrap.

.DESCRIPTION
Windows front end for `bodyrig-scene-inspect`. The inspector and Blender run in
the WSL distro set up by setup-scene-inspector-wsl.ps1. The source folder (-Root)
and the output folder (-Out) stay on Windows. The cache and the private staging
copies live on the WSL file system.

Isolation is fixed to bubblewrap. If it is not available, the run stops (exit 2)
instead of falling back to an unisolated run.

Every run has a total time budget (-Budget, default 60m). No asset starts after
it and no Blender worker runs past it. Finished results are kept, and running
the same command again continues from the cache. Each run ends with a
PASS/FAIL line per #1393 speed target.

Exit codes are those of the CLI: 0 = every asset analysed, 1 = at least one
asset FAILED (the rest were still processed), 2 = setup error, 3 = the time
budget ran out first (run the same command again to continue).

.EXAMPLE
.\run-scene-inspector-wsl.ps1 -Root C:\assets\staging -All -Out C:\assets\scene-out

.EXAMPLE
.\run-scene-inspector-wsl.ps1 -Root C:\assets\staging -All -Out C:\assets\scene-out -Budget 15m

.EXAMPLE
.\run-scene-inspector-wsl.ps1 -Root C:\assets\staging -All -Out C:\assets\scene-bench -Bench -Runs 3
#>
param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$Out,
    [string[]]$Asset = @(),
    [switch]$All,
    [string]$Conditioning = "pose,depth,normal",
    [int]$Resolution = 512,
    [int]$Jobs = 2,
    [double]$TimeoutSeconds = 120,
    [string]$Budget = "60m",
    [double]$MemoryGB = 8,
    [switch]$MinimumOnly,
    [switch]$Bench,
    [int]$Runs = 3,
    [string]$Distro = "",
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if ($null -eq (Get-Command $WslExe -ErrorAction SilentlyContinue)) {
    throw "WSL not found ($WslExe). Run setup-scene-inspector-wsl.ps1 after installing WSL2."
}
if (-not (Test-Path -LiteralPath $Root -PathType Container)) { throw "Root folder not found: $Root" }
if (-not $All -and $Asset.Count -eq 0) { throw "Give -All or at least one -Asset (relative to -Root)." }
New-Item -ItemType Directory -Force -Path $Out | Out-Null
# Resolve against the PowerShell location, not the process directory.
$Root = (Resolve-Path -LiteralPath $Root).Path
$Out = (Resolve-Path -LiteralPath $Out).Path

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
$rootWsl = ConvertTo-WslPath $Root
$outWsl = ConvertTo-WslPath $Out

$stateArgs = $distroArgs + @("--exec", "sh", "-c", 'cat "$HOME/.cache/bodyrig/scene-inspector-wsl.json"')
$stateText = (& $WslExe @stateArgs 2>$null | Out-String)
if ($LASTEXITCODE -ne 0 -or -not $stateText.Trim()) {
    throw "The WSL scene inspector is not set up. Run .\setup-scene-inspector-wsl.ps1 first."
}
$state = $stateText | ConvertFrom-Json

$command = if ($Bench) { "bench" } else { "inspect" }
$cli = @(
    "--cd", $repoWsl, "--exec", "env", "PYTHONPATH=$repoWsl", "PYTHONDONTWRITEBYTECODE=1",
    $state.host_python, "-m", "bodyrig.scene_inspector_cli", $command,
    "--root", $rootWsl, "--out", $outWsl, "--work-root", $state.work_root,
    "--bpy-python", $state.bpy_python, "--isolation", "bwrap",
    "--conditioning", $Conditioning, "--resolution", "$Resolution",
    "--timeout", "$TimeoutSeconds", "--memory-gb", "$MemoryGB"
)
if ($Bench) {
    $cli += @("--runs", "$Runs")
} else {
    $cli += @("--cache", $state.cache, "--jobs", "$Jobs", "--budget", $Budget)
    if ($MinimumOnly) { $cli += "--minimum-only" }
}
if ($All) { $cli += "--all" }
foreach ($item in $Asset) { $cli += @("--asset", ($item -replace '\\', '/')) }

$allArgs = $distroArgs + $cli
& $WslExe @allArgs
exit $LASTEXITCODE
