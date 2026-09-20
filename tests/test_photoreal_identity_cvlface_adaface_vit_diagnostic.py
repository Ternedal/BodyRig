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


def test_persisted_negative_replay_uses_validated_stage13_samples() -> None:
    source = TOOL.read_text(encoding="utf-8")
    negative_loop = source.split(
        "    for item in negatives:",
        1,
    )[1].split(
        "    accepted = sorted",
        1,
    )[0]

    assert 'field="samples"' in negative_loop
    assert 'field="negative_samples"' not in negative_loop
    assert 'source = item["source"]' in negative_loop
    assert 'image, spatial = adapter._read_sample(runtime, source, sample)' in negative_loop
    assert 'stored = item["stored_embedding"]' in negative_loop
    assert 'adapter._frame_sha(image) != item["frame_sha256"]' in negative_loop


def _unit(*values: float) -> list[float]:
    vector = [0.0] * diagnostic.MODEL_DIMENSION
    for index, value in enumerate(values):
        vector[index] = value
    norm = sum(value * value for value in vector) ** 0.5
    return [value / norm for value in vector]


def test_positive_subspace_selection_is_independent_of_negatives() -> None:
    np = pytest.importorskip("numpy")
    positives = [
        {"reference_index": 0, "group_id": "scene:1", "embedding": _unit(1.0, 0.00, 0.00)},
        {"reference_index": 1, "group_id": "scene:2", "embedding": _unit(0.98, 0.20, 0.00)},
        {"reference_index": 2, "group_id": "scene:3", "embedding": _unit(0.95, -0.25, 0.00)},
        {"reference_index": 3, "group_id": "scene:4", "embedding": _unit(0.92, 0.35, 0.00)},
        {"reference_index": 4, "group_id": "scene:5", "embedding": _unit(0.90, -0.40, 0.00)},
    ]
    negatives_a = [
        {"negative_index": 0, "subject_performer_id": "99", "embedding": _unit(0.0, 0.0, 1.0)}
    ]
    negatives_b = [
        {"negative_index": 0, "subject_performer_id": "99", "embedding": _unit(0.7, 0.7, 0.1)},
        {"negative_index": 1, "subject_performer_id": "100", "embedding": _unit(-0.2, 0.1, 0.97)},
    ]

    first = diagnostic._positive_only_subspace_diagnostic(
        np=np,
        positives=positives,
        negatives=negatives_a,
        variance_target=0.95,
    )
    second = diagnostic._positive_only_subspace_diagnostic(
        np=np,
        positives=positives,
        negatives=negatives_b,
        variance_target=0.95,
    )

    assert first["final_rank"] == second["final_rank"]
    assert first["fold_ranks"] == second["fold_ranks"]
    assert first["final_explained_variance"] == second["final_explained_variance"]
    assert first["positive_model_selection_only"] is True
    assert first["negative_evidence_used_for_selection"] is False
    assert first["positive_score_count"] == len(positives)
    assert first["negative_score_count"] == len(negatives_a)
    assert second["negative_score_count"] == len(negatives_b)
    assert first["all_positive_references_retained"] is True
    assert first["all_positive_groups_retained"] is True
    assert first["all_negative_observations_retained"] is True


def test_positive_subspace_fit_uses_smallest_rank_reaching_target() -> None:
    np = pytest.importorskip("numpy")
    centroids = [
        _unit(1.0, 0.00, 0.0),
        _unit(0.98, 0.20, 0.0),
        _unit(0.96, -0.28, 0.0),
        _unit(0.94, 0.34, 0.0),
    ]
    model = diagnostic._fit_positive_subspace(
        np=np,
        group_centroids=centroids,
        variance_target=0.95,
    )

    assert 1 <= model["rank"] <= 3
    assert model["explained_variance"] >= 0.95
