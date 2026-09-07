param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [IO.Path]::GetFullPath($AcceptanceDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Acceptance directory not found: $AcceptanceDir" }

$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python) { throw "python was not found on PATH; automatic release gate requires the BodyRig Python environment." }
$args = @("-m", "bodyrig.automatic_release_gate", "--acceptance-dir", $AcceptanceDir, "--repo-root", $repoRoot)
if (-not [string]::IsNullOrWhiteSpace($Output)) {
    $args += @("--output", [IO.Path]::GetFullPath($Output))
}
& $python.Source @args
if ($LASTEXITCODE -ne 0) { throw "BodyRig automatic production gate failed with exit code $LASTEXITCODE." }
exit 0
