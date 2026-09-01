param(
    [Parameter(Mandatory = $true)][string]$IntegrationCheckout,
    [string]$BodyRigPython = '',
    [string]$OutputDir = '',
    [string[]]$SearchRoot = @()
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw 'The historical fidelity baseline renderer is Windows-only.'
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7+ is required.' }

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Resolve-InputDirectory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

$integration = Resolve-InputDirectory -Path ([IO.Path]::GetFullPath($IntegrationCheckout)) -Label 'BodyRig integration checkout'
$expectedRevision = '64aa10bf5b1ad45a1e5ffdd63328b751b33359b9'
$targetSha = '8a8915658201eb8a391a3a2771b2e36bc4fe0e20d293259e015938d5aa6f1897'

$head = @(& git -C $integration rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $head.Count -ne 1 -or ([string]$head[0]).Trim().ToLowerInvariant() -ne $expectedRevision) {
    throw "Historical renderer checkout must be exact integration revision $expectedRevision"
}
$dirty = @(& git -C $integration status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw 'Historical renderer checkout must be exact-clean.' }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $integration '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { throw 'BodyRig Python not found in integration checkout; pass -BodyRigPython.' }
}
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label 'BodyRig Python'

if ($SearchRoot.Count -eq 0) {
    $roots = @()
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { $roots += (Join-Path $env:LOCALAPPDATA 'BodyRig') }
    if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) { $roots += (Join-Path $env:USERPROFILE 'Desktop') }
    $roots += 'C:\Users\Public\Documents\BodyRig'
} else {
    $roots = @($SearchRoot)
}
$roots = @($roots | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) -and (Test-Path -LiteralPath $_ -PathType Container) } | ForEach-Object { [IO.Path]::GetFullPath([string]$_) } | Select-Object -Unique)
if ($roots.Count -lt 1) { throw 'No existing search roots were available for the historical package.' }

$matches = @(
    foreach ($root in $roots) {
        Get-ChildItem -LiteralPath $root -Filter '*.mrbody' -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            $sha = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($sha -eq $targetSha) { $_.FullName }
        }
    }
) | Select-Object -Unique
if ($matches.Count -ne 1) {
    throw "Expected exactly one historical package with SHA $targetSha; found $($matches.Count): $($matches -join '; ')"
}
$package = Resolve-InputFile -Path ([string]$matches[0]) -Label 'Historical bad fidelity package'

$previousPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
try {
    $env:PYTHONPATH = $integration
    $moduleRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) { throw 'Could not prove integration BodyRig Python authority.' }
    $modulePath = [IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
    if (-not $modulePath.StartsWith($integration, [StringComparison]::OrdinalIgnoreCase)) {
        throw "BodyRig Python resolved from a different checkout: $modulePath"
    }

    $auditRaw = @(& $BodyRigPython -c "import hashlib,json,pathlib,sys; from bodyrig.package import validate_package; p=pathlib.Path(sys.argv[1]).resolve(); v=validate_package(p); print(json.dumps({'id':v.manifest['id'],'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'pipeline':v.provenance['pipeline']},separators=(',',':')))" $package)
    if ($LASTEXITCODE -ne 0 -or $auditRaw.Count -ne 1) { throw 'Historical package strict validation/audit failed.' }
    $audit = ([string]$auditRaw[0]) | ConvertFrom-Json
    if ([string]$audit.sha256 -ne $targetSha) { throw 'Historical package bytes drifted after selection.' }
    $fitStages = @($audit.pipeline | Where-Object { [string]$_.stage -eq 'avatar-fitting' })
    if ($fitStages.Count -ne 1) { throw "Historical package must contain exactly one avatar-fitting stage; found $($fitStages.Count)" }

    if ([string]::IsNullOrWhiteSpace($OutputDir)) {
        if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA unavailable; pass -OutputDir.' }
        $OutputDir = Join-Path $env:LOCALAPPDATA 'BodyRig\fidelity-baselines\integration-64aa-8a891565'
    }
    $out = [IO.Path]::GetFullPath($OutputDir)
    if (Test-Path -LiteralPath $out) { throw "Historical baseline output already exists: $out" }

    & (Join-Path $integration 'run-fidelity-windows-render-probe.ps1') -PackagePath $package -OutputDir $out
    if ($LASTEXITCODE -ne 0) { throw "Historical fidelity render failed with exit code $LASTEXITCODE" }
    $snapshots = Resolve-InputDirectory -Path (Join-Path $out 'snapshots') -Label 'Historical baseline snapshots'
    foreach ($name in @('front-full.png','three-quarter-full.png','side-full.png','face-front.png','fidelity-render-set.json')) {
        $null = Resolve-InputFile -Path (Join-Path $snapshots $name) -Label "Historical canonical snapshot $name"
    }

    Write-Host 'Historical physically-bad fidelity baseline: PASS'
    Write-Host "Package:      $package"
    Write-Host "Package SHA:  $targetSha"
    Write-Host "Body ID:      $([string]$audit.id)"
    Write-Host "Avatar fitter: $([string]$fitStages[0].adapter) @ $([string]$fitStages[0].revision)"
    Write-Host "Snapshots:    $snapshots"
} finally {
    if ($null -eq $previousPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $previousPythonPath }
}
