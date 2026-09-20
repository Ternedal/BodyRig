from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from bodyrig import photoreal_identity_group_review as review


FORMAT = "bodyrig-photoreal-identity-cvlface-adaface-vit-diagnostic"
VERSION = 1
PROVENANCE_FORMAT = "bodyrig-photoreal-cvlface-diagnostic-provenance"
MODEL_REPO = "minchul/cvlface_adaface_vit_base_webface4m"
MODEL_REVISION = "b95848ffb6cfbcdba67a4e24adf3c0b91518d7e3"
MODEL_FILE = "model/model.safetensors"
MODEL_SHA256 = "5fafd6b7d599a3ede5fac5bd1d01ad05e9e93e89b39b7687d4a3bc93ff2aebc0"
MODEL_DIMENSION = 512
MODEL_INPUT_SIZE = 112


class PhotorealIdentityCvlFaceDiagnosticError(RuntimeError):
    pass


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            f"could not load diagnostic dependency: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotorealIdentityCvlFaceDiagnosticError(
            f"required file is missing: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            f"{label} is unreadable: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityCvlFaceDiagnosticError(
            f"{label} must be a JSON object"
        )
    return value


def _normalize(vector: Any, *, dimension: int, label: str) -> list[float]:
    if hasattr(vector, "detach"):
        vector = vector.detach()
    if hasattr(vector, "float"):
        vector = vector.float()
    if hasattr(vector, "cpu"):
        vector = vector.cpu()
    if hasattr(vector, "reshape") and hasattr(vector, "tolist"):
        vector = vector.reshape(-1).tolist()
    if not isinstance(vector, (list, tuple)) or len(vector) != dimension:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            f"{label} dimension mismatch"
        )
    try:
        values = [float(item) for item in vector]
    except (TypeError, ValueError, OverflowError) as exc:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            f"{label} contains invalid values"
        ) from exc
    if any(not math.isfinite(item) for item in values):
        raise PhotorealIdentityCvlFaceDiagnosticError(
            f"{label} contains non-finite values"
        )
    norm = math.sqrt(sum(item * item for item in values))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise PhotorealIdentityCvlFaceDiagnosticError(
            f"{label} has invalid norm"
        )
    return [item / norm for item in values]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "embedding dimensions are inconsistent"
        )
    return max(
        -1.0,
        min(1.0, sum(a * b for a, b in zip(left, right, strict=True))),
    )


def _validate_provenance(root: Path) -> dict[str, Any]:
    provenance = _read_json(
        root / "source-provenance.json",
        label="CVLFace diagnostic provenance",
    )
    expected = {
        "format": PROVENANCE_FORMAT,
        "version": VERSION,
        "repo_id": MODEL_REPO,
        "repo_revision": MODEL_REVISION,
        "model_file": MODEL_FILE,
        "model_sha256": MODEL_SHA256,
        "architecture": "ViT-Base",
        "training_loss": "AdaFace",
        "training_dataset": "WebFace4M",
        "embedding_dimension": MODEL_DIMENSION,
        "input_size": MODEL_INPUT_SIZE,
        "color_space": "RGB",
        "normalization": "ToTensor; mean=0.5,std=0.5 per RGB channel",
        "training_dataset_license_requires_operator_review": True,
        "reuses_bodyrig_photoreal_torch": True,
        "parallel_torch_install": False,
        "diagnostic_only": True,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    for key, value in expected.items():
        if provenance.get(key) != value:
            raise PhotorealIdentityCvlFaceDiagnosticError(
                f"CVLFace diagnostic provenance mismatch: {key}"
            )
    observed = _sha256_file(root / MODEL_FILE)
    if observed != MODEL_SHA256:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "CVLFace model.safetensors SHA-256 mismatch"
        )
    if not (root / "model" / "config.json").is_file():
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "CVLFace local model config is missing"
        )
    if not (root / "model" / "wrapper.py").is_file():
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "CVLFace local model wrapper is missing"
        )
    return provenance


def _load_cvlface(root: Path, *, device: str):
    normalized = device.strip().lower()
    if normalized not in {"cpu", "cuda", "cuda:0"}:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "--device must be cpu, cuda or cuda:0"
        )
    dependency_root = root / "python"
    model_root = root / "model"
    if not dependency_root.is_dir():
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "CVLFace diagnostic dependency root is missing"
        )
    sys.path.insert(0, str(dependency_root))
    try:
        import torch
        from transformers import AutoModel
    except Exception as exc:  # noqa: BLE001
        raise PhotorealIdentityCvlFaceDiagnosticError(
            f"CVLFace diagnostic dependencies unavailable: {exc}"
        ) from exc

    if normalized != "cpu" and not torch.cuda.is_available():
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "CVLFace diagnostic requested CUDA but torch.cuda is unavailable"
        )
    torch_device = torch.device("cpu" if normalized == "cpu" else "cuda:0")
    cwd = os.getcwd()
    sys.path.insert(0, str(model_root))
    try:
        os.chdir(model_root)
        model = AutoModel.from_pretrained(
            str(model_root),
            trust_remote_code=True,
            local_files_only=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise PhotorealIdentityCvlFaceDiagnosticError(
            f"CVLFace model initialization failed: {exc}"
        ) from exc
    finally:
        os.chdir(cwd)
        with contextlib.suppress(ValueError):
            sys.path.remove(str(model_root))
    model.eval()
    model.to(torch_device)
    return model, torch, torch_device


def _cvlface_embedding(
    *,
    model: Any,
    torch: Any,
    torch_device: Any,
    aligned_bgr: Any,
) -> list[float]:
    try:
        rgb = aligned_bgr[:, :, ::-1].copy()
        tensor = torch.from_numpy(rgb).permute(2, 0, 1).float()
        tensor = tensor.div(255.0).sub(0.5).div(0.5).unsqueeze(0)
        tensor = tensor.to(torch_device)
        with torch.inference_mode():
            output = model(tensor)
        if isinstance(output, (list, tuple)):
            if not output:
                raise RuntimeError("model returned empty tuple/list")
            output = output[0]
        if hasattr(output, "last_hidden_state"):
            output = output.last_hidden_state
        return _normalize(
            output,
            dimension=MODEL_DIMENSION,
            label="CVLFace AdaFace ViT embedding",
        )
    except PhotorealIdentityCvlFaceDiagnosticError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PhotorealIdentityCvlFaceDiagnosticError(
            f"CVLFace AdaFace ViT inference failed: {exc}"
        ) from exc


def _measure(
    *,
    adapter: Any,
    runtime: Any,
    representation: Any,
    model: Any,
    torch: Any,
    torch_device: Any,
    image: Any,
    dimension: int,
) -> tuple[list[float], list[float], dict[str, Any]]:
    current, quality = representation._single_face_measurement(
        adapter=adapter,
        runtime=runtime,
        image=image,
    )
    if current is None:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "accepted frame no longer replays as one identity"
        )
    candidates = adapter._candidates(runtime, image)
    faces = [item.get("face") for item in candidates if item.get("face") is not None]
    if len(candidates) != 1 or len(faces) != 1:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "accepted frame did not reproduce exactly one face"
        )
    face = faces[0]
    landmarks = getattr(face, "kps", None)
    if landmarks is None:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "accepted frame has no five-point landmarks"
        )
    current_models = getattr(runtime.face_app, "models", None)
    current_recognizer = (
        current_models.get("recognition")
        if isinstance(current_models, Mapping)
        else None
    )
    if current_recognizer is None:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "current recognition model is unavailable"
        )
    try:
        from insightface.utils import face_align

        aligned = face_align.norm_crop(
            image,
            landmark=landmarks,
            image_size=MODEL_INPUT_SIZE,
        )
        aligned = runtime.np.ascontiguousarray(aligned)
        current_direct = _normalize(
            current_recognizer.get_feat(aligned),
            dimension=dimension,
            label="current direct recognition embedding",
        )
        alternate = _cvlface_embedding(
            model=model,
            torch=torch,
            torch_device=torch_device,
            aligned_bgr=aligned,
        )
    except PhotorealIdentityCvlFaceDiagnosticError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PhotorealIdentityCvlFaceDiagnosticError(
            f"aligned recognizer replay failed: {exc}"
        ) from exc
    replay = _cosine(current, current_direct)
    if replay < 0.999999:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "current direct aligned replay does not match FaceAnalysis embedding"
        )
    return current, alternate, {
        "current_direct_replay_cosine": round(replay, 9),
        "quality": quality,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare BodyRig's pinned w600k_r50 representation with an official "
            "CVLFace AdaFace ViT-Base@WebFace4M model on the exact same aligned "
            "human-attested positive and persisted negative evidence."
        )
    )
    parser.add_argument("--identity-bank", type=Path, required=True)
    parser.add_argument("--identity-request", type=Path, required=True)
    parser.add_argument("--identity-request-origin", type=Path, required=True)
    parser.add_argument("--calibration-request", type=Path, required=True)
    parser.add_argument("--calibration-request-origin", type=Path, required=True)
    parser.add_argument("--negative-observations", type=Path, required=True)
    parser.add_argument("--review-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--cvlface-root", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.out.expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityCvlFaceDiagnosticError(
            f"diagnostic output already exists: {output}"
        )
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    ab = _load_module(
        repo_root / "tools" / "photoreal_identity_recognizer_ab_diagnostic.py",
        "bodyrig_cvlface_ab_dependency",
    )
    flip = _load_module(
        repo_root / "tools" / "photoreal_identity_flip_tta_diagnostic.py",
        "bodyrig_cvlface_flip_dependency",
    )
    representation = flip._load_representation_tool(repo_root)
    adapter = representation._load_adapter(repo_root)
    adapter_revision = adapter._self_revision()

    bank_path = args.identity_bank.expanduser().resolve()
    bank = ab._read_json(bank_path, label="identity bank")
    performer_id, bank_sha = review._validate_bank(
        bank,
        adapter_revision=adapter_revision,
    )
    dimension = bank.get("embedding_dimension")
    if dimension != MODEL_DIMENSION:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "diagnostic requires a 512-dimensional identity bank"
        )

    identity_request = ab._read_json(
        args.identity_request.expanduser().resolve(),
        label="Stage-7 identity execution request",
    )
    identity_request_origin = ab._read_json(
        args.identity_request_origin.expanduser().resolve(),
        label="Stage-7 identity original request",
    )
    representation._request_transport_equivalent(
        identity_request_origin,
        identity_request,
    )
    identity_sources = review._validate_request(
        identity_request,
        performer_id=performer_id,
        bank=bank,
        adapter_revision=adapter_revision,
    )
    attestation = representation._validate_attestation(
        review_root=args.review_root.expanduser().resolve(),
        bank=bank,
    )

    calibration_request = ab._read_json(
        args.calibration_request.expanduser().resolve(),
        label="Stage-13 calibration execution request",
    )
    calibration_request_origin = ab._read_json(
        args.calibration_request_origin.expanduser().resolve(),
        label="Stage-13 calibration original request",
    )
    representation._request_transport_equivalent(
        calibration_request_origin,
        calibration_request,
    )
    calibration_sources = flip._validate_calibration_request(
        calibration_request,
        performer_id=performer_id,
        bank=bank,
        adapter_revision=adapter_revision,
    )
    negative_document = ab._read_json(
        args.negative_observations.expanduser().resolve(),
        label="identity negative observations",
    )
    negatives = flip._validate_negative_observations(
        negative_document,
        performer_id=performer_id,
        bank=bank,
        adapter_revision=adapter_revision,
        sources=calibration_sources,
        dimension=dimension,
    )

    model_root = args.model_root.expanduser().resolve()
    model_set = adapter.build_model_set(model_root)
    if flip._sha(
        model_set.get("model_set_sha256"),
        label="runtime model-set SHA-256",
    ) != flip._sha(
        bank.get("model_set_sha256"),
        label="identity bank model-set SHA-256",
    ):
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "current model root does not match identity bank model set"
        )
    manifest = adapter._load_model_manifest(model_root)
    runtime = adapter._load_runtime(manifest, device=args.device)

    cvlface_root = args.cvlface_root.expanduser().resolve()
    provenance = _validate_provenance(cvlface_root)
    cvlface_model, torch, torch_device = _load_cvlface(
        cvlface_root,
        device=args.device,
    )

    references = bank.get("references")
    if not isinstance(references, list) or not references:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "identity bank contains no references"
        )

    positive_variants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    negative_variants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    positive_rows: list[dict[str, Any]] = []
    negative_rows: list[dict[str, Any]] = []

    for index, raw in enumerate(references):
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityCvlFaceDiagnosticError(
                "identity bank reference is invalid"
            )
        source_key = str(raw.get("source_key") or "").strip()
        source = identity_sources.get(source_key)
        if source is None:
            raise PhotorealIdentityCvlFaceDiagnosticError(
                f"reference source absent from Stage-7 request: {source_key}"
            )
        sample = flip._find_sample(
            source,
            field="reference_samples",
            timestamp=raw.get("timestamp_seconds"),
            eye=raw.get("eye"),
        )
        expected_sha = flip._sha(
            raw.get("frame_sha256"),
            label="identity bank frame SHA-256",
        )
        image, _viewport_id, _viewport, _eye_image, _spatial = (
            representation._match_exact_viewport(
                adapter=adapter,
                runtime=runtime,
                source=source,
                sample=sample,
                expected_frame_sha=expected_sha,
            )
        )
        current, cvlface, replay = _measure(
            adapter=adapter,
            runtime=runtime,
            representation=representation,
            model=cvlface_model,
            torch=torch,
            torch_device=torch_device,
            image=image,
            dimension=dimension,
        )
        stored = _normalize(
            raw.get("embedding"),
            dimension=dimension,
            label=f"identity bank embedding[{index}]",
        )
        if _cosine(current, stored) < 0.999999:
            raise PhotorealIdentityCvlFaceDiagnosticError(
                "current replay does not match persisted bank embedding"
            )
        group_id = str(raw.get("group_id") or "").strip()
        if not group_id:
            raise PhotorealIdentityCvlFaceDiagnosticError(
                "identity bank reference lacks group id"
            )
        positive_variants["bank-w600k-r50"].append(
            {"group_id": group_id, "embedding": stored}
        )
        positive_variants["cvlface-adaface-vit-base-webface4m"].append(
            {"group_id": group_id, "embedding": cvlface}
        )
        positive_rows.append(
            {
                "reference_index": index,
                "group_id": group_id,
                "frame_sha256": expected_sha,
                "current_replay_cosine": replay["current_direct_replay_cosine"],
            }
        )

    for index, raw in enumerate(negatives):
        source_key = str(raw.get("source_key") or "").strip()
        source = calibration_sources.get(source_key)
        if source is None:
            raise PhotorealIdentityCvlFaceDiagnosticError(
                f"negative source absent from Stage-13 request: {source_key}"
            )
        sample = flip._find_sample(
            source,
            field="negative_samples",
            timestamp=raw.get("timestamp_seconds"),
            eye=raw.get("eye"),
        )
        expected_sha = flip._sha(
            raw.get("frame_sha256"),
            label="negative frame SHA-256",
        )
        image, _viewport_id, _viewport, _eye_image, _spatial = (
            representation._match_exact_viewport(
                adapter=adapter,
                runtime=runtime,
                source=source,
                sample=sample,
                expected_frame_sha=expected_sha,
            )
        )
        current, cvlface, replay = _measure(
            adapter=adapter,
            runtime=runtime,
            representation=representation,
            model=cvlface_model,
            torch=torch,
            torch_device=torch_device,
            image=image,
            dimension=dimension,
        )
        stored = _normalize(
            raw.get("embedding"),
            dimension=dimension,
            label=f"negative embedding[{index}]",
        )
        if _cosine(current, stored) < 0.999999:
            raise PhotorealIdentityCvlFaceDiagnosticError(
                "current negative replay does not match persisted embedding"
            )
        subject = str(raw.get("subject_performer_id") or "").strip()
        negative_variants["bank-w600k-r50"].append(
            {
                "negative_index": index,
                "subject_performer_id": subject,
                "embedding": stored,
            }
        )
        negative_variants["cvlface-adaface-vit-base-webface4m"].append(
            {
                "negative_index": index,
                "subject_performer_id": subject,
                "embedding": cvlface,
            }
        )
        negative_rows.append(
            {
                "negative_index": index,
                "subject_performer_id": subject,
                "frame_sha256": expected_sha,
                "current_replay_cosine": replay["current_direct_replay_cosine"],
            }
        )

    accepted = sorted(str(value) for value in attestation["accepted_group_ids"])
    observed = sorted(
        {str(item["group_id"]) for item in positive_variants["bank-w600k-r50"]}
    )
    if accepted != observed:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "human-attested group set differs from replayed positive groups"
        )

    variants: dict[str, Any] = {}
    for name in ("bank-w600k-r50", "cvlface-adaface-vit-base-webface4m"):
        positives = positive_variants[name]
        negatives_for_variant = negative_variants[name]
        if len(positives) != len(references):
            raise PhotorealIdentityCvlFaceDiagnosticError(
                f"{name} positive coverage is incomplete"
            )
        if len(negatives_for_variant) != len(negatives):
            raise PhotorealIdentityCvlFaceDiagnosticError(
                f"{name} negative coverage is incomplete"
            )
        variants[name] = {
            "positive_reference_coverage": 1.0,
            "negative_observation_coverage": 1.0,
            "positive_reference_count": len(positives),
            "positive_group_count": len(observed),
            "negative_observation_count": len(negatives_for_variant),
            "scoring_models": flip._score_models(
                positives,
                negatives_for_variant,
            ),
            "diagnostic_only": True,
        }

    bodyrig_revision = os.environ.get("BODYRIG_REVISION", "").strip()
    if len(bodyrig_revision) != 40:
        raise PhotorealIdentityCvlFaceDiagnosticError(
            "BODYRIG_REVISION must be the exact 40-character Git HEAD"
        )

    result = {
        "format": FORMAT,
        "version": VERSION,
        "bodyrig_revision": bodyrig_revision,
        "performer_id": performer_id,
        "identity_bank_sha256": bank_sha,
        "positive_reference_count": len(references),
        "human_attested_group_count": len(observed),
        "negative_observation_count": len(negatives),
        "cvlface_provenance": provenance,
        "variants": variants,
        "positive_replay": positive_rows,
        "negative_replay": negative_rows,
        "training_dataset_license_requires_operator_review": True,
        "negative_observation_count_below_production_minimum": len(negatives) < 8,
        "diagnostic_only": True,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
