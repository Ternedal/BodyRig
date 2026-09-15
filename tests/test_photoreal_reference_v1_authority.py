from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from bodyrig import photoreal_reference_vision_config as vision_config
from bodyrig import photoreal_reference_vision_preflight as preflight

MMPOSE_REVISION = "759b39c13fea6ba094afc1fa932f51dc1b11cbf9"
MMDET_REVISION = "fe3f809a0a514189baf889aa358c498d51ee36cd"
MODEL_SET_SHA = "c" * 64


def _runtime_root(tmp_path: Path, version: object) -> Path:
    root = tmp_path / "models"
    root.mkdir()
    (root / "runtime-environment.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-photoreal-reference-runtime-environment",
                "version": version,
                "distribution": "Ubuntu-22.04",
                "linux_python": "/opt/bodyrig-photoreal/bin/python",
                "mmpose_revision": MMPOSE_REVISION,
                "mmdetection_revision": MMDET_REVISION,
                "observed": {
                    "torch_cuda_available": True,
                    "onnxruntime_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
                },
                "build_only": True,
                "production_activation": False,
            },
            allow_nan=True,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return root


@pytest.mark.parametrize("version", [True, False, "1", None, [], {}, 2, float("nan"), float("inf")])
def test_runtime_receipt_rejects_non_numeric_v1_at_point_of_use(tmp_path: Path, version: object) -> None:
    root = _runtime_root(tmp_path, version)
    with pytest.raises(vision_config.PhotorealReferenceVisionConfigError, match="numeric v1"):
        vision_config._validate_runtime_receipt(
            root,
            distribution="Ubuntu-22.04",
            linux_python="/opt/bodyrig-photoreal/bin/python",
            device="cuda:0",
        )


@pytest.mark.parametrize("version", [1, 1.0])
def test_runtime_receipt_preserves_numeric_v1_compatibility(tmp_path: Path, version: object) -> None:
    root = _runtime_root(tmp_path, version)
    receipt = vision_config._validate_runtime_receipt(
        root,
        distribution="Ubuntu-22.04",
        linux_python="/opt/bodyrig-photoreal/bin/python",
        device="cuda:0",
    )
    assert receipt["version"] == 1


def _probe_fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    adapter = tmp_path / "adapter.py"
    probe = tmp_path / "probe.py"
    root = tmp_path / "models"
    adapter.write_text("# adapter\n", encoding="utf-8")
    probe.write_text("# probe\n", encoding="utf-8")
    root.mkdir()
    return adapter, probe, root, hashlib.sha256(adapter.read_bytes()).hexdigest()


def _probe_result(revision: str, version: object) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-reference-vision-probe",
        "version": version,
        "adapter_revision": revision,
        "model_set_sha256": MODEL_SET_SHA,
        "device": "cuda:0",
        "identity_embedding_dimension": 512,
        "face_inference_executed": True,
        "pose_inference_executed": True,
        "synthetic_face_count": 0,
        "synthetic_pose_count": 0,
        "synthetic_frame_sha256": "a" * 64,
        "synthetic_perceptual_hash": "0123456789abcdef",
        "source_media_accessed": False,
        "identity_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def _patch_probe(monkeypatch: pytest.MonkeyPatch, result: dict[str, object]) -> None:
    monkeypatch.setattr(preflight, "build_model_set", lambda _root: {"model_set_sha256": MODEL_SET_SHA})
    monkeypatch.setattr(preflight, "make_wsl_path_converter", lambda _exe, _distribution: lambda path: f"/wsl/{Path(path).name}")
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(result, allow_nan=True) + "\n", stderr=""),
    )


@pytest.mark.parametrize("version", [True, False, "1", None, [], {}, 2, float("nan"), float("inf")])
def test_preflight_probe_rejects_non_numeric_v1_at_point_of_use(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, version: object
) -> None:
    adapter, probe, root, revision = _probe_fixture(tmp_path)
    _patch_probe(monkeypatch, _probe_result(revision, version))
    with pytest.raises(preflight.PhotorealReferenceVisionPreflightError, match="numeric v1"):
        preflight.run_reference_vision_preflight(
            adapter_path=adapter,
            probe_path=probe,
            model_root=root,
            distribution="Ubuntu-22.04",
            linux_python="/opt/bodyrig-photoreal/bin/python",
            device="cuda:0",
        )


@pytest.mark.parametrize("version", [1, 1.0])
def test_preflight_probe_preserves_numeric_v1_compatibility(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, version: object
) -> None:
    adapter, probe, root, revision = _probe_fixture(tmp_path)
    _patch_probe(monkeypatch, _probe_result(revision, version))
    result = preflight.run_reference_vision_preflight(
        adapter_path=adapter,
        probe_path=probe,
        model_root=root,
        distribution="Ubuntu-22.04",
        linux_python="/opt/bodyrig-photoreal/bin/python",
        device="cuda:0",
    )
    assert result["version"] == 1


@pytest.mark.parametrize(
    ("version", "expected"),
    [(True, False), (False, False), ("1", False), (None, False), ([], False), ({}, False), (2, False), (1, True), (1.0, True)],
)
def test_one_command_powershell_numeric_v1_gate(tmp_path: Path, version: object, expected: bool) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is not available on this runner")

    entrypoint = Path(__file__).resolve().parents[1] / "start-photoreal-v2-reference.ps1"
    source = entrypoint.read_text(encoding="utf-8")
    assert "Test-NumericV1 -Value $receipt.version" in source
    assert "[int]$receipt.version" not in source

    harness = tmp_path / "numeric-v1-harness.ps1"
    harness.write_text(
        """param([string]$Entrypoint,[string]$Json)
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Entrypoint, [ref]$tokens, [ref]$errors)
$fn = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-NumericV1' }, $true) | Select-Object -First 1
if ($null -eq $fn) { exit 3 }
Invoke-Expression $fn.Extent.Text
$value = ($Json | ConvertFrom-Json -Depth 20).version
if (Test-NumericV1 -Value $value) { exit 0 }
exit 1
""",
        encoding="utf-8",
    )
    payload = json.dumps({"version": version}, allow_nan=False, separators=(",", ":"))
    completed = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-File", str(harness), str(entrypoint), payload],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.returncode == (0 if expected else 1), completed.stderr
