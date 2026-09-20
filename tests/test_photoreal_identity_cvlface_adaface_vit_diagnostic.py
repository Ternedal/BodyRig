from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "photoreal_identity_cvlface_adaface_vit_diagnostic.py"
SPEC = importlib.util.spec_from_file_location(
    "bodyrig_photoreal_identity_cvlface_adaface_vit_diagnostic_test",
    TOOL,
)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnostic
SPEC.loader.exec_module(diagnostic)


def _provenance() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-cvlface-diagnostic-provenance",
        "version": 1,
        "repo_id": "minchul/cvlface_adaface_vit_base_webface4m",
        "repo_revision": "b95848ffb6cfbcdba67a4e24adf3c0b91518d7e3",
        "model_file": "model/model.safetensors",
        "model_sha256": (
            "5fafd6b7d599a3ede5fac5bd1d01ad05"
            "e9e93e89b39b7687d4a3bc93ff2aebc0"
        ),
        "architecture": "ViT-Base",
        "training_loss": "AdaFace",
        "training_dataset": "WebFace4M",
        "embedding_dimension": 512,
        "input_size": 112,
        "color_space": "RGB",
        "normalization": "ToTensor; mean=0.5,std=0.5 per RGB channel",
        "training_dataset_license_requires_operator_review": True,
        "reuses_bodyrig_photoreal_torch": True,
        "parallel_torch_install": False,
        "runtime_dependency_profile": "cvlface-vit-runtime-v2",
        "fvcore": "0.1.5.post20221221",
        "timm": "0.9.7",
        "model_cuda_smoke_test": True,
        "diagnostic_only": True,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def test_cvlface_provenance_is_pinned_and_authority_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "model.safetensors").write_bytes(b"model")
    (tmp_path / "model" / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "model" / "wrapper.py").write_text("", encoding="utf-8")
    (tmp_path / "source-provenance.json").write_text(
        json.dumps(_provenance()),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        diagnostic,
        "_sha256_file",
        lambda _path: diagnostic.MODEL_SHA256,
    )

    provenance = diagnostic._validate_provenance(tmp_path)

    assert provenance["repo_revision"] == diagnostic.MODEL_REVISION
    assert provenance["reuses_bodyrig_photoreal_torch"] is True
    assert provenance["parallel_torch_install"] is False
    assert provenance["runtime_dependency_profile"] == "cvlface-vit-runtime-v2"
    assert provenance["fvcore"] == "0.1.5.post20221221"
    assert provenance["timm"] == "0.9.7"
    assert provenance["model_cuda_smoke_test"] is True
    assert provenance["diagnostic_only"] is True
    assert provenance["production_activation"] is False

    bad = _provenance()
    bad["identity_matching_authorized"] = True
    (tmp_path / "source-provenance.json").write_text(
        json.dumps(bad),
        encoding="utf-8",
    )
    with pytest.raises(
        diagnostic.PhotorealIdentityCvlFaceDiagnosticError,
        match="identity_matching_authorized",
    ):
        diagnostic._validate_provenance(tmp_path)


def test_cvlface_model_identity_is_exact() -> None:
    assert diagnostic.MODEL_REPO == (
        "minchul/cvlface_adaface_vit_base_webface4m"
    )
    assert diagnostic.MODEL_REVISION == (
        "b95848ffb6cfbcdba67a4e24adf3c0b91518d7e3"
    )
    assert diagnostic.MODEL_SHA256 == (
        "5fafd6b7d599a3ede5fac5bd1d01ad05"
        "e9e93e89b39b7687d4a3bc93ff2aebc0"
    )
    assert diagnostic.MODEL_DIMENSION == 512
    assert diagnostic.MODEL_INPUT_SIZE == 112


def test_normalize_rejects_wrong_dimension() -> None:
    with pytest.raises(
        diagnostic.PhotorealIdentityCvlFaceDiagnosticError,
        match="dimension mismatch",
    ):
        diagnostic._normalize(
            [1.0, 0.0],
            dimension=512,
            label="test",
        )
