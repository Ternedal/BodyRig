param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("health", "search", "probe")]
    [string]$Command,

    [Parameter(Position = 1)]
    [string]$Term = "",

    [ValidateRange(1, 100)]
    [int]$Limit = 25,

    [string]$PerformerId = "",

    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { $BodyRigPython = $venv }
    else { $BodyRigPython = Resolve-CommandPath "python" }
}
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    throw "BodyRig Python not found. Create the repo venv or pass -BodyRigPython explicitly."
}
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"
$expectedBodyRigModule = Resolve-InputFile -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "BodyRig checkout module"

Push-Location $repoRoot
try {
    $authorityRaw = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())")
    if ($LASTEXITCODE -ne 0 -or $authorityRaw.Count -ne 1) {
        throw "BodyRig Python could not prove a single checkout-bound bodyrig import."
    }
    $actualBodyRigModule = Resolve-InputFile -Path ([string]$authorityRaw[0]).Trim() -Label "Imported BodyRig module"
    if (-not [string]::Equals($actualBodyRigModule, $expectedBodyRigModule, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "BodyRig Python imports bodyrig from unexpected location: $actualBodyRigModule. Expected checkout authority: $expectedBodyRigModule"
    }

    $stashArgs = @($Command)
    if ($Command -eq "search") {
        if ([string]::IsNullOrWhiteSpace($Term)) {
            throw "Search requires a performer name as the second argument."
        }
        $stashArgs += @($Term, "--limit", [string]$Limit)
    }
    elseif ($Command -eq "probe") {
        if ([string]::IsNullOrWhiteSpace($PerformerId)) {
            throw "Probe requires -PerformerId."
        }
        $stashArgs += @("--performer-id", $PerformerId)
    }

    & $BodyRigPython -m bodyrig.stash_cli @stashArgs
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "BodyRig Stash discovery failed with exit code $exitCode."
    }
}
finally {
    Pop-Location
}

exit 0
