from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from bodyrig import photoreal_identity_group_review as review


FORMAT = "bodyrig-photoreal-identity-recognizer-ab-diagnostic"
VERSION = 1
PROVENANCE_FORMAT = "bodyrig-photoreal-diagnostic-recognizer-provenance"
ALTERNATE_PACKAGE = "antelopev2"
ALTERNATE_RECOGNIZER_FILE = "glintr100.onnx"
ALTERNATE_ARCHIVE_SHA256 = "8e182f14fc6e80b3bfa375b33eb6cff7ee05d8ef7633e738d1c89021dcf0c5c5"
ALTERNATE_RECOGNIZER_SHA256 = "4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf"
ALTERNATE_ARCHIVE_URL = (
    "https://github.com/deepinsight/insightface/releases/download/model-zoo/"
    "antelopev2.zip"
)


class PhotorealIdentityRecognizerAbDiagnosticError(RuntimeError):
    pass


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            f"could not load diagnostic dependency: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256_file(path: Path) -> str:
    import hashlib

    if not path.is_file():
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            f"required file is missing: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            f"{label} is unreadable: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            f"{label} must be a JSON object"
        )
    return value


def _normalize(vector: Any, *, dimension: int, label: str) -> list[float]:
    if hasattr(vector, "reshape") and hasattr(vector, "tolist"):
        vector = vector.reshape(-1).tolist()
    if not isinstance(vector, (list, tuple)) or len(vector) != dimension:
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            f"{label} dimension mismatch"
        )
    try:
        values = [float(item) for item in vector]
    except (TypeError, ValueError, OverflowError) as exc:
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            f"{label} contains invalid values"
        ) from exc
    if any(not math.isfinite(item) for item in values):
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            f"{label} contains non-finite values"
        )
    norm = math.sqrt(sum(item * item for item in values))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            f"{label} has invalid norm"
        )
    return [item / norm for item in values]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "embedding dimensions are inconsistent"
        )
    return max(
        -1.0,
        min(1.0, sum(a * b for a, b in zip(left, right, strict=True))),
    )


def _validate_alternate_provenance(
    *,
    root: Path,
) -> tuple[Path, dict[str, Any]]:
    recognizer_path = root / ALTERNATE_RECOGNIZER_FILE
    provenance_path = root / "source-provenance.json"
    provenance = _read_json(
        provenance_path,
        label="diagnostic recognizer provenance",
    )
    if (
        provenance.get("format") != PROVENANCE_FORMAT
        or provenance.get("version") != VERSION
    ):
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "diagnostic recognizer provenance format/version mismatch"
        )
    exact = {
        "package": ALTERNATE_PACKAGE,
        "archive_url": ALTERNATE_ARCHIVE_URL,
        "archive_sha256": ALTERNATE_ARCHIVE_SHA256,
        "recognizer_file": ALTERNATE_RECOGNIZER_FILE,
        "recognizer_sha256": ALTERNATE_RECOGNIZER_SHA256,
        "embedding_dimension": 512,
        "input_size": 112,
        "preprocessing": "insightface-arcface-1",
        "license_operator_accepted": True,
        "diagnostic_only": True,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    for key, expected in exact.items():
        if provenance.get(key) != expected:
            raise PhotorealIdentityRecognizerAbDiagnosticError(
                f"diagnostic recognizer provenance mismatch: {key}"
            )
    observed_sha = _sha256_file(recognizer_path)
    if observed_sha != ALTERNATE_RECOGNIZER_SHA256:
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "diagnostic recognizer bytes do not match pinned antelopev2 glintr100 SHA-256"
        )
    return recognizer_path, provenance


def _load_alternate_recognizer(path: Path, *, device: str):
    try:
        from insightface import model_zoo
    except Exception as exc:  # noqa: BLE001
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "InsightFace model_zoo is unavailable"
        ) from exc

    normalized = device.strip().lower()
    if normalized not in {"cpu", "cuda", "cuda:0"}:
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "--device must be cpu, cuda or cuda:0"
        )
    use_cuda = normalized != "cpu"
    providers = (
        ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if use_cuda
        else ["CPUExecutionProvider"]
    )
    try:
        recognizer = model_zoo.get_model(
            str(path),
            providers=providers,
        )
        if recognizer is None:
            raise RuntimeError("model_zoo returned no recognizer")
        if getattr(recognizer, "taskname", None) != "recognition":
            raise RuntimeError(
                f"expected recognition task, got {getattr(recognizer, 'taskname', None)!r}"
            )
        recognizer.prepare(ctx_id=0 if use_cuda else -1)
    except Exception as exc:  # noqa: BLE001
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            f"alternate recognizer initialization failed: {exc}"
        ) from exc

    input_size = getattr(recognizer, "input_size", None)
    if (
        not isinstance(input_size, (list, tuple))
        or len(input_size) != 2
        or tuple(int(value) for value in input_size) != (112, 112)
    ):
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "alternate recognizer input size is not pinned 112x112"
        )
    output_shape = getattr(recognizer, "output_shape", None)
    if (
        not isinstance(output_shape, (list, tuple))
        or len(output_shape) < 2
        or int(output_shape[-1]) != 512
    ):
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "alternate recognizer embedding dimension is not pinned 512"
        )
    return recognizer


def _measure_recognizers(
    *,
    adapter: Any,
    runtime: Any,
    representation: Any,
    alternate_recognizer: Any,
    image: Any,
    dimension: int,
) -> tuple[list[float], list[float], dict[str, Any]]:
    current, current_quality = representation._single_face_measurement(
        adapter=adapter,
        runtime=runtime,
        image=image,
    )
    if current is None:
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "accepted frame no longer replays as one identity"
        )

    candidates = adapter._candidates(runtime, image)
    faces = [
        item.get("face")
        for item in candidates
        if item.get("face") is not None
    ]
    if len(candidates) != 1 or len(faces) != 1:
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "accepted frame did not reproduce exactly one face for recognizer A/B"
        )
    face = faces[0]
    landmarks = getattr(face, "kps", None)
    if landmarks is None:
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "accepted frame has no five-point landmarks"
        )

    current_models = getattr(runtime.face_app, "models", None)
    current_recognizer = (
        current_models.get("recognition")
        if isinstance(current_models, Mapping)
        else None
    )
    if (
        current_recognizer is None
        or not callable(getattr(current_recognizer, "get_feat", None))
    ):
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "current InsightFace recognition model does not expose get_feat"
        )

    try:
        from insightface.utils import face_align

        aligned = face_align.norm_crop(
            image,
            landmark=landmarks,
            image_size=112,
        )
        aligned = runtime.np.ascontiguousarray(aligned)
        current_direct = _normalize(
            current_recognizer.get_feat(aligned),
            dimension=dimension,
            label="current direct recognition embedding",
        )
        alternate = _normalize(
            alternate_recognizer.get_feat(aligned),
            dimension=dimension,
            label="alternate recognition embedding",
        )
    except PhotorealIdentityRecognizerAbDiagnosticError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            f"recognizer A/B inference failed: {exc}"
        ) from exc

    direct_replay_cosine = _cosine(current, current_direct)
    if direct_replay_cosine < 0.999999:
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "current recognizer direct replay does not match FaceAnalysis embedding"
        )

    return current, alternate, {
        "status": "available",
        "current_direct_replay_cosine": round(direct_replay_cosine, 9),
        "current_quality": current_quality,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare BodyRig's pinned buffalo_l w600k_r50 identity representation "
            "with pinned antelopev2 glintr100 on the exact same human-attested "
            "positive and persisted negative frames. Diagnostic only."
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
    parser.add_argument("--diagnostic-recognizer-root", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.out.expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            f"diagnostic output already exists: {output}"
        )

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    flip = _load_module(
        repo_root / "tools" / "photoreal_identity_flip_tta_diagnostic.py",
        "bodyrig_identity_recognizer_ab_flip_dependency",
    )
    representation = flip._load_representation_tool(repo_root)
    adapter = representation._load_adapter(repo_root)
    adapter_revision = adapter._self_revision()

    bank_path = args.identity_bank.expanduser().resolve()
    identity_request_path = args.identity_request.expanduser().resolve()
    identity_request_origin_path = args.identity_request_origin.expanduser().resolve()
    calibration_request_path = args.calibration_request.expanduser().resolve()
    calibration_request_origin_path = (
        args.calibration_request_origin.expanduser().resolve()
    )
    negative_observations_path = args.negative_observations.expanduser().resolve()
    review_root = args.review_root.expanduser().resolve()
    model_root = args.model_root.expanduser().resolve()
    diagnostic_recognizer_root = (
        args.diagnostic_recognizer_root.expanduser().resolve()
    )

    bank = _read_json(bank_path, label="identity bank")
    performer_id, bank_sha = review._validate_bank(
        bank,
        adapter_revision=adapter_revision,
    )
    dimension = bank.get("embedding_dimension")
    if dimension != 512:
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "recognizer A/B diagnostic requires the pinned 512-dimensional identity bank"
        )

    identity_request = _read_json(
        identity_request_path,
        label="Stage-7 identity execution request",
    )
    identity_request_origin = _read_json(
        identity_request_origin_path,
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
        review_root=review_root,
        bank=bank,
    )

    calibration_request = _read_json(
        calibration_request_path,
        label="Stage-13 calibration execution request",
    )
    calibration_request_origin = _read_json(
        calibration_request_origin_path,
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
    negative_document = _read_json(
        negative_observations_path,
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

    model_set = adapter.build_model_set(model_root)
    if flip._sha(
        model_set.get("model_set_sha256"),
        label="runtime model-set SHA-256",
    ) != flip._sha(
        bank.get("model_set_sha256"),
        label="identity bank model-set SHA-256",
    ):
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "current model root does not match identity bank model set"
        )
    manifest = adapter._load_model_manifest(model_root)
    runtime = adapter._load_runtime(manifest, device=args.device)
    if runtime.embedding_dimension != dimension:
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "current runtime embedding dimension does not match identity bank"
        )

    alternate_path, alternate_provenance = _validate_alternate_provenance(
        root=diagnostic_recognizer_root,
    )
    alternate_recognizer = _load_alternate_recognizer(
        alternate_path,
        device=args.device,
    )

    references = bank.get("references")
    if not isinstance(references, list) or not references:
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "identity bank contains no references"
        )

    positive_variants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    negative_variants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    positive_diagnostics: list[dict[str, Any]] = []

    for index, raw in enumerate(references):
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityRecognizerAbDiagnosticError(
                "identity bank reference is invalid"
            )
        source_key = str(raw.get("source_key") or "").strip()
        source = identity_sources.get(source_key)
        if source is None:
            raise PhotorealIdentityRecognizerAbDiagnosticError(
                f"identity bank reference source is absent from Stage-7 request: {source_key}"
            )
        sample = flip._find_sample(
            source,
            field="reference_samples",
            timestamp=raw.get("timestamp_seconds"),
            eye=raw.get("eye"),
        )
        expected_frame_sha = flip._sha(
            raw.get("frame_sha256"),
            label="identity bank frame SHA-256",
        )
        image, _viewport_id, _viewport, _eye_image, _spatial = (
            representation._match_exact_viewport(
                adapter=adapter,
                runtime=runtime,
                source=source,
                sample=sample,
                expected_frame_sha=expected_frame_sha,
            )
        )
        current, alternate, quality = _measure_recognizers(
            adapter=adapter,
            runtime=runtime,
            representation=representation,
            alternate_recognizer=alternate_recognizer,
            image=image,
            dimension=dimension,
        )
        stored = _normalize(
            raw.get("embedding"),
            dimension=dimension,
            label=f"identity bank embedding[{index}]",
        )
        if _cosine(current, stored) < 0.999999:
            raise PhotorealIdentityRecognizerAbDiagnosticError(
                "current recognizer replay does not match persisted bank embedding"
            )
        group_id = str(raw.get("group_id") or "").strip()
        if not group_id:
            raise PhotorealIdentityRecognizerAbDiagnosticError(
                "identity bank reference lacks group id"
            )

        positive_variants["bank-w600k-r50"].append(
            {"group_id": group_id, "embedding": stored}
        )
        positive_variants["replay-w600k-r50"].append(
            {"group_id": group_id, "embedding": current}
        )
        positive_variants["antelopev2-glintr100"].append(
            {"group_id": group_id, "embedding": alternate}
        )
        positive_diagnostics.append(
            {
                "reference_index": index,
                "group_id": group_id,
                "frame_sha256": expected_frame_sha,
                "timestamp_seconds": raw.get("timestamp_seconds"),
                "eye": str(raw.get("eye") or ""),
                "current_to_alternate_cosine": round(
                    _cosine(current, alternate),
                    9,
                ),
                **quality,
            }
        )

    negative_diagnostics: list[dict[str, Any]] = []
    for item in negatives:
        source = item["source"]
        sample = flip._find_sample(
            source,
            field="samples",
            timestamp=item["timestamp_seconds"],
            eye=item["eye"],
        )
        image, spatial = adapter._read_sample(runtime, source, sample)
        if spatial:
            raise PhotorealIdentityRecognizerAbDiagnosticError(
                "persisted negative unexpectedly requires spatial deprojection"
            )
        if adapter._frame_sha(image) != item["frame_sha256"]:
            raise PhotorealIdentityRecognizerAbDiagnosticError(
                "persisted negative frame SHA no longer reproduces"
            )

        current, alternate, quality = _measure_recognizers(
            adapter=adapter,
            runtime=runtime,
            representation=representation,
            alternate_recognizer=alternate_recognizer,
            image=image,
            dimension=dimension,
        )
        stored = item["stored_embedding"]
        if _cosine(current, stored) < 0.999999:
            raise PhotorealIdentityRecognizerAbDiagnosticError(
                "current recognizer replay does not match persisted negative embedding"
            )

        base = {"subject_performer_id": item["subject_performer_id"]}
        negative_variants["bank-w600k-r50"].append(
            {**base, "embedding": stored}
        )
        negative_variants["replay-w600k-r50"].append(
            {**base, "embedding": current}
        )
        negative_variants["antelopev2-glintr100"].append(
            {**base, "embedding": alternate}
        )
        negative_diagnostics.append(
            {
                "negative_index": item["index"],
                "subject_performer_id": item["subject_performer_id"],
                "frame_sha256": item["frame_sha256"],
                "current_to_alternate_cosine": round(
                    _cosine(current, alternate),
                    9,
                ),
                **quality,
            }
        )

    variant_results: dict[str, Any] = {}
    for name in (
        "bank-w600k-r50",
        "replay-w600k-r50",
        "antelopev2-glintr100",
    ):
        positives = positive_variants[name]
        variant_negatives = negative_variants[name]
        positive_groups = {str(item["group_id"]) for item in positives}
        negative_performers = {
            str(item["subject_performer_id"]) for item in variant_negatives
        }
        if (
            len(positives) != len(references)
            or len(variant_negatives) != len(negatives)
            or len(positive_groups) != len(attestation.get("accepted_group_ids") or [])
        ):
            raise PhotorealIdentityRecognizerAbDiagnosticError(
                f"recognizer A/B comparison lost evidence coverage for {name}"
            )
        variant_results[name] = {
            "positive_measurement_count": len(positives),
            "negative_measurement_count": len(variant_negatives),
            "positive_reference_coverage": 1.0,
            "negative_observation_coverage": 1.0,
            "positive_group_count": len(positive_groups),
            "negative_performer_count": len(negative_performers),
            "scoring_status": "available",
            "scoring_models": flip._score_models(
                positives,
                variant_negatives,
            ),
            "diagnostic_only": True,
        }

    bodyrig_revision = str(os.environ.get("BODYRIG_REVISION") or "").strip().lower()
    if (
        len(bodyrig_revision) != 40
        or any(character not in "0123456789abcdef" for character in bodyrig_revision)
    ):
        raise PhotorealIdentityRecognizerAbDiagnosticError(
            "BODYRIG_REVISION must bind diagnostic execution to exact Git HEAD"
        )

    result = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "diagnostic_bodyrig_revision": bodyrig_revision,
        "adapter_revision": adapter_revision,
        "model_set_sha256": str(bank.get("model_set_sha256") or ""),
        "identity_bank_sha256": bank_sha,
        "identity_bank_file_sha256": _sha256_file(bank_path),
        "identity_request_sha256": _sha256_file(identity_request_origin_path),
        "calibration_request_sha256": _sha256_file(calibration_request_origin_path),
        "negative_observations_sha256": _sha256_file(negative_observations_path),
        "identity_group_attestation_sha256": _sha256_file(
            review_root / "identity-group-attestation.json"
        ),
        "alternate_recognizer": {
            "package": ALTERNATE_PACKAGE,
            "recognizer_file": ALTERNATE_RECOGNIZER_FILE,
            "recognizer_sha256": ALTERNATE_RECOGNIZER_SHA256,
            "archive_sha256": ALTERNATE_ARCHIVE_SHA256,
            "architecture": alternate_provenance.get("recognition_architecture"),
            "training_set": alternate_provenance.get("recognition_training_set"),
        },
        "positive_reference_count": len(references),
        "human_attested_group_count": len(
            attestation.get("accepted_group_ids") or []
        ),
        "negative_observation_count": len(negatives),
        "negative_performer_count": len(
            {item["subject_performer_id"] for item in negatives}
        ),
        "comparison": {
            "detector": "existing pinned buffalo_l detector",
            "alignment": "same original-frame five-point landmarks and 112x112 norm_crop",
            "current_recognizer": "w600k_r50.onnx / ResNet50@WebFace600K",
            "alternate_recognizer": "glintr100.onnx / ResNet100@Glint360K",
            "production_adapter_changed": False,
        },
        "variants": variant_results,
        "positive_reference_diagnostics": positive_diagnostics,
        "negative_observation_diagnostics": negative_diagnostics,
        "diagnostic_only": True,
        "identity_group_selection_authority": False,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "format": FORMAT,
                "performer_id": performer_id,
                "positive_reference_count": len(references),
                "negative_observation_count": len(negatives),
                "variants": variant_results,
                "diagnostic_only": True,
                "production_activation": False,
                "output": str(output),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
