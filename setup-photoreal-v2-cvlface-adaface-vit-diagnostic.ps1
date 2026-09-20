param(
    [string]$DiagnosticRoot = "",
    [switch]$AcceptTrainingDatasetTerms,
    [switch]$Force,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoId = "minchul/cvlface_adaface_vit_base_webface4m"
$repoRevision = "b95848ffb6cfbcdba67a4e24adf3c0b91518d7e3"
$modelRelative = "model\model.safetensors"
$modelSha = "5fafd6b7d599a3ede5fac5bd1d01ad05e9e93e89b39b7687d4a3bc93ff2aebc0"

if (-not $AcceptTrainingDatasetTerms) {
    throw "CVLFace model card requires users to follow the training-dataset license. Re-run with -AcceptTrainingDatasetTerms only after reviewing that restriction. This asset remains diagnostic-only."
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is required on Windows."
}
if ([string]::IsNullOrWhiteSpace($DiagnosticRoot)) {
    $DiagnosticRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\diagnostic-recognizers\cvlface-adaface-vit-base-webface4m"
}
$DiagnosticRoot = [IO.Path]::GetFullPath($DiagnosticRoot)

function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$windowsPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $windowsPython -PathType Leaf)) {
    throw "BodyRig Windows Python not found: $windowsPython"
}

function Convert-ToWslPath {
    param([string]$WindowsPath)
    if ($WindowsPath.StartsWith('/')) { return $WindowsPath }
    $pythonCode = @'
import base64
import sys
sys.path.insert(0, sys.argv[1])
from bodyrig.wsl_adapter_bridge import make_wsl_path_converter
value = make_wsl_path_converter(sys.argv[2], sys.argv[3])(sys.argv[4])
print(base64.b64encode(value.encode("utf-8")).decode("ascii"))
'@
    $lines = @(& $windowsPython -c $pythonCode $repoRoot "wsl.exe" $Distribution $WindowsPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) {
        throw "Could not convert path with BodyRig WSL bridge: $WindowsPath | $($lines -join ' ')"
    }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(([string]$lines[0]).Trim()))
}

if (Test-Path -LiteralPath $DiagnosticRoot -PathType Container) {
    $model = Join-Path $DiagnosticRoot $modelRelative
    $provenance = Join-Path $DiagnosticRoot "source-provenance.json"
    if (-not $Force -and
        (Test-Path -LiteralPath $model -PathType Leaf) -and
        (Test-Path -LiteralPath $provenance -PathType Leaf) -and
        ((Sha256 $model) -eq $modelSha)) {
        $existing = Get-Content -LiteralPath $provenance -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
        if (
            $existing.format -eq "bodyrig-photoreal-cvlface-diagnostic-provenance" -and
            $existing.repo_id -eq $repoId -and
            $existing.repo_revision -eq $repoRevision -and
            $existing.model_sha256 -eq $modelSha -and
            $existing.diagnostic_only -eq $true -and
            $existing.production_activation -eq $false
        ) {
            Write-Host "BodyRig CVLFace diagnostic asset: READY"
            Write-Host "Root:       $DiagnosticRoot"
            Write-Host "Model:      AdaFace ViT-Base@WebFace4M"
            Write-Host "Production: FALSE"
            exit 0
        }
    }
    if (-not $Force) {
        throw "CVLFace diagnostic root already exists but is not the exact pinned asset: $DiagnosticRoot. Use -Force only after reviewing the directory."
    }
}

$parent = Split-Path -Parent $DiagnosticRoot
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$tempRoot = Join-Path $parent ("cvlface-stage-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
$wslTempRoot = Convert-ToWslPath $tempRoot
$wslDependencyRoot = "$wslTempRoot/python"
$wslModelRoot = "$wslTempRoot/model"

try {
    Write-Host "Installing isolated CVLFace diagnostic dependencies..."
    $pipArgs = @(
        "-d", $Distribution, "--",
        $LinuxPython, "-m", "pip", "install",
        "--disable-pip-version-check", "--no-input",
        "--target", $wslDependencyRoot,
        "transformers==4.33.0",
        "huggingface-hub==0.17.3",
        "omegaconf==2.3.0",
        "timm==0.9.12",
        "safetensors==0.3.3",
        "PyYAML==6.0.1"
    )
    & wsl.exe @pipArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CVLFace isolated dependency installation failed with exit code $LASTEXITCODE."
    }

    $downloadScript = @'
import sys
from huggingface_hub import snapshot_download
target, repo_id, revision = sys.argv[1:4]
snapshot_download(
    repo_id=repo_id,
    revision=revision,
    local_dir=target,
    local_dir_use_symlinks=False,
)
'@
    $downloadScriptPath = Join-Path $tempRoot "download-cvlface.py"
    $downloadScript | Set-Content -LiteralPath $downloadScriptPath -Encoding UTF8
    $wslDownloadScript = Convert-ToWslPath $downloadScriptPath

    Write-Host "Downloading pinned CVLFace model snapshot..."
    $downloadArgs = @(
        "-d", $Distribution, "--", "env",
        "PYTHONPATH=$wslDependencyRoot",
        $LinuxPython, $wslDownloadScript,
        $wslModelRoot, $repoId, $repoRevision
    )
    & wsl.exe @downloadArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Pinned CVLFace snapshot download failed with exit code $LASTEXITCODE."
    }

    $model = Join-Path $tempRoot $modelRelative
    if (-not (Test-Path -LiteralPath $model -PathType Leaf)) {
        throw "CVLFace model.safetensors was not downloaded: $model"
    }
    $observedSha = Sha256 $model
    if ($observedSha -ne $modelSha) {
        throw "CVLFace model SHA-256 mismatch: expected=$modelSha observed=$observedSha"
    }

    $required = @(
        (Join-Path $tempRoot "model\config.json"),
        (Join-Path $tempRoot "model\wrapper.py"),
        (Join-Path $tempRoot "model\pretrained_model\model.pt"),
        (Join-Path $tempRoot "model\pretrained_model\model.yaml")
    )
    foreach ($item in $required) {
        if (-not (Test-Path -LiteralPath $item -PathType Leaf)) {
            throw "Pinned CVLFace snapshot is incomplete: $item"
        }
    }

    $provenance = [ordered]@{
        format = "bodyrig-photoreal-cvlface-diagnostic-provenance"
        version = 1
        repo_id = $repoId
        repo_revision = $repoRevision
        model_file = "model/model.safetensors"
        model_sha256 = $observedSha
        architecture = "ViT-Base"
        training_loss = "AdaFace"
        training_dataset = "WebFace4M"
        embedding_dimension = 512
        input_size = 112
        color_space = "RGB"
        normalization = "ToTensor; mean=0.5,std=0.5 per RGB channel"
        software_license = "MIT"
        training_dataset_license_requires_operator_review = $true
        unsafe_pickle_dependency_present = $true
        license_operator_accepted = $true
        diagnostic_only = $true
        identity_matching_authorized = $false
        teacher_training_authorized = $false
        photoreal_acceptance_authority = $false
        production_activation = $false
    }
    $provenance | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $tempRoot "source-provenance.json") -Encoding UTF8

    Remove-Item -LiteralPath $downloadScriptPath -Force -ErrorAction SilentlyContinue

    if (Test-Path -LiteralPath $DiagnosticRoot) {
        Remove-Item -LiteralPath $DiagnosticRoot -Recurse -Force
    }
    Move-Item -LiteralPath $tempRoot -Destination $DiagnosticRoot

    Write-Host ""
    Write-Host "BodyRig CVLFace diagnostic asset: READY"
    Write-Host "Root:        $DiagnosticRoot"
    Write-Host "Model:       AdaFace ViT-Base@WebFace4M"
    Write-Host "Revision:    $repoRevision"
    Write-Host "Model SHA:   $modelSha"
    Write-Host "Authority:   DIAGNOSTIC ONLY / FALSE"
    Write-Host "Production:  FALSE"
} finally {
    if (Test-Path -LiteralPath $tempRoot -PathType Container) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
