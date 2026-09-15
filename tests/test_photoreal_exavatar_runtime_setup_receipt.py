from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_runtime_setup_receipt as receipt


def _digest(value: dict[str, object], omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _runtime(tmp_path: Path) -> Path:
    root = tmp_path / "bodyrig-exavatar"
    python = root / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"python-placeholder")
    value: dict[str, object] = {
        "format": receipt.FORMAT,
        "version": receipt.VERSION,
        "distribution": "Ubuntu-22.04",
        "linux_python": str(python.resolve()),
        "pytorch3d_commit": receipt.PYTORCH3D_COMMIT,
        "requested_versions": dict(receipt.EXPECTED_REQUESTED_VERSIONS),
        "chumpy_patch": {
            "path": "/opt/bodyrig-exavatar/lib/python3.10/site-packages/chumpy/__init__.py",
            "before_sha256": "a" * 64,
            "sha256": "b" * 64,
            "patch": receipt.CHUMPY_PATCH,
        },
        "torchgeometry_patch": {
            "path": "/opt/bodyrig-exavatar/lib/python3.10/site-packages/torchgeometry/core/conversions.py",
            "sha256": "c" * 64,
            "patch": receipt.TORCHGEOMETRY_PATCH,
        },
        "observed": {
            "chumpy": "0.70",
            "cuda_smoke": True,
            "chumpy_smoke": True,
            "torchgeometry_smoke": True,
        },
        "nvcc": ["Cuda compilation tools, release 12.4"],
        "nvidia_smi": ["NVIDIA GeForce RTX 3060, driver, 12288 MiB"],
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }
    value["setup_sha256"] = _digest(value, "setup_sha256")
    (root / "bodyrig-exavatar-runtime-setup.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return python


def test_runtime_setup_receipt_accepts_exact_pinned_provenance(tmp_path: Path) -> None:
    python = _runtime(tmp_path)
    result = receipt.validate_runtime_setup_receipt(linux_python=python)

    assert result["pytorch3d_commit"] == receipt.PYTORCH3D_COMMIT
    assert result["requested_versions"]["chumpy"] == "0.70"
    assert result["chumpy_patch"]["patch"] == receipt.CHUMPY_PATCH
    assert result["torchgeometry_patch"]["patch"] == receipt.TORCHGEOMETRY_PATCH
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False


def test_runtime_setup_receipt_rejects_changed_version_set(tmp_path: Path) -> None:
    python = _runtime(tmp_path)
    path = python.parent.parent / "bodyrig-exavatar-runtime-setup.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["requested_versions"]["chumpy"] = "0.71"
    value["setup_sha256"] = _digest(value, "setup_sha256")
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError, match="requested-version set mismatch"):
        receipt.validate_runtime_setup_receipt(linux_python=python)


def test_runtime_setup_receipt_rejects_wrong_patch_identity(tmp_path: Path) -> None:
    python = _runtime(tmp_path)
    path = python.parent.parent / "bodyrig-exavatar-runtime-setup.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["chumpy_patch"]["patch"] = "unknown"
    value["setup_sha256"] = _digest(value, "setup_sha256")
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError, match="Chumpy patch identity mismatch"):
        receipt.validate_runtime_setup_receipt(linux_python=python)


def test_runtime_setup_receipt_rejects_digest_tampering(tmp_path: Path) -> None:
    python = _runtime(tmp_path)
    path = python.parent.parent / "bodyrig-exavatar-runtime-setup.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["observed"]["chumpy"] = "tampered"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError):
        receipt.validate_runtime_setup_receipt(linux_python=python)
