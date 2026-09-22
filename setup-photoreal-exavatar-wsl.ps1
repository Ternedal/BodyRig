param(
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-exavatar/bin/python",
    [string]$WslExe = "wsl.exe",
    [switch]$Force,
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$torchVersion = "2.6.0"
$torchvisionVersion = "0.21.0"
$expectedCudaVersion = "12.4"
$numpyVersion = "1.26.4"
$scipyVersion = "1.15.2"
$opencvVersion = "4.10.0.84"
$smplxVersion = "0.1.28"
$lpipsVersion = "0.1.4"
$mmcvVersion = "2.1.0"
$mmcvCommit = "57c4e25e06e2d4f8a9357c84bcd24089a284dc88"
$mmengineVersion = "0.10.7"
$mmdetVersion = "3.3.0"
$mmposeVersion = "1.3.2"
$openmimVersion = "0.3.9"
$setuptoolsVersion = "80.10.2"
$pyopenglVersion = "3.1.0"
$chumpyVersion = "0.70"
$pytorch3dCommit = "0a7d4c1a171e8b768c63f15b17564f9ad495f49b"

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
$receipt = "$venvRoot/bodyrig-exavatar-runtime-setup.json"

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL EXAVATAR WSL SETUP"
Write-Host "Distribution:      $Distribution"
Write-Host "Linux Python:      $LinuxPython"
Write-Host "Torch:             $torchVersion / CUDA $expectedCudaVersion wheel"
Write-Host "PyTorch3D commit:  $pytorch3dCommit"
Write-Host "MMCV:              $mmcvVersion @ $mmcvCommit"
Write-Host "Chumpy:            $chumpyVersion + NumPy 1.26 compatibility patch"
Write-Host "Production:        FALSE"
Write-Host "============================================================"

Invoke-Wsl -Arguments @("/usr/bin/env", "true")
$nvidia = Invoke-Wsl -Arguments @("nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader") -Capture
if ($nvidia.Count -lt 1) { throw "WSL NVIDIA passthrough returned no GPU." }
Write-Host "GPU: $([string]$nvidia[0])"

# PyTorch3D and the pinned Gaussian rasterizer are CUDA extensions. Do not
# silently install Ubuntu 22.04's old nvidia-cuda-toolkit. The compiler major
# and minor must match the pinned Torch CUDA runtime exactly.
& $WslExe -d $Distribution -- /usr/bin/which nvcc 1>$null 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "nvcc is not available in WSL. Install a CUDA toolkit compatible with the pinned Torch CUDA runtime before ExAvatar setup; BodyRig will not install Ubuntu's legacy nvidia-cuda-toolkit automatically."
}
$nvcc = Invoke-Wsl -Arguments @("nvcc", "--version") -Capture
$nvccText = $nvcc -join "`n"
if ($nvccText -notmatch "release\s+$([regex]::Escape($expectedCudaVersion))(?:,|\s)") {
    throw "CUDA compiler mismatch: pinned Torch requires CUDA $expectedCudaVersion but nvcc did not report release $expectedCudaVersion. Refusing to build PyTorch3D/Gaussian extensions with mismatched CUDA toolchains."
}
Write-Host (($nvcc | Select-Object -Last 1).ToString())

Invoke-Wsl -Root -Arguments @("/usr/bin/apt-get", "update")
Invoke-Wsl -Root -Arguments @(
    "/usr/bin/apt-get", "install", "-y",
    "python3.10", "python3.10-venv", "python3.10-dev",
    "build-essential", "git", "ffmpeg", "cmake", "ninja-build",
    "libgl1", "libglib2.0-0", "libgomp1", "libegl1", "libgles2"
)

# The runtime venv intentionally shares /opt/bodyrig-exavatar with the
# already-installed public dependency tree at /opt/bodyrig-exavatar/deps.
# Do not reject or delete the whole root merely because deps/workspaces exist.
$runtimeMarker = "$venvRoot/pyvenv.cfg"
if ($Force -and $Resume) {
    throw "-Force and -Resume are mutually exclusive."
}
if ($Force) {
    foreach ($runtimePath in @(
        "$venvRoot/bin",
        "$venvRoot/include",
        "$venvRoot/lib",
        "$venvRoot/lib64",
        "$venvRoot/share",
        $runtimeMarker,
        $receipt
    )) {
        Invoke-Wsl -Root -Arguments @("/bin/rm", "-rf", $runtimePath)
    }
} elseif ($Resume) {
    & $WslExe -d $Distribution -- /usr/bin/test -f $runtimeMarker 2>$null
    $markerExists = ($LASTEXITCODE -eq 0)
    & $WslExe -d $Distribution -- /usr/bin/test -x $LinuxPython 2>$null
    $pythonExists = ($LASTEXITCODE -eq 0)
    & $WslExe -d $Distribution -- /usr/bin/test -e $receipt 2>$null
    $receiptExists = ($LASTEXITCODE -eq 0)
    if (-not $markerExists -or -not $pythonExists) {
        throw "Cannot resume ExAvatar runtime because the partial venv is not structurally valid: $venvRoot"
    }
    if ($receiptExists) {
        throw "Cannot resume ExAvatar runtime because a completed runtime receipt already exists: $receipt"
    }
    Write-Host "Runtime recovery:   RESUME PARTIAL VENV"
} else {
    & $WslExe -d $Distribution -- /usr/bin/test -e $runtimeMarker 2>$null
    $markerExists = ($LASTEXITCODE -eq 0)
    & $WslExe -d $Distribution -- /usr/bin/test -e $LinuxPython 2>$null
    $pythonExists = ($LASTEXITCODE -eq 0)
    & $WslExe -d $Distribution -- /usr/bin/test -e $receipt 2>$null
    $receiptExists = ($LASTEXITCODE -eq 0)
    if ($markerExists -or $pythonExists -or $receiptExists) {
        throw "ExAvatar WSL runtime already exists under: $venvRoot. Use -Resume for an incomplete runtime or -Force to rebuild it while preserving public dependencies."
    }
}

if (-not $Resume) {
    Invoke-Wsl -Root -Arguments @("/usr/bin/python3.10", "-m", "venv", $venvRoot)
}
Invoke-Wsl -Root -Arguments @($LinuxPython, "-m", "pip", "install", "--upgrade", "pip", "setuptools==$setuptoolsVersion", "wheel", "cython", "ninja")
Invoke-Wsl -Root -Arguments @(
    $LinuxPython, "-m", "pip", "install",
    "torch==$torchVersion", "torchvision==$torchvisionVersion",
    "--index-url", "https://download.pytorch.org/whl/cu124"
)

# Install non-OpenMMLab runtime dependencies first. Keep MMDetection/MMPose
# out of this resolver pass so they cannot select a different MMCV variant.
Invoke-Wsl -Root -Arguments @(
    $LinuxPython, "-m", "pip", "install",
    "numpy==$numpyVersion", "scipy==$scipyVersion", "opencv-python==$opencvVersion",
    "smplx==$smplxVersion", "lpips==$lpipsVersion",
    "openmim==$openmimVersion", "mmengine==$mmengineVersion",
    "kornia==0.8.0", "yacs==0.1.8", "face-alignment==1.3.4",
    "timm==1.0.15", "einops==0.8.1", "tqdm==4.67.1", "pillow==10.4.0",
    "torchgeometry==0.1.2", "plyfile==1.1", "scikit-image==0.25.2", "PyYAML==6.0.2",
    "pyrender==0.1.45", "trimesh==3.23.5", "tensorboardX==2.6.2.2",
    "setproctitle==1.3.5", "fvcore", "iopath", "pyopengl==$pyopenglVersion"
)

# ExAvatar lists chumpy 0.71, but public PyPI publishes 0.70. Install the
# public package separately, then patch its legacy NumPy alias import below.
Invoke-Wsl -Root -Arguments @(
    $LinuxPython, "-m", "pip", "install", "--no-build-isolation", "chumpy==$chumpyVersion"
)

# OpenMIM 0.3.9 still imports pkg_resources. setuptools 82+ removed it,
# so keep the runtime on the last compatible setuptools family and fail closed
# before invoking mim if that compatibility module is unavailable.
Invoke-Wsl -Root -Arguments @(
    $LinuxPython, "-c",
    "import importlib.metadata, pkg_resources; assert importlib.metadata.version('setuptools') == '$setuptoolsVersion'"
)

# OpenMMLab publishes prebuilt MMCV wheels only for selected Torch/CUDA
# combinations. Torch 2.6 / CUDA 12.4 falls back to the source distribution,
# so build the exact MMCV 2.1.0 release commit explicitly. Disable PEP517
# build isolation so setup.py sees the pinned Torch and setuptools<81 runtime.
Invoke-Wsl -Root -Arguments @(
    "/usr/bin/env",
    "MMCV_WITH_OPS=1",
    "CUDA_HOME=/usr/local/cuda-$expectedCudaVersion",
    "PYTHONNOUSERSITE=1",
    $LinuxPython, "-m", "pip", "install", "--no-build-isolation",
    "git+https://github.com/open-mmlab/mmcv.git@$mmcvCommit"
)
Invoke-Wsl -Root -Arguments @($mimExe, "install", "mmdet==$mmdetVersion")
Invoke-Wsl -Root -Arguments @($LinuxPython, "-m", "pip", "install", "mmpose==$mmposeVersion")
Invoke-Wsl -Root -Arguments @($LinuxPython, "-m", "pip", "check")

# Pin PyTorch3D to exact public source bytes and build against the already
# pinned Torch/CUDA environment. Build isolation could otherwise hide Torch
# from setup.py or compile against a transient dependency set.
Invoke-Wsl -Root -Arguments @(
    "/usr/bin/env",
    "FORCE_CUDA=1",
    "PYTHONNOUSERSITE=1",
    $LinuxPython, "-m", "pip", "install", "--no-build-isolation",
    "git+https://github.com/facebookresearch/pytorch3d.git@$pytorch3dCommit"
)
Invoke-Wsl -Root -Arguments @($LinuxPython, "-m", "pip", "check")

# Chumpy 0.70 imports NumPy aliases removed in modern NumPy. Patch only the
# exact legacy import line without importing Chumpy first.
$chumpyPatchCode = @'
import hashlib
import json
import sysconfig
from pathlib import Path

path = Path(sysconfig.get_paths()["purelib"]) / "chumpy" / "__init__.py"
if not path.is_file():
    raise SystemExit(f"chumpy __init__.py not found: {path}")
raw = path.read_text(encoding="utf-8")
marker = "from numpy import bool, int, float, complex, object, unicode, str, nan, inf"
replacement = "\n".join([
    "# BodyRig NumPy>=1.24 compatibility patch for public chumpy 0.70.",
    "import builtins as _bodyrig_builtins",
    "bool = _bodyrig_builtins.bool",
    "int = _bodyrig_builtins.int",
    "float = _bodyrig_builtins.float",
    "complex = _bodyrig_builtins.complex",
    "object = _bodyrig_builtins.object",
    "unicode = _bodyrig_builtins.str",
    "str = _bodyrig_builtins.str",
    "from numpy import nan, inf",
])
if raw.count(marker) != 1:
    raise SystemExit(f"chumpy legacy NumPy marker mismatch: expected exactly one occurrence, observed {raw.count(marker)}")
before = hashlib.sha256(path.read_bytes()).hexdigest()
path.write_text(raw.replace(marker, replacement, 1), encoding="utf-8")
after = hashlib.sha256(path.read_bytes()).hexdigest()
if before == after:
    raise SystemExit("chumpy compatibility patch did not change bytes")
print(json.dumps({
    "path": str(path),
    "before_sha256": before,
    "sha256": after,
    "patch": "bodyrig-chumpy-0.70-numpy-alias-v1",
}, sort_keys=True, separators=(",", ":")))
'@
$chumpyPatchRaw = Invoke-Wsl -Root -Arguments @($LinuxPython, "-c", $chumpyPatchCode) -Capture
$chumpyPatchLine = ($chumpyPatchRaw | Select-Object -Last 1).ToString().Trim()
try { $chumpyPatch = $chumpyPatchLine | ConvertFrom-Json -Depth 10 }
catch { throw "Chumpy compatibility patch did not return valid JSON: $chumpyPatchLine" }

# Hand4Whole depends on torchgeometry 0.1.2, whose old bool-mask arithmetic is
# incompatible with modern PyTorch. Apply the fix published by its author.
$torchgeometryPatchCode = @'
import hashlib
import json
from pathlib import Path
import torchgeometry.core.conversions as conversions

path = Path(conversions.__file__).resolve()
raw = path.read_text(encoding="utf-8")
replacements = {
    "mask_c0 = mask_d2 * mask_d0_d1": "mask_c0 = mask_d2.float() * mask_d0_d1.float()",
    "mask_c1 = mask_d2 * (1 - mask_d0_d1)": "mask_c1 = mask_d2.float() * (1 - mask_d0_d1.float())",
    "mask_c2 = (1 - mask_d2) * mask_d0_nd1": "mask_c2 = (1 - mask_d2.float()) * mask_d0_nd1.float()",
    "mask_c3 = (1 - mask_d2) * (1 - mask_d0_nd1)": "mask_c3 = (1 - mask_d2.float()) * (1 - mask_d0_nd1.float())",
}
for old, new in replacements.items():
    if raw.count(old) != 1:
        raise SystemExit(f"torchgeometry legacy marker mismatch: {old}")
    raw = raw.replace(old, new, 1)
path.write_text(raw, encoding="utf-8")
print(json.dumps({
    "path": str(path),
    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    "patch": "hand4whole-author-float-mask-v1",
}, sort_keys=True, separators=(",", ":")))
'@
$torchgeometryPatchRaw = Invoke-Wsl -Root -Arguments @($LinuxPython, "-c", $torchgeometryPatchCode) -Capture
$torchgeometryPatchLine = ($torchgeometryPatchRaw | Select-Object -Last 1).ToString().Trim()
try { $torchgeometryPatch = $torchgeometryPatchLine | ConvertFrom-Json -Depth 10 }
catch { throw "torchgeometry patch did not return valid JSON: $torchgeometryPatchLine" }

$probeCode = @'
import json
import sys
import chumpy
import cv2
import einops
import face_alignment
import kornia
import lpips
import OpenGL
import pyrender
import mmcv
import mmdet
import mmengine
import mmpose
import numpy
import pytorch3d
import scipy
import smplx
import timm
import torch
import torchgeometry
import torchvision
import importlib.metadata
from pytorch3d.transforms import axis_angle_to_matrix
from torchgeometry.core.conversions import rotation_matrix_to_angle_axis

if not torch.cuda.is_available():
    raise SystemExit("CUDA unavailable")
mat = axis_angle_to_matrix(torch.zeros((1, 3), device="cuda:0"))
if tuple(mat.shape) != (1, 3, 3):
    raise SystemExit("PyTorch3D smoke failed")
legacy = torch.eye(3).view(1, 3, 3)
axis = rotation_matrix_to_angle_axis(legacy)
if tuple(axis.shape) != (1, 3):
    raise SystemExit("torchgeometry smoke failed")
if not hasattr(chumpy, "Ch"):
    raise SystemExit("chumpy import smoke failed")
payload = {
    "python": sys.version.split()[0],
    "torch": torch.__version__,
    "torchvision": torchvision.__version__,
    "torch_cuda": torch.version.cuda,
    "gpu": torch.cuda.get_device_name(0),
    "numpy": numpy.__version__,
    "scipy": scipy.__version__,
    "opencv": cv2.__version__,
    "smplx": importlib.metadata.version("smplx"),
    "lpips": importlib.metadata.version("lpips"),
    "pyopengl": importlib.metadata.version("PyOpenGL"),
    "pyrender": importlib.metadata.version("pyrender"),
    "chumpy": importlib.metadata.version("chumpy"),
    "mmcv": mmcv.__version__,
    "mmengine": mmengine.__version__,
    "mmdet": mmdet.__version__,
    "mmpose": mmpose.__version__,
    "pytorch3d_origin": pytorch3d.__file__,
    "cuda_smoke": True,
    "chumpy_smoke": True,
    "torchgeometry_smoke": True,
}
print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
'@
$probeRaw = Invoke-Wsl -Arguments @("/usr/bin/env", "PYTHONNOUSERSITE=1", $LinuxPython, "-c", $probeCode) -Capture
$probeLine = ($probeRaw | Select-Object -Last 1).ToString().Trim()
try { $probe = $probeLine | ConvertFrom-Json -Depth 20 }
catch { throw "ExAvatar environment probe did not return valid JSON: $probeLine" }

if ([string]$probe.torch -notlike "$torchVersion*") { throw "Unexpected Torch version: $($probe.torch)" }
if ([string]$probe.torchvision -notlike "$torchvisionVersion*") { throw "Unexpected torchvision version: $($probe.torchvision)" }
if ([string]$probe.torch_cuda -ne $expectedCudaVersion) { throw "Unexpected Torch CUDA runtime: $($probe.torch_cuda), expected $expectedCudaVersion" }
if ([string]$probe.numpy -ne $numpyVersion) { throw "Unexpected NumPy version: $($probe.numpy)" }
if ([string]$probe.scipy -ne $scipyVersion) { throw "Unexpected SciPy version: $($probe.scipy)" }
if ([string]$probe.pyopengl -ne $pyopenglVersion) { throw "Unexpected PyOpenGL version: $($probe.pyopengl)" }
if ([string]$probe.pyrender -ne "0.1.45") { throw "Unexpected pyrender version: $($probe.pyrender)" }
if ([string]$probe.chumpy -ne $chumpyVersion) { throw "Unexpected Chumpy version: $($probe.chumpy)" }
if ([string]$probe.mmcv -ne $mmcvVersion) { throw "Unexpected MMCV version: $($probe.mmcv)" }
if ([string]$probe.mmengine -ne $mmengineVersion) { throw "Unexpected MMEngine version: $($probe.mmengine)" }
if ([string]$probe.mmdet -ne $mmdetVersion) { throw "Unexpected MMDetection version: $($probe.mmdet)" }
if ([string]$probe.mmpose -ne $mmposeVersion) { throw "Unexpected MMPose version: $($probe.mmpose)" }
if ($probe.cuda_smoke -ne $true -or $probe.chumpy_smoke -ne $true -or $probe.torchgeometry_smoke -ne $true) {
    throw "ExAvatar runtime smoke did not pass."
}

$receiptCode = @'
import hashlib
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(sys.argv[2])
raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
payload["setup_sha256"] = hashlib.sha256(raw).hexdigest()
path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
'@
$setupReceipt = [ordered]@{
    format = "bodyrig-photoreal-exavatar-runtime-setup"
    version = 1
    distribution = $Distribution
    linux_python = $LinuxPython
    pytorch3d_commit = $pytorch3dCommit
    expected_cuda_version = $expectedCudaVersion
    requested_versions = [ordered]@{
        torch = $torchVersion
        torchvision = $torchvisionVersion
        numpy = $numpyVersion
        scipy = $scipyVersion
        opencv_python = $opencvVersion
        smplx = $smplxVersion
        lpips = $lpipsVersion
        pyopengl = $pyopenglVersion
        pyrender = "0.1.45"
        chumpy = $chumpyVersion
        mmcv = $mmcvVersion
        mmcv_commit = $mmcvCommit
        mmengine = $mmengineVersion
        mmdet = $mmdetVersion
        mmpose = $mmposeVersion
    }
    chumpy_patch = $chumpyPatch
    torchgeometry_patch = $torchgeometryPatch
    observed = $probe
    nvcc = @($nvcc | ForEach-Object { [string]$_ })
    nvidia_smi = @($nvidia | ForEach-Object { [string]$_ })
    photoreal_acceptance_authority = $false
    build_only = $true
    production_activation = $false
}
$setupJson = $setupReceipt | ConvertTo-Json -Depth 30 -Compress
Invoke-Wsl -Root -Arguments @($LinuxPython, "-c", $receiptCode, $receipt, $setupJson)

Write-Host ""
Write-Host "BodyRig ExAvatar WSL runtime: SETUP PASS"
Write-Host "Python:          $($probe.python)"
Write-Host "Torch:           $($probe.torch)"
Write-Host "CUDA:            $($probe.torch_cuda)"
Write-Host "GPU:             $($probe.gpu)"
Write-Host "PyTorch3D:       PINNED $pytorch3dCommit"
Write-Host "OpenMMLab:       MMCV $($probe.mmcv) / MMDet $($probe.mmdet) / MMPose $($probe.mmpose)"
Write-Host "PyOpenGL:        $($probe.pyopengl) / pyrender $($probe.pyrender)"
Write-Host "Chumpy:          $($probe.chumpy) PATCHED + SMOKE PASS"
Write-Host "torchgeometry:   PATCHED + SMOKE PASS"
Write-Host "Receipt:         $receipt"
Write-Host "Photoreal authority: FALSE"
Write-Host "Production:      FALSE"
