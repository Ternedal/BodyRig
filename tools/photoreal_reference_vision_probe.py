from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


class VisionProbeError(RuntimeError):
    pass


def _load_adapter(path: Path):
    spec = importlib.util.spec_from_file_location("bodyrig_photoreal_reference_vision_runtime_probe", path)
    if spec is None or spec.loader is None:
        raise VisionProbeError(f"could not load adapter module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def _active_face_execution_providers(face_app: object) -> list[str]:
    models = getattr(face_app, "models", None)
    if not isinstance(models, dict) or not models:
        raise VisionProbeError("InsightFace runtime exposes no initialized model sessions")
    providers: set[str] = set()
    for model in models.values():
        session = getattr(model, "session", None)
        get_providers = getattr(session, "get_providers", None)
        if not callable(get_providers):
            raise VisionProbeError("InsightFace model session does not expose execution providers")
        try:
            active = get_providers()
        except Exception as exc:  # noqa: BLE001
            raise VisionProbeError(f"could not inspect InsightFace execution providers: {exc}") from exc
        if not isinstance(active, (list, tuple)):
            raise VisionProbeError("InsightFace execution provider readback is invalid")
        for provider in active:
            name = str(provider or "").strip()
            if name:
                providers.add(name)
    if not providers:
        raise VisionProbeError("InsightFace runtime reports no active execution providers")
    return sorted(providers)



def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe the pinned BodyRig Photoreal reference vision runtime without source media.")
    parser.add_argument("--adapter-path", type=Path, required=True)
    parser.add_argument("--adapter-revision", required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--model-set-sha256", required=True)
    parser.add_argument("--device", default="cuda:0")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        adapter_path = args.adapter_path.expanduser().resolve()
        model_root = args.model_root.expanduser().resolve()
        if not adapter_path.is_file():
            raise VisionProbeError(f"adapter not found: {adapter_path}")
        if not model_root.is_dir():
            raise VisionProbeError(f"model root not found: {model_root}")
        adapter = _load_adapter(adapter_path)
        try:
            observed_revision = str(adapter._self_revision()).strip().lower()
        except Exception as exc:  # noqa: BLE001
            raise VisionProbeError(f"could not compute executable adapter revision: {exc}") from exc
        if len(observed_revision) != 64 or any(character not in "0123456789abcdef" for character in observed_revision):
            raise VisionProbeError("executable adapter revision is invalid")
        if observed_revision != str(args.adapter_revision).strip().lower():
            raise VisionProbeError("adapter dependency bytes do not match pinned adapter revision")
        try:
            model_set = adapter.build_model_set(model_root)
        except Exception as exc:  # noqa: BLE001
            raise VisionProbeError(f"could not digest model root: {exc}") from exc
        expected_model_sha = str(args.model_set_sha256).strip().lower()
        if model_set.get("model_set_sha256") != expected_model_sha:
            raise VisionProbeError("model root bytes do not match pinned model-set SHA-256")

        manifest = adapter._load_model_manifest(model_root)
        runtime = adapter._load_runtime(manifest, device=args.device)
        synthetic = runtime.np.zeros((512, 512, 3), dtype=runtime.np.uint8)
        faces = adapter._faces(runtime, synthetic)
        poses = adapter._pose_predictions(runtime, synthetic)
        face_execution_providers = _active_face_execution_providers(runtime.face_app)
        requested_device = str(args.device or "").strip().lower()
        if requested_device != "cpu" and "CUDAExecutionProvider" not in face_execution_providers:
            raise VisionProbeError(
                "requested CUDA but InsightFace sessions did not activate CUDAExecutionProvider"
            )
        frame_sha = adapter._frame_sha(synthetic)
        phash = adapter._perceptual_hash(runtime, synthetic)
        result = {
            "format": "bodyrig-photoreal-reference-vision-probe",
            "version": 1,
            "adapter_revision": observed_revision,
            "model_set_sha256": expected_model_sha,
            "device": args.device,
            "identity_embedding_dimension": runtime.embedding_dimension,
            "face_inference_executed": True,
            "pose_inference_executed": True,
            "face_execution_providers": face_execution_providers,
            "synthetic_face_count": len(faces),
            "synthetic_pose_count": len(poses),
            "synthetic_frame_sha256": frame_sha,
            "synthetic_perceptual_hash": phash,
            "source_media_accessed": False,
            "identity_authority": False,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    except (OSError, VisionProbeError) as exc:
        print(f"BodyRig Photoreal reference vision probe: FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
