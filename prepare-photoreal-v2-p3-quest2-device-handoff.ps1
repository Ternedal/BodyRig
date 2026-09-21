param(
    [Parameter(Mandatory = $true)][string]$RuntimeReviewWorkspace,
    [Parameter(Mandatory = $true)][string]$StudentOutputRoot,
    [string]$DeviceSessionRoot = "",
    [string]$AdbExe = "",
    [string]$Serial = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Quest2 P3 device handoff is Windows-orchestrated."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for Quest2 P3 device handoff."
}

function Need-Directory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Sha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') {
        throw "$Label is not a canonical SHA-256."
    }
    return $normalized
}

function Need-RelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $clean = $Value.Trim().Replace("\", "/")
    if (
        [string]::IsNullOrWhiteSpace($clean) -or
        $clean.StartsWith("/") -or
        $clean.StartsWith("../") -or
        ("/$clean/").Contains("/../") -or
        ($clean.Split("/", 2)[0]).Contains(":")
    ) {
        throw "$Label escapes its root."
    }
    return $clean
}

function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Invoke-Adb {
    param(
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [switch]$Capture
    )
    $all = @()
    if (-not [string]::IsNullOrWhiteSpace($script:Serial)) {
        $all += @("-s", $script:Serial)
    }
    $all += $Arguments

    if ($Capture) {
        $lines = @(& $script:AdbExe @all 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "adb failed: $($lines -join [Environment]::NewLine)"
        }
        return $lines
    }

    & $script:AdbExe @all
    if ($LASTEXITCODE -ne 0) {
        throw "adb failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Quest2 P3 device handoff requires an exact clean BodyRig checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not resolve BodyRig HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') {
    throw "BodyRig HEAD is invalid."
}

$RuntimeReviewWorkspace = Need-Directory -Path $RuntimeReviewWorkspace -Label "Quest2 runtime review workspace"
$StudentOutputRoot = Need-Directory -Path $StudentOutputRoot -Label "Final P3 student output root"
$planPath = Need-File -Path (Join-Path $RuntimeReviewWorkspace "p3-device-runtime-review-plan.json") -Label "Quest2 runtime review plan"
$plan = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

if (
    [string]$plan.format -ne "bodyrig-photoreal-p3-device-runtime-review-plan" -or
    $plan.version -is [bool] -or
    [double]$plan.version -ne 1.0
) {
    throw "Quest2 runtime review plan format/version mismatch."
}
if (
    [string]$plan.target_device_family -ne "meta-quest" -or
    [string]$plan.target_device_model -ne "quest-2"
) {
    throw "Quest2 P3 device handoff requires an exact quest-2 target plan."
}
foreach ($field in @(
    "student_artifact_bytes_reverified",
    "physical_device_installation_required",
    "physical_device_evidence_required",
    "human_runtime_visual_acceptance_required",
    "runtime_review_ready"
)) {
    if ($plan.$field -isnot [bool] -or $plan.$field -ne $true) {
        throw "Quest2 runtime review plan requirement missing: $field"
    }
}
foreach ($field in @(
    "physical_device_evidence_present",
    "runtime_acceptance_authority",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($plan.$field -isnot [bool] -or $plan.$field -ne $false) {
        throw "Quest2 runtime review plan crossed authority boundary: $field"
    }
}

$planSha = Need-Sha256 -Value ([string]$plan.p3_device_runtime_review_plan_sha256) -Label "runtime review plan SHA-256"
$artifacts = @($plan.student_artifacts)
if ($artifacts.Count -lt 1 -or [int]$plan.student_artifact_count -ne $artifacts.Count) {
    throw "Quest2 runtime review plan has an invalid student artifact universe."
}

$expectedPaths = @{}
$normalizedArtifacts = @()
foreach ($artifact in $artifacts) {
    $relative = Need-RelativePath -Value ([string]$artifact.relative_path) -Label "student artifact path"
    if ($expectedPaths.ContainsKey($relative)) {
        throw "Quest2 runtime review plan repeats student artifact: $relative"
    }
    $expectedSha = Need-Sha256 -Value ([string]$artifact.sha256) -Label "student artifact SHA-256"
    $size = $artifact.size_bytes
    if ($size -is [bool] -or $size -isnot [ValueType] -or [int64]$size -lt 1) {
        throw "Quest2 runtime review plan has invalid artifact size: $relative"
    }

    $windowsRelative = $relative.Replace("/", [IO.Path]::DirectorySeparatorChar)
    $localPath = Need-File -Path (Join-Path $StudentOutputRoot $windowsRelative) -Label "student artifact"
    $observedSize = (Get-Item -LiteralPath $localPath).Length
    if ($observedSize -ne [int64]$size) {
        throw "Quest2 student artifact size drifted: $relative"
    }
    $observedSha = Sha256 $localPath
    if ($observedSha -ne $expectedSha) {
        throw "Quest2 student artifact bytes drifted: $relative"
    }

    $expectedPaths[$relative] = $true
    $normalizedArtifacts += [ordered]@{
        kind = [string]$artifact.kind
        relative_path = $relative
        size_bytes = [int64]$size
        sha256 = $observedSha
        local_path = $localPath
    }
}

$actualPaths = @(
    Get-ChildItem -LiteralPath $StudentOutputRoot -Recurse -File |
        ForEach-Object {
            [IO.Path]::GetRelativePath($StudentOutputRoot, $_.FullName).Replace("\", "/")
        } |
        Where-Object { $_ -ne "distillation-manifest.json" } |
        Sort-Object
)
$expectedSorted = @($expectedPaths.Keys | Sort-Object)
if (($actualPaths -join "`n") -ne ($expectedSorted -join "`n")) {
    throw "Quest2 student output artifact universe drifted before physical handoff."
}

$contractPath = Need-File -Path (Join-Path $repoRoot "reference-renderer\renderer-contract.json") -Label "Reference renderer contract"
$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$contractVersion = $contract.version
if (
    [string]$contract.format -ne "bodyrig-reference-renderer-contract" -or
    $null -eq $contractVersion -or
    $contractVersion -is [bool] -or
    $contractVersion -isnot [ValueType] -or
    [decimal]$contractVersion -ne [decimal]1
) {
    throw "Reference renderer contract format/version mismatch."
}
$unityVersion = [string]$contract.unity_editor_version
if ($unityVersion -notmatch '^6000\.3\.\d+f\d+$') {
    throw "Reference renderer Unity version is invalid."
}
$pinnedAdb = Join-Path "C:\Program Files\Unity\Hub\Editor\$unityVersion\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools" "adb.exe"
$pinnedAdb = Need-File -Path $pinnedAdb -Label "Pinned Unity Android adb"
if (-not [string]::IsNullOrWhiteSpace($AdbExe)) {
    $requestedAdb = Need-File -Path $AdbExe -Label "Requested adb"
    if (-not [string]::Equals($requestedAdb, $pinnedAdb, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Quest2 P3 device handoff refuses non-pinned adb: $requestedAdb"
    }
}
$script:AdbExe = $pinnedAdb
$script:Serial = $Serial

if ([string]::IsNullOrWhiteSpace($script:Serial)) {
    $devices = @(
        Invoke-Adb -Arguments @("devices") -Capture |
            Select-Object -Skip 1 |
            Where-Object { $_ -match '^\S+\s+device$' }
    )
    if ($devices.Count -ne 1) {
        throw "Expected exactly one online adb device; found $($devices.Count). Pass -Serial when multiple devices are attached."
    }
    $script:Serial = ($devices[0] -split '\s+')[0]
}

$model = ((Invoke-Adb -Arguments @("shell", "getprop", "ro.product.model") -Capture) -join "").Trim()
if ($model -notmatch '(?i)(Quest\s*2|Oculus\s*Quest\s*2)') {
    throw "Connected device does not identify itself explicitly as Quest 2: '$model'"
}

if ([string]::IsNullOrWhiteSpace($DeviceSessionRoot)) {
    $DeviceSessionRoot = Join-Path $RuntimeReviewWorkspace "p3-quest2-device-handoff"
} else {
    $DeviceSessionRoot = [IO.Path]::GetFullPath($DeviceSessionRoot)
}
if (Test-Path -LiteralPath $DeviceSessionRoot) {
    throw "Quest2 P3 device handoff session already exists: $DeviceSessionRoot"
}
New-Item -ItemType Directory -Path $DeviceSessionRoot | Out-Null
$DeviceSessionRoot = Need-Directory -Path $DeviceSessionRoot -Label "Quest2 P3 device handoff session"
$roundtripRoot = Join-Path $DeviceSessionRoot "roundtrip"
New-Item -ItemType Directory -Path $roundtripRoot | Out-Null

$remoteRoot = "/sdcard/Download/BodyRig/P3/$($planSha.Substring(0,16))-$([Guid]::NewGuid().ToString('N'))"
$existing = ((Invoke-Adb -Arguments @("shell", "sh", "-c", "if [ -e '$remoteRoot' ]; then echo exists; fi") -Capture) -join "").Trim()
if ($existing -eq "exists") {
    throw "Quest2 remote handoff root unexpectedly already exists: $remoteRoot"
}
Invoke-Adb -Arguments @("shell", "mkdir", "-p", "$remoteRoot/student")

$stagedArtifacts = @()
foreach ($artifact in $normalizedArtifacts) {
    $relative = [string]$artifact.relative_path
    $remotePath = "$remoteRoot/student/$relative"
    $lastSlash = $remotePath.LastIndexOf("/")
    if ($lastSlash -lt 1) {
        throw "Quest2 remote artifact path is invalid: $remotePath"
    }
    $remoteParent = $remotePath.Substring(0, $lastSlash)
    Invoke-Adb -Arguments @("shell", "mkdir", "-p", $remoteParent)
    Invoke-Adb -Arguments @("push", [string]$artifact.local_path, $remotePath)

    $roundtripPath = Join-Path $roundtripRoot $relative.Replace("/", [IO.Path]::DirectorySeparatorChar)
    $roundtripParent = Split-Path -Parent $roundtripPath
    if (-not (Test-Path -LiteralPath $roundtripParent -PathType Container)) {
        New-Item -ItemType Directory -Path $roundtripParent -Force | Out-Null
    }
    Invoke-Adb -Arguments @("pull", $remotePath, $roundtripPath)
    $roundtripPath = Need-File -Path $roundtripPath -Label "Quest2 roundtrip artifact"
    $roundtripSha = Sha256 $roundtripPath
    if ($roundtripSha -ne [string]$artifact.sha256) {
        throw "Quest2 staged artifact failed byte-for-byte roundtrip verification: $relative"
    }

    $stagedArtifacts += [ordered]@{
        relative_path = $relative
        sha256 = [string]$artifact.sha256
        remote_path = $remotePath
        roundtrip_sha256 = $roundtripSha
    }
}

$receiptPath = Join-Path $DeviceSessionRoot "p3-quest2-device-handoff.json"
$receipt = [ordered]@{
    format = "bodyrig-photoreal-p3-quest2-device-handoff"
    version = 1
    bodyrig_revision = $head
    p3_device_runtime_review_plan_sha256 = $planSha
    target_device_family = [string]$plan.target_device_family
    target_device_model = [string]$plan.target_device_model
    observed_device_model = $model
    adb_authority = $pinnedAdb
    remote_stage_root = $remoteRoot
    student_artifacts = $stagedArtifacts
    local_student_bytes_reverified = $true
    physical_quest2_observed = $true
    student_bytes_staged_to_device = $true
    staged_student_hashes_roundtrip_verified = $true
    runtime_loaded = $false
    installed_student_hashes_verified_on_device = $false
    stereo_rendering_observed = $false
    vr_safe_frame_pacing_observed = $false
    human_runtime_visual_acceptance_complete = $false
    runtime_acceptance_authority = $false
    photoreal_acceptance_authority = $false
    production_activation = $false
}
$receipt | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $receiptPath -Encoding UTF8

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 P3 DEVICE HANDOFF"
Write-Host "Revision:                    $head"
Write-Host "Runtime review plan:         $planPath"
Write-Host "Plan SHA:                    $planSha"
Write-Host "Quest device:                $model"
Write-Host "ADB authority:               $pinnedAdb"
Write-Host "Remote stage root:           $remoteRoot"
Write-Host "Artifacts staged:            $($stagedArtifacts.Count)"
Write-Host "Roundtrip byte verification: PASS"
Write-Host "Runtime loaded:              FALSE"
Write-Host "Installed hashes verified:   FALSE"
Write-Host "Physical PASS/FAIL:          NOT RUN"
Write-Host "Production:                  FALSE"
Write-Host "============================================================"
Write-Host ""
Write-Host "Quest2 P3 device handoff: COMPLETE"
Write-Host "Receipt: $receiptPath"
Write-Host ""
Write-Host "Important: staged bytes are NOT runtime installation evidence."
Write-Host "The next gate must load these exact bytes through the Quest renderer,"
Write-Host "measure runtime performance, and collect explicit human visual PASS/FAIL."
exit 0
