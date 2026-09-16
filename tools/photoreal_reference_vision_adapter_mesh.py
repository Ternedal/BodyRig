from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bodyrig.photoreal_mesh_deprojection import (  # noqa: E402
    PhotorealMeshDeprojectionError,
    deproject_mesh_views,
)

BASE_ADAPTER_PATH = Path(__file__).with_name("photoreal_reference_vision_adapter.py")
BASE_SPEC = importlib.util.spec_from_file_location("bodyrig_photoreal_reference_vision_adapter_base", BASE_ADAPTER_PATH)
if BASE_SPEC is None or BASE_SPEC.loader is None:
    raise RuntimeError("could not load BodyRig reference vision base adapter")
base = importlib.util.module_from_spec(BASE_SPEC)
sys.modules[BASE_SPEC.name] = base
BASE_SPEC.loader.exec_module(base)

ADAPTER_NAME = base.ADAPTER_NAME
FRAME_REQUEST = base.FRAME_REQUEST
ReferenceVisionError = base.ReferenceVisionError


def _self_revision() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# The generated config binds to this wrapper's exact bytes. Keep the base adapter's
# provenance verifier intact while making its self-revision point at the executable
# adapter that was actually configured.
base._self_revision = _self_revision


def _frame_result(runtime: Any, request: Mapping[str, Any], args: Any) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    mesh_cache: dict[Any, Any] = {}
    for source, sample in base._iter_samples(request["sources"], "samples"):
        image, spatial = base._read_sample(runtime, source, sample)
        base_row = {
            "source_key": source["source_key"],
            "source_sha256": source["source_sha256"],
            "kind": source["kind"],
            "timestamp_seconds": sample.get("timestamp_seconds"),
            "eye": sample["eye"],
            "projection": source["projection"],
        }
        projection = source.get("projection")
        if spatial and projection == "equi":
            try:
                viewports = base.deproject_equirectangular_views(
                    runtime,
                    image,
                    source.get("projection_authority"),
                )
            except base.PhotorealEquirectangularDeprojectionError as exc:
                raise ReferenceVisionError(f"equirectangular deprojection failed: {exc}") from exc
            for viewport_id, viewport_image in viewports:
                observations.extend(
                    base._candidate_rows(
                        runtime,
                        viewport_image,
                        base=base_row,
                        candidate_prefix=f"{viewport_id}-",
                    )
                )
        elif spatial and projection == "mshp":
            try:
                viewports = deproject_mesh_views(
                    runtime,
                    image,
                    source.get("resolved_path"),
                    source.get("projection_authority"),
                    eye=str(sample.get("eye") or ""),
                    cache=mesh_cache,
                )
            except PhotorealMeshDeprojectionError as exc:
                raise ReferenceVisionError(f"mesh deprojection failed: {exc}") from exc
            for viewport_id, viewport_image in viewports:
                observations.extend(
                    base._candidate_rows(
                        runtime,
                        viewport_image,
                        base=base_row,
                        candidate_prefix=f"{viewport_id}-",
                    )
                )
        elif spatial:
            height, width = image.shape[:2]
            observations.append(
                {
                    **base_row,
                    "frame_sha256": base._frame_sha(image),
                    "perceptual_hash": base._perceptual_hash(runtime, image),
                    "candidate_id": "none-0",
                    "person_detected": False,
                    "width": width,
                    "height": height,
                    "view_bin": "unknown",
                    "face_visibility": 0.0,
                    "full_body_visibility": 0.0,
                    "person_fraction": 0.0,
                    "sharpness": base._sharpness(runtime, image),
                    "motion": 0.0,
                    "occlusion": 0.0,
                    "identity_measurement_status": "unavailable",
                    "identity_embedding": None,
                }
            )
        else:
            observations.extend(base._candidate_rows(runtime, image, base=base_row))
    if not observations:
        raise ReferenceVisionError("frame analyzer produced no observations")
    return {
        "format": "bodyrig-photoreal-frame-observations",
        "version": 1,
        "performer_id": request["performer_id"],
        "analyzer": args.bodyrig_adapter,
        "analyzer_revision": args.bodyrig_revision,
        "analyzer_model_set_sha256": args.bodyrig_model_set_sha256,
        "identity_embedding_dimension": runtime.embedding_dimension,
        "observations": observations,
        "build_only": True,
        "production_activation": False,
    }


base._frame_result = _frame_result


def main(argv: list[str] | None = None) -> int:
    return int(base.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
