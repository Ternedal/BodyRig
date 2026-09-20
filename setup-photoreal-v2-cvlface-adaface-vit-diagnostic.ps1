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
$runtimeDependencyProfile = "cvlface-vit-runtime-v2"

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

$existingAssetReady = $false
$existingRuntimeReady = $false
if (Test-Path -LiteralPath $DiagnosticRoot -PathType Container) {
    $model = Join-Path $DiagnosticRoot $modelRelative
    $provenance = Join-Path $DiagnosticRoot "source-provenance.json"
    if (
        (Test-Path -LiteralPath $model -PathType Leaf) -and
        (Test-Path -LiteralPath $provenance -PathType Leaf) -and
        ((Sha256 $model) -eq $modelSha)
    ) {
        $existing = Get-Content -LiteralPath $provenance -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
        $existingAssetReady = (
            $existing.format -eq "bodyrig-photoreal-cvlface-diagnostic-provenance" -and
            $existing.repo_id -eq $repoId -and
            $existing.repo_revision -eq $repoRevision -and
            $existing.model_sha256 -eq $modelSha -and
            $existing.reuses_bodyrig_photoreal_torch -eq $true -and
            $existing.diagnostic_only -eq $true -and
            $existing.production_activation -eq $false
        )
        $existingRuntimeReady = (
            $existingAssetReady -and
            $existing.runtime_dependency_profile -eq $runtimeDependencyProfile -and
            (Test-Path -LiteralPath (Join-Path $DiagnosticRoot "python\fvcore\__init__.py") -PathType Leaf)
        )
        if ($existingRuntimeReady -and -not $Force) {
            Write-Host "BodyRig CVLFace diagnostic asset: READY"
            Write-Host "Root:       $DiagnosticRoot"
            Write-Host "Model:      AdaFace ViT-Base@WebFace4M"
            Write-Host "Runtime:    $runtimeDependencyProfile"
            Write-Host "Production: FALSE"
            exit 0
        }
    }
    if (-not $existingAssetReady -and -not $Force) {
        throw "CVLFace diagnostic root already exists but is not the exact pinned asset: $DiagnosticRoot. Use -Force only after reviewing the directory."
    }
}
$runtimeProbe = @'
import json
import numpy
import torch
import torchvision
payload = {
    "torch": torch.__version__.split("+")[0],
    "torchvision": torchvision.__version__.split("+")[0],
    "numpy": numpy.__version__,
    "cuda_available": bool(torch.cuda.is_available()),
    "cuda_version": torch.version.cuda,
}
print(json.dumps(payload, sort_keys=True))
'@
$runtimeLines = @(& wsl.exe -d $Distribution -- $LinuxPython -c $runtimeProbe 2>&1)
if ($LASTEXITCODE -ne 0 -or $runtimeLines.Count -lt 1) {
    throw "Could not probe the existing BodyRig Photoreal Torch runtime: $($runtimeLines -join ' ')"
}
try {
    $runtime = ($runtimeLines | Select-Object -Last 1) | ConvertFrom-Json -Depth 10
} catch {
    throw "BodyRig Photoreal Torch runtime probe returned invalid JSON: $($runtimeLines -join ' ')"
}
if ([string]$runtime.torch -ne "2.1.0") {
    throw "CVLFace diagnostic requires BodyRig's pinned Torch 2.1.0 runtime; observed=$($runtime.torch)"
}
if ([string]$runtime.torchvision -ne "0.16.0") {
    throw "CVLFace diagnostic requires BodyRig's pinned torchvision 0.16.0 runtime; observed=$($runtime.torchvision)"
}
if ([string]$runtime.numpy -ne "1.26.4") {
    throw "CVLFace diagnostic requires BodyRig's pinned NumPy 1.26.4 runtime; observed=$($runtime.numpy)"
}
if ($runtime.cuda_available -ne $true) {
    throw "CVLFace diagnostic requires the existing BodyRig Photoreal CUDA runtime."
}

$lightweightDependencies = @(
    "transformers==4.33.0",
    "huggingface-hub==0.17.3",
    "omegaconf==2.3.0",
    "timm==0.9.7",
    "safetensors==0.3.3",
    "tokenizers==0.13.3",
    "antlr4-python3-runtime==4.9.3",
    "filelock==3.14.0",
    "fsspec==2023.9.2",
    "packaging==24.0",
    "regex==2023.8.8",
    "requests==2.28.2",
    "tqdm==4.65.0",
    "PyYAML==6.0.1",
    "fvcore==0.1.5.post20221221",
    "yacs==0.1.8",
    "termcolor==2.3.0",
    "tabulate==0.9.0",
    "iopath==0.1.10",
    "portalocker==2.8.2",
    "aiofiles==23.2.1"
)

function Install-CvlFaceDependencies {
    param([Parameter(Mandatory = $true)][string]$WslDependencyRoot)
    Install-CvlFaceDependencies -WslDependencyRoot $wslDependencyRoot

    $downloadScript = @'
import sys
from huggingface_hub import hf_hub_download

target, repo_id, revision = sys.argv[1:4]
files_txt = hf_hub_download(
    repo_id=repo_id,
    filename="files.txt",
    revision=revision,
    local_dir=target,
    local_dir_use_symlinks=False,
)
with open(files_txt, "r", encoding="utf-8") as handle:
    files = [line.strip() for line in handle if line.strip()]
for filename in files + ["config.json", "wrapper.py", "model.safetensors"]:
    hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        revision=revision,
        local_dir=target,
        local_dir_use_symlinks=False,
    )
'@
    $downloadScriptPath = Join-Path $tempRoot "download-cvlface.py"
    $downloadScript | Set-Content -LiteralPath $downloadScriptPath -Encoding UTF8
    $wslDownloadScript = Convert-ToWslPath $downloadScriptPath

    Write-Host "Downloading pinned CVLFace model files..."
    $downloadArgs = @(
        "-d", $Distribution, "--", "env",
        "PYTHONPATH=$wslDependencyRoot",
        $LinuxPython, $wslDownloadScript,
        $wslModelRoot, $repoId, $repoRevision
    )
    & wsl.exe @downloadArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Pinned CVLFace model download failed with exit code $LASTEXITCODE."
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
        (Join-Path $tempRoot "model\files.txt")
    )
    foreach ($item in $required) {
        if (-not (Test-Path -LiteralPath $item -PathType Leaf)) {
            throw "Pinned CVLFace model download is incomplete: $item"
        }
    }
    Test-CvlFaceModel -WslDependencyRoot $wslDependencyRoot -WslModelRoot $wslModelRoot


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
        license_operator_accepted = $true
        runtime_dependency_profile = $runtimeDependencyProfile
        fvcore = "0.1.5.post20221221"
        timm = "0.9.7"
        model_cuda_smoke_test = $true
        reuses_bodyrig_photoreal_torch = $true
        bodyrig_torch = [string]$runtime.torch
        bodyrig_torchvision = [string]$runtime.torchvision
        bodyrig_numpy = [string]$runtime.numpy
        bodyrig_cuda = [string]$runtime.cuda_version
        parallel_torch_install = $false
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
    Write-Host "Torch:       $($runtime.torch) (reused)"
    Write-Host "CUDA:        $($runtime.cuda_version) (reused)"
    Write-Host "Authority:   DIAGNOSTIC ONLY / FALSE"
    Write-Host "Production:  FALSE"
} finally {
    if (Test-Path -LiteralPath $tempRoot -PathType Container) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
