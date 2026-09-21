param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [string]$P2Root = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Get-ConfigArg {
    param(
        [Parameter(Mandatory = $true)][object[]]$Command,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $matches = @()
    for ($i = 0; $i -lt $Command.Count; $i++) {
        if ([string]$Command[$i] -eq $Name) { $matches += $i }
    }
    if ($matches.Count -ne 1) { throw "Teacher config must contain exactly one $Name." }
    $index = [int]$matches[0]
    if ($index + 1 -ge $Command.Count) { throw "Teacher config $Name has no value." }
    $value = ([string]$Command[$index + 1]).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) { throw "Teacher config $Name is empty." }
    return $value
}

function Convert-ToWslPath {
    param(
        [Parameter(Mandatory = $true)][string]$WslExe,
        [Parameter(Mandatory = $true)][string]$Distribution,
        [Parameter(Mandatory = $true)][string]$WindowsPath
    )
    $raw = @(& $WslExe -d $Distribution -- /usr/bin/wslpath -a -u $WindowsPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$raw[0])) {
        throw "Could not translate Windows path into WSL: $WindowsPath"
    }
    return ([string]$raw[0]).Trim()
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branch = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $branch.Count -ne 1 -or ([string]$branch[0]).Trim() -ne "main") {
    throw "P2 ExAvatar animation identity export requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 ExAvatar animation identity export requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$teacherConfigPath = Need-File -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-config.json") -Label "ExAvatar teacher config"
$teacherOutputRoot = Need-Directory -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-output\output") -Label "ExAvatar teacher output root"

if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"
$animationPlan = Need-File -Path (Join-Path $P2Root "p2-animation-plan.json") -Label "P2 animation plan"

$config = Get-Content -LiteralPath $teacherConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if (
    [string]$config.format -ne "bodyrig-photoreal-teacher-config" -or
    $config.version -is [bool] -or
    [double]$config.version -ne 1.0
) {
    throw "ExAvatar teacher config format/version mismatch."
}
if ([string]$config.adapter -ne "exavatar-benchmark") {
    throw "ExAvatar teacher config adapter mismatch."
}
if ([string]$config.upstream_repository -ne "https://github.com/mks0601/ExAvatar_RELEASE") {
    throw "ExAvatar teacher config upstream repository mismatch."
}
if ([string]$config.upstream_commit -ne "d45268730c779fae4118f1a361cf9ff639bc4d1e") {
    throw "ExAvatar teacher config upstream commit mismatch."
}
$command = @($config.command)
if ($command.Count -lt 1) { throw "ExAvatar teacher config command is empty." }

$distribution = Get-ConfigArg -Command $command -Name "--distribution"
$wslExe = Get-ConfigArg -Command $command -Name "--wsl-exe"
$linuxPython = Get-ConfigArg -Command $command -Name "--linux-python"
$linuxWorkspace = Get-ConfigArg -Command $command -Name "--workspace-root"
if (-not $linuxWorkspace.StartsWith("/") -or $linuxWorkspace -eq "/") {
    throw "Teacher config workspace root is not an absolute non-root Linux path."
}
if (-not $linuxPython.StartsWith("/")) {
    throw "Teacher config Linux Python is not absolute."
}

$identityRoot = Join-Path $P2Root "animation-input\exavatar-identity"
if (Test-Path -LiteralPath $identityRoot) {
    throw "P2 ExAvatar animation identity output already exists: $identityRoot"
}
$identityParent = Split-Path -Parent $identityRoot
New-Item -ItemType Directory -Path $identityParent -Force | Out-Null

$linuxRepo = Convert-ToWslPath -WslExe $wslExe -Distribution $distribution -WindowsPath $repoRoot
$linuxPlan = Convert-ToWslPath -WslExe $wslExe -Distribution $distribution -WindowsPath $animationPlan
$linuxTeacherOutput = Convert-ToWslPath -WslExe $wslExe -Distribution $distribution -WindowsPath $teacherOutputRoot
$linuxIdentityRoot = Convert-ToWslPath -WslExe $wslExe -Distribution $distribution -WindowsPath $identityRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - EXAVATAR ANIMATION IDENTITY INPUT"
Write-Host "Teacher config:       $teacherConfigPath"
Write-Host "P2 animation plan:    $animationPlan"
Write-Host "Linux workspace:      $linuxWorkspace"
Write-Host "Identity output:      $identityRoot"
Write-Host "Source media rehash:  NO"
Write-Host "Fitting/training:     NOT RUN"
Write-Host "Animation execution:  FALSE"
Write-Host "Production:           FALSE"
Write-Host "============================================================"
Write-Host ""

$argsList = @(
    "-d", $distribution, "--",
    "/usr/bin/env",
    "PYTHONPATH=$linuxRepo",
    "PYTHONNOUSERSITE=1",
    $linuxPython,
    "-m", "bodyrig.photoreal_p2_exavatar_animation_identity",
    "--animation-plan", $linuxPlan,
    "--exavatar-workspace-root", $linuxWorkspace,
    "--teacher-output-root", $linuxTeacherOutput,
    "--out", $linuxIdentityRoot
)
$output = @(& $wslExe @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P2 ExAvatar animation identity export failed with code $code."
}

$receiptPath = Need-File -Path (Join-Path $identityRoot "p2-exavatar-animation-identity.json") -Label "P2 ExAvatar animation identity receipt"
$receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if ($receipt.identity_artifact_count -ne 4) {
    throw "P2 ExAvatar animation identity receipt does not contain exactly four identity artifacts."
}
foreach ($field in @(
    "teacher_checkpoint_bytes_reverified",
    "identity_bytes_reverified_against_preprocess_state",
    "p2_animation_identity_input_ready"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $true) {
        throw "P2 ExAvatar animation identity authority missing: $field"
    }
}
foreach ($field in @(
    "source_media_rehash_performed",
    "p2_animation_execution_authorized",
    "p2_animated_teacher_acceptance_authority",
    "quest_distillation_authorized",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $false) {
        throw "P2 ExAvatar animation identity crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "P2 ExAvatar animation identity: READY"
Write-Host "Identity artifacts:   $($receipt.identity_artifact_count)"
Write-Host "Checkpoint reverify:  TRUE"
Write-Host "Preprocess binding:   TRUE"
Write-Host "Source media rehash:  NO"
Write-Host "Fitting/training:     NOT RUN"
Write-Host "Animation execution:  FALSE"
Write-Host "Production:           FALSE"
Write-Host "Receipt: $receiptPath"
exit 0
