param(
    [Parameter(Mandatory = $true)][string]$ModelRoot,
    [switch]$AcceptInsightFaceResearchLicense,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$insightArchiveUrl = "https://github.com/deepinsight/insightface/releases/download/model-zoo/buffalo_l.zip"
$insightArchiveSha = "80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f"
$poseUrl = "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/rtmpose-l_simcc-ucoco_dw-ucoco_270e-384x288-2438fd99_20230728.pth"
$detectorUrl = "https://download.openmmlab.com/mmpose/v1/projects/rtmpose/rtmdet_m_8xb32-100e_coco-obj365-person-235e8209.pth"
$mmposeRevision = "759b39c13fea6ba094afc1fa932f51dc1b11cbf9"
$poseConfigUrl = "https://raw.githubusercontent.com/open-mmlab/mmpose/$mmposeRevision/configs/wholebody_2d_keypoint/rtmpose/ubody/rtmpose-l_8xb32-270e_coco-ubody-wholebody-384x288.py"
$runtimeConfigUrl = "https://raw.githubusercontent.com/open-mmlab/mmpose/$mmposeRevision/configs/_base_/default_runtime.py"
$detectorConfigUrl = "https://raw.githubusercontent.com/open-mmlab/mmpose/$mmposeRevision/demo/mmdetection_cfg/rtmdet_m_640-8xb32_coco-person.py"

if (-not $AcceptInsightFaceResearchLicense) {
    throw "buffalo_l model weights are research/non-commercial assets. Re-run with -AcceptInsightFaceResearchLicense only after you have reviewed and accept that model license."
}

$ModelRoot = [IO.Path]::GetFullPath($ModelRoot)
if (Test-Path -LiteralPath $ModelRoot) {
    if (-not $Force) { throw "Photoreal model root already exists: $ModelRoot" }
}
$targetParent = Split-Path -Parent $ModelRoot
if ([string]::IsNullOrWhiteSpace($targetParent)) { throw "Photoreal model root parent is invalid: $ModelRoot" }
New-Item -ItemType Directory -Path $targetParent -Force | Out-Null

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-photoreal-models-" + [Guid]::NewGuid().ToString("N"))
$stageRoot = Join-Path $tempRoot "model-root"
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

function Download-File {
    param([Parameter(Mandatory = $true)][string]$Url,[Parameter(Mandatory = $true)][string]$Path)
    Write-Host "Download: $Url"
    Invoke-WebRequest -Uri $Url -OutFile $Path -UseBasicParsing
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Download did not create file: $Path" }
    if ((Get-Item -LiteralPath $Path).Length -lt 1) { throw "Downloaded file is empty: $Path" }
}

function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

try {
    $archive = Join-Path $tempRoot "buffalo_l.zip"
    Download-File -Url $insightArchiveUrl -Path $archive
    $observedArchiveSha = Sha256 -Path $archive
    if ($observedArchiveSha -ne $insightArchiveSha) {
        throw "InsightFace buffalo_l archive SHA-256 mismatch: expected=$insightArchiveSha observed=$observedArchiveSha"
    }

    $extract = Join-Path $tempRoot "buffalo"
    Expand-Archive -LiteralPath $archive -DestinationPath $extract -Force
    $recognizer = Get-ChildItem -LiteralPath $extract -Filter "w600k_r50.onnx" -File -Recurse | Select-Object -First 1
    $detector = Get-ChildItem -LiteralPath $extract -Filter "det_10g.onnx" -File -Recurse | Select-Object -First 1
    if ($null -eq $recognizer -or $null -eq $detector) {
        throw "Verified buffalo_l archive does not contain expected detector/recognizer files."
    }
    if ($recognizer.Directory.FullName -ne $detector.Directory.FullName) {
        throw "Verified buffalo_l archive layout is inconsistent."
    }
    $buffaloSource = $recognizer.Directory.FullName
    $buffaloTarget = Join-Path $stageRoot "insightface\models\buffalo_l"
    New-Item -ItemType Directory -Path $buffaloTarget -Force | Out-Null
    Copy-Item -Path (Join-Path $buffaloSource "*") -Destination $buffaloTarget -Force -ErrorAction Stop

    $weightsDir = Join-Path $stageRoot "weights"
    $poseConfigDir = Join-Path $stageRoot "configs\wholebody_2d_keypoint\rtmpose\ubody"
    $baseConfigDir = Join-Path $stageRoot "configs\_base_"
    $detectorConfigDir = Join-Path $stageRoot "configs\mmdetection"
    foreach ($directory in @($weightsDir, $poseConfigDir, $baseConfigDir, $detectorConfigDir)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $poseWeights = Join-Path $weightsDir "rtmpose-l_simcc-ucoco_dw-ucoco_270e-384x288-2438fd99_20230728.pth"
    $detectorWeights = Join-Path $weightsDir "rtmdet_m_8xb32-100e_coco-obj365-person-235e8209.pth"
    $poseConfig = Join-Path $poseConfigDir "rtmpose-l_8xb32-270e_coco-ubody-wholebody-384x288.py"
    $runtimeConfig = Join-Path $baseConfigDir "default_runtime.py"
    $detectorConfig = Join-Path $detectorConfigDir "rtmdet_m_640-8xb32_coco-person.py"

    Download-File -Url $poseUrl -Path $poseWeights
    Download-File -Url $detectorUrl -Path $detectorWeights
    Download-File -Url $poseConfigUrl -Path $poseConfig
    Download-File -Url $runtimeConfigUrl -Path $runtimeConfig
    Download-File -Url $detectorConfigUrl -Path $detectorConfig

    $manifest = [ordered]@{
        format = "bodyrig-photoreal-reference-vision-models"
        version = 1
        insightface_root = "insightface"
        insightface_name = "buffalo_l"
        mmpose_pose_config = "configs/wholebody_2d_keypoint/rtmpose/ubody/rtmpose-l_8xb32-270e_coco-ubody-wholebody-384x288.py"
        mmpose_pose_weights = "weights/rtmpose-l_simcc-ucoco_dw-ucoco_270e-384x288-2438fd99_20230728.pth"
        mmdet_config = "configs/mmdetection/rtmdet_m_640-8xb32_coco-person.py"
        mmdet_weights = "weights/rtmdet_m_8xb32-100e_coco-obj365-person-235e8209.pth"
        identity_embedding_dimension = 512
    }
    $manifestPath = Join-Path $stageRoot "bodyrig-reference-vision-v1.json"
    $manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    $provenance = [ordered]@{
        format = "bodyrig-photoreal-reference-model-source-provenance"
        version = 1
        insightface_package = "buffalo_l"
        insightface_archive_url = $insightArchiveUrl
        insightface_archive_sha256 = $observedArchiveSha
        insightface_license_operator_accepted = $true
        mmpose_revision = $mmposeRevision
        pose_weights_url = $poseUrl
        pose_weights_sha256 = Sha256 -Path $poseWeights
        detector_weights_url = $detectorUrl
        detector_weights_sha256 = Sha256 -Path $detectorWeights
        pose_config_sha256 = Sha256 -Path $poseConfig
        runtime_config_sha256 = Sha256 -Path $runtimeConfig
        detector_config_sha256 = Sha256 -Path $detectorConfig
        build_only = $true
        production_activation = $false
    }
    $provenancePath = Join-Path $stageRoot "source-provenance.json"
    $provenance | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $provenancePath -Encoding UTF8

    $required = @(
        $manifestPath,
        $provenancePath,
        $poseWeights,
        $detectorWeights,
        (Join-Path $buffaloTarget "w600k_r50.onnx"),
        (Join-Path $buffaloTarget "det_10g.onnx")
    )
    foreach ($path in $required) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Staged model root is incomplete: $path" }
    }

    if (Test-Path -LiteralPath $ModelRoot) {
        if (-not $Force) { throw "Photoreal model root appeared during staging: $ModelRoot" }
        Remove-Item -LiteralPath $ModelRoot -Recurse -Force
    }
    Move-Item -LiteralPath $stageRoot -Destination $ModelRoot -ErrorAction Stop

    Write-Host ""
    Write-Host "BodyRig Photoreal reference model root: READY"
    Write-Host "Root:             $ModelRoot"
    Write-Host "InsightFace:      buffalo_l (verified archive SHA)"
    Write-Host "Whole-body pose:  DWPose/RTMPose-L 384x288"
    Write-Host "Person detector:  RTMDet-M"
    Write-Host "MMPose revision:  $mmposeRevision"
    Write-Host "Production:       FALSE"
} finally {
    if (Test-Path -LiteralPath $tempRoot -PathType Container) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
