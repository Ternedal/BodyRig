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
    param([Parameter(Mandatory = $true)][string]$WindowsPath)
    if ($WindowsPath.StartsWith('/')) {
        return $WindowsPath
    }
    $pythonCode = @'
import base64
import sys
sys.path.insert(0, sys.argv[1])
from bodyrig.wsl_adapter_bridge import make_wsl_path_converter
value = make_wsl_path_converter(sys.argv[2], sys.argv[3])(sys.argv[4])
print(base64.b64encode(value.encode("utf-8")).decode("ascii"))
'@
    $lines = @(
        & $windowsPython -c $pythonCode $repoRoot "wsl.exe" $Distribution $WindowsPath 2>&1
    )
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) {
        throw "Could not convert path with BodyRig WSL bridge: $WindowsPath | $($lines -join ' ')"
    }
    $encoded = ([string]$lines[0]).Trim()
    try {
        $value = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
    } catch {
        throw "BodyRig WSL bridge returned invalid encoded path data: $WindowsPath"
    }
    if ([string]::IsNullOrWhiteSpace($value) -or -not $value.StartsWith('/')) {
        throw "BodyRig WSL bridge returned invalid path: $WindowsPath"
    }
    return $value
}

function Probe-BodyRigRuntime {
    $probe = @'
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
    $lines = @(& wsl.exe -d $Distribution -- $LinuxPython -c $probe 2>&1)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -lt 1) {
        throw "Could not probe the existing BodyRig Photoreal Torch runtime: $($lines -join ' ')"
    }
    try {
        $runtime = ($lines | Select-Object -Last 1) | ConvertFrom-Json -Depth 10
    } catch {
        throw "BodyRig Photoreal Torch runtime probe returned invalid JSON: $($lines -join ' ')"
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
    return $runtime
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
    "aiofiles==23.2.1",
    "charset-normalizer==3.2.0",
    "idna==3.4",
    "urllib3==1.26.18",
    "certifi==2023.7.22"
)

function Install-CvlFaceDependencies {
    param([Parameter(Mandatory = $true)][string]$WslDependencyRoot)

    Write-Host "Installing lightweight CVLFace dependencies (reusing BodyRig Torch/CUDA)..."
    $pipArgs = @(
        "-d", $Distribution, "--",
        $LinuxPython, "-m", "pip", "install",
        "--disable-pip-version-check", "--no-input",
        "--no-deps", "--upgrade",
        "--target", $WslDependencyRoot
    ) + $lightweightDependencies
    & wsl.exe @pipArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CVLFace lightweight dependency installation failed with exit code $LASTEXITCODE."
    }

    $probe = @'
import sys
root = sys.argv[1]
sys.path.insert(0, root)
import fvcore
import huggingface_hub
import iopath
import omegaconf
import safetensors
import timm
import tokenizers
import transformers
import torch
import torchvision
from fvcore.nn import flop_count
assert fvcore.__version__ == "0.1.5.post20221221"
assert timm.__version__ == "0.9.7"
assert torch.__version__.split("+")[0] == "2.1.0"
assert torchvision.__version__.split("+")[0] == "0.16.0"
print("ok")
'@
    $lines = @(
        & wsl.exe -d $Distribution -- $LinuxPython -c $probe $WslDependencyRoot 2>&1
    )
    if ($LASTEXITCODE -ne 0 -or ([string]($lines | Select-Object -Last 1)).Trim() -ne "ok") {
        throw "CVLFace dependency probe failed: $($lines -join ' ')"
    }
}

function Test-CvlFaceModel {
    param(
        [Parameter(Mandatory = $true)][string]$WslDependencyRoot,
        [Parameter(Mandatory = $true)][string]$WslModelRoot
    )

    $smoke = @'
import os
import sys
dependency_root, model_root = sys.argv[1:3]
sys.path.insert(0, dependency_root)
sys.path.insert(0, model_root)
import torch
from transformers import AutoModel
cwd = os.getcwd()
try:
    os.chdir(model_root)
    model = AutoModel.from_pretrained(
        model_root,
        trust_remote_code=True,
        local_files_only=True,
    )
finally:
    os.chdir(cwd)
model.eval().to("cuda:0")
sample = torch.zeros((1, 3, 112, 112), dtype=torch.float32, device="cuda:0")
with torch.inference_mode():
    output = model(sample)
if isinstance(output, (list, tuple)):
    if not output:
        raise SystemExit("CVLFace smoke inference returned empty tuple/list")
    output = output[0]
if hasattr(output, "last_hidden_state"):
    output = output.last_hidden_state
shape = tuple(int(value) for value in output.shape)
if shape != (1, 512):
    raise SystemExit(f"unexpected CVLFace output shape: {shape}")
if not bool(torch.isfinite(output).all()):
    raise SystemExit("CVLFace smoke inference returned non-finite values")
print("ok")
'@
    Write-Host "Smoke-testing pinned CVLFace model on CUDA..."
    $args = @(
        "-d", $Distribution, "--", "env",
        "PYTHONPATH=$WslDependencyRoot",
        "TRANSFORMERS_OFFLINE=1",
        "HF_HUB_OFFLINE=1",
        $LinuxPython, "-c", $smoke,
        $WslDependencyRoot, $WslModelRoot
    )
    $lines = @(& wsl.exe @args 2>&1)
    if ($LASTEXITCODE -ne 0 -or ([string]($lines | Select-Object -Last 1)).Trim() -ne "ok") {
        throw "CVLFace CUDA smoke test failed: $($lines -join ' ')"
    }
}

function Write-RuntimeProvenance {
    param(
        [Parameter(Mandatory = $true)]$Provenance,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Runtime
    )

    $Provenance | Add-Member -NotePropertyName runtime_dependency_profile -NotePropertyValue $runtimeDependencyProfile -Force
    $Provenance | Add-Member -NotePropertyName fvcore -NotePropertyValue "0.1.5.post20221221" -Force
    $Provenance | Add-Member -NotePropertyName timm -NotePropertyValue "0.9.7" -Force
    $Provenance | Add-Member -NotePropertyName model_cuda_smoke_test -NotePropertyValue $true -Force
    $Provenance | Add-Member -NotePropertyName reuses_bodyrig_photoreal_torch -NotePropertyValue $true -Force
    $Provenance | Add-Member -NotePropertyName bodyrig_torch -NotePropertyValue ([string]$Runtime.torch) -Force
    $Provenance | Add-Member -NotePropertyName bodyrig_torchvision -NotePropertyValue ([string]$Runtime.torchvision) -Force
    $Provenance | Add-Member -NotePropertyName bodyrig_numpy -NotePropertyValue ([string]$Runtime.numpy) -Force
    $Provenance | Add-Member -NotePropertyName bodyrig_cuda -NotePropertyValue ([string]$Runtime.cuda_version) -Force
    $Provenance | Add-Member -NotePropertyName parallel_torch_install -NotePropertyValue $false -Force
    $Provenance | Add-Member -NotePropertyName diagnostic_only -NotePropertyValue $true -Force
    $Provenance | Add-Member -NotePropertyName identity_matching_authorized -NotePropertyValue $false -Force
    $Provenance | Add-Member -NotePropertyName teacher_training_authorized -NotePropertyValue $false -Force
    $Provenance | Add-Member -NotePropertyName photoreal_acceptance_authority -NotePropertyValue $false -Force
    $Provenance | Add-Member -NotePropertyName production_activation -NotePropertyValue $false -Force
    $Provenance | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

$runtime = Probe-BodyRigRuntime

$existingAssetReady = $false
$existingRuntimeReady = $false
$existing = $null
$existingModel = Join-Path $DiagnosticRoot $modelRelative
$existingProvenancePath = Join-Path $DiagnosticRoot "source-provenance.json"

if (Test-Path -LiteralPath $DiagnosticRoot -PathType Container) {
    if (
        (Test-Path -LiteralPath $existingModel -PathType Leaf) -and
        (Test-Path -LiteralPath $existingProvenancePath -PathType Leaf) -and
        ((Sha256 $existingModel) -eq $modelSha)
    ) {
        $existing = Get-Content -LiteralPath $existingProvenancePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
        $existingAssetReady = (
            $existing.format -eq "bodyrig-photoreal-cvlface-diagnostic-provenance" -and
            $existing.repo_id -eq $repoId -and
            $existing.repo_revision -eq $repoRevision -and
            $existing.model_sha256 -eq $modelSha -and
            $existing.diagnostic_only -eq $true -and
            $existing.production_activation -eq $false
        )
        $hasRuntimeProfile = $existing.PSObject.Properties.Name -contains "runtime_dependency_profile"
        $hasSmoke = $existing.PSObject.Properties.Name -contains "model_cuda_smoke_test"
        $existingRuntimeReady = (
            $existingAssetReady -and
            $hasRuntimeProfile -and
            $existing.runtime_dependency_profile -eq $runtimeDependencyProfile -and
            $hasSmoke -and
            $existing.model_cuda_smoke_test -eq $true -and
            (Test-Path -LiteralPath (Join-Path $DiagnosticRoot "python\fvcore\__init__.py") -PathType Leaf)
        )

        if ($existingRuntimeReady -and -not $Force) {
            Write-Host "BodyRig CVLFace diagnostic asset: READY"
            Write-Host "Root:       $DiagnosticRoot"
            Write-Host "Model:      AdaFace ViT-Base@WebFace4M"
            Write-Host "Runtime:    $runtimeDependencyProfile"
            Write-Host "Torch:      $($runtime.torch) (reused)"
            Write-Host "CUDA:       $($runtime.cuda_version) (reused)"
            Write-Host "Production: FALSE"
            exit 0
        }
    }

    if (-not $existingAssetReady -and -not $Force) {
        throw "CVLFace diagnostic root already exists but is not the exact pinned asset: $DiagnosticRoot. Use -Force only after reviewing the directory."
    }
}

if ($existingAssetReady -and -not $existingRuntimeReady -and -not $Force) {
    Write-Host "Repairing CVLFace lightweight runtime in place; pinned model download is reused."
    $dependencyRoot = Join-Path $DiagnosticRoot "python"
    New-Item -ItemType Directory -Path $dependencyRoot -Force | Out-Null
    $wslDependencyRoot = Convert-ToWslPath $dependencyRoot
    $wslModelRoot = Convert-ToWslPath (Join-Path $DiagnosticRoot "model")

    Install-CvlFaceDependencies -WslDependencyRoot $wslDependencyRoot
    Test-CvlFaceModel -WslDependencyRoot $wslDependencyRoot -WslModelRoot $wslModelRoot
    Write-RuntimeProvenance -Provenance $existing -Path $existingProvenancePath -Runtime $runtime

    Write-Host ""
    Write-Host "BodyRig CVLFace diagnostic runtime: REPAIRED"
    Write-Host "Root:        $DiagnosticRoot"
    Write-Host "Model:       AdaFace ViT-Base@WebFace4M (reused)"
    Write-Host "Runtime:     $runtimeDependencyProfile"
    Write-Host "Torch:       $($runtime.torch) (reused)"
    Write-Host "CUDA:        $($runtime.cuda_version) (reused)"
    Write-Host "Authority:   DIAGNOSTIC ONLY / FALSE"
    Write-Host "Production:  FALSE"
    exit 0
}

$parent = Split-Path -Parent $DiagnosticRoot
if ([string]::IsNullOrWhiteSpace($parent)) {
    throw "CVLFace diagnostic parent is invalid: $DiagnosticRoot"
}
New-Item -ItemType Directory -Path $parent -Force | Out-Null

$staleStages = @(
    Get-ChildItem -LiteralPath $parent -Directory -Filter "cvlface-stage-*" -ErrorAction SilentlyContinue
)
foreach ($stale in $staleStages) {
    Write-Host "Removing stale CVLFace staging directory: $($stale.FullName)"
    Remove-Item -LiteralPath $stale.FullName -Recurse -Force -ErrorAction Stop
}

$tempRoot = Join-Path $parent ("cvlface-stage-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
$dependencyRoot = Join-Path $tempRoot "python"
$modelRoot = Join-Path $tempRoot "model"
New-Item -ItemType Directory -Path $dependencyRoot -Force | Out-Null
New-Item -ItemType Directory -Path $modelRoot -Force | Out-Null
$wslDependencyRoot = Convert-ToWslPath $dependencyRoot
$wslModelRoot = Convert-ToWslPath $modelRoot

try {
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
        (Join-Path $tempRoot "model\files.txt"),
        (Join-Path $tempRoot "model\pretrained_model\model.pt"),
        (Join-Path $tempRoot "model\pretrained_model\model.yaml")
    )
    foreach ($item in $required) {
        if (-not (Test-Path -LiteralPath $item -PathType Leaf)) {
            throw "Pinned CVLFace model download is incomplete: $item"
        }
    }

    Test-CvlFaceModel -WslDependencyRoot $wslDependencyRoot -WslModelRoot $wslModelRoot

    $provenance = [pscustomobject][ordered]@{
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
    $provenancePath = Join-Path $tempRoot "source-provenance.json"
    $provenance | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $provenancePath -Encoding UTF8

    Remove-Item -LiteralPath $downloadScriptPath -Force -ErrorAction SilentlyContinue

    if (Test-Path -LiteralPath $DiagnosticRoot) {
        if (-not $Force) {
            throw "CVLFace diagnostic root appeared during staging: $DiagnosticRoot"
        }
        Remove-Item -LiteralPath $DiagnosticRoot -Recurse -Force
    }
    Move-Item -LiteralPath $tempRoot -Destination $DiagnosticRoot

    Write-Host ""
    Write-Host "BodyRig CVLFace diagnostic asset: READY"
    Write-Host "Root:        $DiagnosticRoot"
    Write-Host "Model:       AdaFace ViT-Base@WebFace4M"
    Write-Host "Revision:    $repoRevision"
    Write-Host "Model SHA:   $modelSha"
    Write-Host "Runtime:     $runtimeDependencyProfile"
    Write-Host "Torch:       $($runtime.torch) (reused)"
    Write-Host "CUDA:        $($runtime.cuda_version) (reused)"
    Write-Host "Authority:   DIAGNOSTIC ONLY / FALSE"
    Write-Host "Production:  FALSE"
} finally {
    if (Test-Path -LiteralPath $tempRoot -PathType Container) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
