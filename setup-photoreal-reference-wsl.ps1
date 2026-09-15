param(
    [Parameter(Mandatory = $true)][string]$ModelRoot,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [string]$WslExe = "wsl.exe",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$mmposeRevision = "759b39c13fea6ba094afc1fa932f51dc1b11cbf9"
$mmdetRevision = "cfd5d3a985b0249de009b67d04f37263e11cdf3d"
$torchVersion = "2.1.0"
$torchvisionVersion = "0.16.0"
$numpyVersion = "1.26.4"
$opencvVersion = "4.9.0.80"
$mmcvVersion = "2.1.0"
$mmengineVersion = "0.10.7"
$insightfaceVersion = "0.7.3"
$onnxruntimeVersion = "1.20.2"
$openmimVersion = "0.3.9"
$xtcocotoolsVersion = "1.14.3"

function Invoke-Wsl {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$Root,
        [switch]$Capture
    )
    $prefix = @("-d", $Distribution)
    if ($Root) { $prefix += @("-u", "root") }
    $prefix += "--"
    if ($Capture) {
        $output = @(& $WslExe @prefix @Arguments 2>&1)
        $code = $LASTEXITCODE
        if ($code -ne 0) {
            throw "WSL command failed ($code): $($Arguments -join ' ')`n$($output -join [Environment]::NewLine)"
        }
        return ,$output
    }
    & $WslExe @prefix @Arguments
    $code = $LASTEXITCODE
    if ($code -ne 0) { throw "WSL command failed ($code): $($Arguments -join ' ')" }
}

if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "Distribution is required." }
if ([string]::IsNullOrWhiteSpace($LinuxPython) -or -not $LinuxPython.StartsWith('/') -or -not $LinuxPython.EndsWith('/bin/python')) {
    throw "LinuxPython must be an absolute venv path ending in /bin/python."
}
$venvRoot = $LinuxPython.Substring(0, $LinuxPython.Length - "/bin/python".Length)
$mimExe = "$venvRoot/bin/mim"
$ModelRoot = [IO.Path]::GetFullPath($ModelRoot)
if (-not (Test-Path -LiteralPath $ModelRoot -PathType Container)) { throw "ModelRoot not found: $ModelRoot" }
$manifest = Join-Path $ModelRoot "bodyrig-reference-vision-v1.json"
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
    throw "Reference model manifest not found. Run setup-photoreal-reference-models.ps1 first."
}
$environmentReceipt = Join-Path $ModelRoot "runtime-environment.json"
if ((Test-Path -LiteralPath $environmentReceipt -PathType Leaf) -and -not $Force) {
    throw "Runtime environment receipt already exists: $environmentReceipt. Use -Force only to intentionally rebuild the reference environment."
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL REFERENCE WSL SETUP"
Write-Host "Distribution:      $Distribution"
Write-Host "Linux Python:      $LinuxPython"
Write-Host "MMPose revision:   $mmposeRevision"
Write-Host "MMDetection rev:   $mmdetRevision"
Write-Host "MMCV:              $mmcvVersion"
Write-Host "Production:        FALSE"
Write-Host "============================================================"

Invoke-Wsl -Arguments @("/usr/bin/env", "true")
$nvidia = Invoke-Wsl -Arguments @("nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader") -Capture
if ($nvidia.Count -lt 1) { throw "WSL NVIDIA passthrough returned no GPU." }
Write-Host "GPU: $([string]$nvidia[0])"

Invoke-Wsl -Root -Arguments @("/usr/bin/apt-get", "update")
Invoke-Wsl -Root -Arguments @(
    "/usr/bin/apt-get", "install", "-y",
    "python3", "python3-venv", "python3-dev", "build-essential", "git", "ffmpeg",
    "libgl1", "libglib2.0-0", "libgomp1"
)

if ($Force) {
    Invoke-Wsl -Root -Arguments @("/bin/rm", "-rf", $venvRoot)
} else {
    & $WslExe -d $Distribution -- /usr/bin/test -e $venvRoot 2>$null
    if ($LASTEXITCODE -eq 0) { throw "Reference WSL environment already exists: $venvRoot. Use -Force to rebuild." }
}
Invoke-Wsl -Root -Arguments @("/usr/bin/python3", "-m", "venv", $venvRoot)
Invoke-Wsl -Root -Arguments @($LinuxPython, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel", "cython")
Invoke-Wsl -Root -Arguments @(
    $LinuxPython, "-m", "pip", "install",
    "torch==$torchVersion", "torchvision==$torchvisionVersion",
    "--index-url", "https://download.pytorch.org/whl/cu121"
)
Invoke-Wsl -Root -Arguments @(
    $LinuxPython, "-m", "pip", "install",
    "numpy==$numpyVersion",
    "opencv-python==$opencvVersion",
    "onnxruntime-gpu==$onnxruntimeVersion",
    "insightface==$insightfaceVersion",
    "openmim==$openmimVersion",
    "scipy",
    "json-tricks",
    "munkres",
    "xtcocotools==$xtcocotoolsVersion"
)
Invoke-Wsl -Root -Arguments @($mimExe, "install", "mmengine==$mmengineVersion", "mmcv==$mmcvVersion")
Invoke-Wsl -Root -Arguments @(
    $LinuxPython, "-m", "pip", "install", "--no-build-isolation",
    "git+https://github.com/open-mmlab/mmdetection.git@$mmdetRevision"
)
Invoke-Wsl -Root -Arguments @(
    $LinuxPython, "-m", "pip", "install",
    "git+https://github.com/open-mmlab/mmpose.git@$mmposeRevision"
)

$probeCode = @'
import json
import cv2
import insightface
import mmcv
import mmengine
import mmdet
import mmpose
import numpy
import onnxruntime
import torch
import torchvision
payload = {
    "python": __import__("sys").version.split()[0],
    "torch": torch.__version__,
    "torchvision": torchvision.__version__,
    "numpy": numpy.__version__,
    "mmcv": mmcv.__version__,
    "mmengine": mmengine.__version__,
    "mmdet": mmdet.__version__,
    "mmpose": mmpose.__version__,
    "insightface": insightface.__version__,
    "onnxruntime": onnxruntime.__version__,
    "opencv": cv2.__version__,
    "torch_cuda_available": bool(torch.cuda.is_available()),
    "torch_cuda_version": torch.version.cuda,
    "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "onnxruntime_providers": onnxruntime.get_available_providers(),
}
print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
'@
$probeRaw = Invoke-Wsl -Arguments @($LinuxPython, "-c", $probeCode) -Capture
$probeLine = ($probeRaw | Select-Object -Last 1).ToString().Trim()
try { $probe = $probeLine | ConvertFrom-Json -Depth 20 }
catch { throw "Reference environment probe did not return valid JSON: $probeLine" }
if ($probe.torch_cuda_available -ne $true) { throw "PyTorch CUDA is not available in the reference WSL environment." }
if (@($probe.onnxruntime_providers) -notcontains "CUDAExecutionProvider") {
    throw "ONNX Runtime CUDAExecutionProvider is not available in the reference WSL environment."
}
if ([string]$probe.mmcv -ne $mmcvVersion) { throw "Unexpected MMCV version: $($probe.mmcv)" }
if ([string]$probe.mmengine -ne $mmengineVersion) { throw "Unexpected MMEngine version: $($probe.mmengine)" }

$receipt = [ordered]@{
    format = "bodyrig-photoreal-reference-runtime-environment"
    version = 1
    distribution = $Distribution
    linux_python = $LinuxPython
    mmpose_revision = $mmposeRevision
    mmdetection_revision = $mmdetRevision
    requested_versions = [ordered]@{
        torch = $torchVersion
        torchvision = $torchvisionVersion
        numpy = $numpyVersion
        opencv = $opencvVersion
        mmcv = $mmcvVersion
        mmengine = $mmengineVersion
        insightface = $insightfaceVersion
        onnxruntime = $onnxruntimeVersion
        openmim = $openmimVersion
        xtcocotools = $xtcocotoolsVersion
    }
    observed = $probe
    nvidia_smi = @($nvidia | ForEach-Object { [string]$_ })
    cuda_required = $true
    build_only = $true
    production_activation = $false
}
$receipt | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $environmentReceipt -Encoding UTF8

Write-Host ""
Write-Host "BodyRig Photoreal reference WSL environment: READY"
Write-Host "Python:           $($probe.python)"
Write-Host "Torch:            $($probe.torch)"
Write-Host "CUDA:             $($probe.torch_cuda_version)"
Write-Host "GPU:              $($probe.gpu_name)"
Write-Host "MMCV:             $($probe.mmcv)"
Write-Host "MMPose:           $($probe.mmpose)"
Write-Host "MMDetection:      $($probe.mmdet)"
Write-Host "Receipt:          $environmentReceipt"
Write-Host "Production:       FALSE"
