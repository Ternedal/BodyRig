param(
    [string]$SessionReport = "",
    [string]$AcceptanceDir = "",
    [ValidatePattern('^$|^hfpreview-[0-9a-f]{32}$')][string]$PreviewJobId = "",
    [string]$CompositionAuthorityDir = "",
    [string]$LibraryRoot = "",
    [string]$Serial = "",
    [string]$PerformerId = "",
    [ValidatePattern('^$|^[a-z0-9æøå_-]{1,160}$')][string]$BodyId = "",
    [string]$PhotorealP0Root = "",
    [string]$PhotorealTeacherWorkRoot = "",
    [string]$PhotorealAppearanceReviewRoot = "",
    [string]$PhotorealAssetRoot = "",
    [string]$PhotorealReferenceModelRoot = "",
    [ValidateSet("", "female", "male", "neutral")][string]$PhotorealSmplxGender = "",
    [ValidateSet("", "colmap", "virtual")][string]$PhotorealCameraMode = "",
    [switch]$PhotorealSetupPublicCode,
    [switch]$PhotorealSetupRuntime,
    [string]$PhotorealP2MotionConfig = "",
    [string]$PhotorealP2ReviewSelectionInput = "",
    [string]$PhotorealSingleMotionDriverSourceRef = "",
    [string]$PhotorealReviewedBy = "",
    [string]$PhotorealReviewNotes = "",
    [string]$PhotorealP3TargetProfile = "",
    [string]$PhotorealP3MachineProbe = "",
    [string]$PhotorealWindowsPython = "",
    [string]$PhotorealBindingPersonLibrary = "",
    [string]$PhotorealBindingPersonId = "",
    [string]$PhotorealBindingAssemblyReceipt = "",
    [string]$PhotorealBindingBodyReleaseStatus = "",
    [string]$PhotorealPersonBindingOutput = "",
    [string]$PhotorealPersonBinding = "",
    [string]$PhotorealP3PhysicalReview = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-V1Version($Value) {
    if ($null -eq $Value -or $Value -is [bool] -or $Value -isnot [ValueType]) { return $false }
    try { return [decimal]$Value -eq [decimal]1 } catch { return $false }
}

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the BodyRig operator status router."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$physicalStatus = Join-Path $repoRoot "physical-acceptance-status.ps1"
$highFidelityStatus = Join-Path $repoRoot "high-fidelity-physical-status.ps1"
$digitalTwinStatus = Join-Path $repoRoot "digital-twin-status.ps1"
$firstPhysicalRun = Join-Path $repoRoot "prepare-first-physical-run.ps1"
$profiledFirstPhysicalRun = Join-Path $repoRoot "prepare-profiled-first-physical-run.ps1"
$storageAuthStatus = Join-Path $repoRoot "storage-auth-status.ps1"
$photorealStatus = Join-Path $repoRoot "photoreal-v2-status.ps1"
$photorealDigitalTwinStatus = Join-Path $repoRoot "photoreal-digital-twin-status.ps1"
foreach ($required in @($physicalStatus, $highFidelityStatus, $digitalTwinStatus, $firstPhysicalRun, $profiledFirstPhysicalRun, $storageAuthStatus, $photorealStatus, $photorealDigitalTwinStatus)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Canonical BodyRig operator dependency is missing: $required"
    }
}

$hasSession = -not [string]::IsNullOrWhiteSpace($SessionReport)
$hasAcceptance = -not [string]::IsNullOrWhiteSpace($AcceptanceDir)
$hasPreview = -not [string]::IsNullOrWhiteSpace($PreviewJobId)
$hasComposition = -not [string]::IsNullOrWhiteSpace($CompositionAuthorityDir)
$hasLibrary = -not [string]::IsNullOrWhiteSpace($LibraryRoot)
$hasSerial = -not [string]::IsNullOrWhiteSpace($Serial)
$hasPerformer = -not [string]::IsNullOrWhiteSpace($PerformerId)
$hasBodyId = -not [string]::IsNullOrWhiteSpace($BodyId)
$hasPhotorealP0 = -not [string]::IsNullOrWhiteSpace($PhotorealP0Root)
$hasPhotorealPersonBinding = -not [string]::IsNullOrWhiteSpace($PhotorealPersonBinding)
$hasPhotorealP3PhysicalReview = -not [string]::IsNullOrWhiteSpace($PhotorealP3PhysicalReview)
$hasPhotorealDigitalTwin = $hasPhotorealPersonBinding -or $hasPhotorealP3PhysicalReview
$hasPhotorealCompanion = (
    -not [string]::IsNullOrWhiteSpace($PhotorealTeacherWorkRoot) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealAppearanceReviewRoot) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealAssetRoot) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealReferenceModelRoot) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealSmplxGender) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealCameraMode) -or
    $PhotorealSetupPublicCode -or
    $PhotorealSetupRuntime -or
    -not [string]::IsNullOrWhiteSpace($PhotorealP2MotionConfig) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealP2ReviewSelectionInput) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealSingleMotionDriverSourceRef) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealReviewedBy) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealReviewNotes) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealP3TargetProfile) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealP3MachineProbe) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealWindowsPython) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealBindingPersonLibrary) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealBindingPersonId) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealBindingAssemblyReceipt) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealBindingBodyReleaseStatus) -or
    -not [string]::IsNullOrWhiteSpace($PhotorealPersonBindingOutput)
)

function Invoke-CanonicalStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Script,
        [Parameter(Mandatory = $true)][hashtable]$Parameters
    )
    & $Script @Parameters
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    exit $code
}

if ($hasPhotorealPersonBinding -xor $hasPhotorealP3PhysicalReview) {
    throw "Photoreal digital-twin mode requires -PhotorealPersonBinding and -PhotorealP3PhysicalReview together."
}
if ($hasPhotorealDigitalTwin -and ($hasPhotorealP0 -or $hasPhotorealCompanion)) {
    throw "Photoreal digital-twin mode cannot be combined with Photoreal P0-to-P3 status inputs."
}
if ($hasPhotorealCompanion -and -not $hasPhotorealP0) {
    throw "-PhotorealP0Root is required when any other Photoreal V2 option is supplied."
}
if ($hasPhotorealDigitalTwin) {
    if (-not $hasComposition -or -not $hasAcceptance) {
        throw "Photoreal digital-twin mode requires -CompositionAuthorityDir and -AcceptanceDir."
    }
    if ($hasSession -or $hasPreview -or $hasSerial -or $hasPerformer -or $hasBodyId) {
        throw "Photoreal digital-twin mode cannot be combined with session, high-fidelity preview, serial or physical preflight selectors."
    }

    $parameters = @{
        CompositionAuthorityDir = $CompositionAuthorityDir
        AcceptanceDir = $AcceptanceDir
        PhotorealPersonBinding = $PhotorealPersonBinding
        P3PhysicalReview = $PhotorealP3PhysicalReview
    }
    if ($hasLibrary) { $parameters.LibraryRoot = $LibraryRoot }
    Invoke-CanonicalStatus -Script $photorealDigitalTwinStatus -Parameters $parameters
}
if ($hasPhotorealP0) {
    if ($hasSession -or $hasAcceptance -or $hasPreview -or $hasComposition -or $hasLibrary -or $hasSerial -or $hasPerformer -or $hasBodyId) {
        throw "Photoreal V2 mode cannot be combined with physical, high-fidelity, digital-twin, library or serial selectors."
    }

    $parameters = @{ P0Root = $PhotorealP0Root }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealTeacherWorkRoot)) { $parameters.TeacherWorkRoot = $PhotorealTeacherWorkRoot }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealAppearanceReviewRoot)) { $parameters.AppearanceReviewRoot = $PhotorealAppearanceReviewRoot }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealAssetRoot)) { $parameters.AssetRoot = $PhotorealAssetRoot }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealReferenceModelRoot)) { $parameters.ReferenceModelRoot = $PhotorealReferenceModelRoot }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealSmplxGender)) { $parameters.SmplxGender = $PhotorealSmplxGender }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealCameraMode)) { $parameters.CameraMode = $PhotorealCameraMode }
    if ($PhotorealSetupPublicCode) { $parameters.SetupPublicCode = $true }
    if ($PhotorealSetupRuntime) { $parameters.SetupRuntime = $true }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealP2MotionConfig)) { $parameters.P2MotionConfig = $PhotorealP2MotionConfig }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealP2ReviewSelectionInput)) { $parameters.P2ReviewSelectionInput = $PhotorealP2ReviewSelectionInput }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealSingleMotionDriverSourceRef)) { $parameters.SingleMotionDriverSourceRef = $PhotorealSingleMotionDriverSourceRef }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealReviewedBy)) { $parameters.ReviewedBy = $PhotorealReviewedBy }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealReviewNotes)) { $parameters.ReviewNotes = $PhotorealReviewNotes }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealP3TargetProfile)) { $parameters.P3TargetProfile = $PhotorealP3TargetProfile }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealP3MachineProbe)) { $parameters.P3MachineProbe = $PhotorealP3MachineProbe }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealWindowsPython)) { $parameters.WindowsPython = $PhotorealWindowsPython }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealBindingPersonLibrary)) { $parameters.PersonLibrary = $PhotorealBindingPersonLibrary }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealBindingPersonId)) { $parameters.PersonId = $PhotorealBindingPersonId }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealBindingAssemblyReceipt)) { $parameters.AssemblyReceipt = $PhotorealBindingAssemblyReceipt }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealBindingBodyReleaseStatus)) { $parameters.BodyReleaseStatus = $PhotorealBindingBodyReleaseStatus }
    if (-not [string]::IsNullOrWhiteSpace($PhotorealPersonBindingOutput)) { $parameters.PhotorealPersonBindingOutput = $PhotorealPersonBindingOutput }
    Invoke-CanonicalStatus -Script $photorealStatus -Parameters $parameters
}

if ($hasPerformer -xor $hasBodyId) {
    throw "Physical preflight requires -PerformerId and -BodyId together, or neither."
}
if ($hasPerformer -and $hasBodyId) {
    if ($hasSession -or $hasAcceptance -or $hasPreview -or $hasComposition -or $hasLibrary -or $hasSerial) {
        throw "Physical preflight mode cannot be combined with session, acceptance, high-fidelity, composition, library or serial arguments."
    }
    if ($Json) {
        throw "Physical preflight performer mode does not support -Json because the canonical rig/source doctor has human-readable output."
    }

    $storageRaw = @(& $storageAuthStatus -PerformerId $PerformerId -Json 2>&1)
    $storageCode = $LASTEXITCODE
    if ($null -eq $storageCode) { $storageCode = 0 }
    if ($storageCode -ne 0 -or $storageRaw.Count -ne 1) {
        throw "Could not establish canonical persistent storage-auth status before physical preflight."
    }
    try { $storage = ([string]$storageRaw[0]) | ConvertFrom-Json -Depth 8 }
    catch { throw "Persistent storage-auth status returned unreadable JSON." }
    if ([string]$storage.format -ne "bodyrig-storage-auth-status" -or -not (Test-V1Version $storage.version)) {
        throw "Persistent storage-auth status returned an unexpected contract."
    }
    if ($storage.qualified -ne $true -or [string]$storage.state -ne "qualified") {
        Write-Host "BodyRig physical preflight: BLOCKED | persistent storage authentication is not reboot-qualified"
        Write-Host "Storage state: $([string]$storage.state) | cold-boots=$([int]$storage.cold_boots_passed)/$([int]$storage.cold_boots_required)"
        Write-Host ([string]$storage.message)
        if ($null -ne $storage.next_command -and -not [string]::IsNullOrWhiteSpace([string]$storage.next_command)) {
            Write-Host "Next command:"
            Write-Host ([string]$storage.next_command)
        }
        exit 3
    }
    Write-Host "BodyRig persistent storage authentication: QUALIFIED | cold-boots=$([int]$storage.cold_boots_passed)/$([int]$storage.cold_boots_required)"

    $parameters = @{
        PerformerId = $PerformerId
        BodyId = $BodyId
    }
    Invoke-CanonicalStatus -Script $profiledFirstPhysicalRun -Parameters $parameters
}

if ($hasComposition) {
    if (-not $hasAcceptance) {
        throw "-CompositionAuthorityDir requires -AcceptanceDir for the M4 -> M5 -> M6 digital-twin status chain."
    }
    if ($hasSession -or $hasPreview -or $hasSerial) {
        throw "Digital-twin mode cannot be combined with -SessionReport, -PreviewJobId or -Serial."
    }
    $parameters = @{
        CompositionAuthorityDir = $CompositionAuthorityDir
        AcceptanceDir = $AcceptanceDir
    }
    if ($hasLibrary) { $parameters.LibraryRoot = $LibraryRoot }
    if ($Json) { $parameters.Json = $true }
    Invoke-CanonicalStatus -Script $digitalTwinStatus -Parameters $parameters
}

if ($hasPreview) {
    if ($hasSession -or $hasAcceptance -or $hasComposition -or $hasLibrary) {
        throw "High-fidelity preview mode cannot be combined with session, acceptance, composition or library arguments."
    }
    $parameters = @{ PreviewJobId = $PreviewJobId }
    if ($hasSerial) { $parameters.Serial = $Serial }
    if ($Json) { $parameters.Json = $true }
    Invoke-CanonicalStatus -Script $highFidelityStatus -Parameters $parameters
}

if ($hasSession) {
    if ($hasAcceptance -or $hasComposition -or $hasPreview -or $hasLibrary -or $hasSerial) {
        throw "Physical session mode accepts only -SessionReport (plus -Json)."
    }
    $parameters = @{ SessionReport = $SessionReport }
    if ($Json) { $parameters.Json = $true }
    Invoke-CanonicalStatus -Script $physicalStatus -Parameters $parameters
}

if ($hasAcceptance) {
    if ($hasComposition -or $hasPreview -or $hasLibrary -or $hasSerial) {
        throw "Physical acceptance mode accepts only -AcceptanceDir (plus -Json)."
    }
    $parameters = @{ AcceptanceDir = $AcceptanceDir }
    if ($Json) { $parameters.Json = $true }
    Invoke-CanonicalStatus -Script $physicalStatus -Parameters $parameters
}

if ($hasLibrary -or $hasSerial) {
    throw "-LibraryRoot and -Serial are stage-specific and require digital-twin or high-fidelity mode respectively."
}

$headLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1 -or ([string]$headLines[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not resolve the current BodyRig Git checkout revision."
}
$head = ([string]$headLines[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "Could not verify BodyRig checkout cleanliness."
}
$clean = $dirty.Count -eq 0
$nextCommand = if ($clean) { "& '" + $firstPhysicalRun.Replace("'", "''") + "'" } else { $null }
$message = if ($clean) {
    "No physical evidence selector was supplied. Start with the canonical read-only rig/source doctor before creating a physical session."
} else {
    "BodyRig checkout is dirty. Clean the checkout before starting the canonical physical preflight."
}
$result = [ordered]@{
    format = "bodyrig-operator-status-router"
    version = 1
    read_only = $true
    state = $(if ($clean) { "required" } else { "blocked" })
    stage = "physical-preflight"
    bodyrig_revision = $head
    checkout_clean = $clean
    next_gate = "physical-preflight"
    next_command = $nextCommand
    message = $message
}

if ($Json) {
    $result | ConvertTo-Json -Depth 4 -Compress
} else {
    Write-Host "BodyRig operator status: $($result.state.ToUpperInvariant())"
    Write-Host "Stage:    $($result.stage)"
    Write-Host "Revision: $($result.bodyrig_revision) | clean=$($result.checkout_clean)"
    Write-Host $result.message
    if ($null -ne $result.next_command) {
        Write-Host "Next command:"
        Write-Host $result.next_command
    }
}

exit $(if ($clean) { 0 } else { 3 })
