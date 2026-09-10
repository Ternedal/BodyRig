#!/usr/bin/env python
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(_PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_PARENT))

from bodyrig.bridges import hmr2_4dhumans_bridge as base  # noqa: E402
from bodyrig.bridges.hmr2_config import ADAPTER_NAME, ADAPTER_REVISION  # noqa: E402
from bodyrig.bridges.phalp_mask_config import (  # noqa: E402
    DETECTRON2_CHECKPOINT_BYTES,
    DETECTRON2_CHECKPOINT_SHA256,
    DETECTRON2_CHECKPOINT_URL,
    DETECTRON2_CONFIG,
    DETECTRON2_REVISION,
    MASK_ADAPTER,
    MASK_REVISION,
)
from bodyrig.bridges.phalp_track_mask import canonicalize_attested_track_masks  # noqa: E402

FORMAT = "bodyrig-phalp-attested-track-mask-batch"
VERSION = 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalize_git_url(value: str) -> str:
    text = value.strip().lower().rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    return text


def _verify_detectron2_authority() -> dict[str, object]:
    try:
        distribution = importlib.metadata.distribution("detectron2")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("pinned Detectron2 distribution is missing") from exc
    raw = distribution.read_text("direct_url.json")
    if not raw:
        raise RuntimeError("Detectron2 install lacks direct_url.json Git authority")
    try:
        direct = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Detectron2 direct_url.json is invalid") from exc
    if not isinstance(direct, dict):
        raise RuntimeError("Detectron2 direct_url.json must be an object")
    if _normalize_git_url(str(direct.get("url") or "")) != "https://github.com/facebookresearch/detectron2":
        raise RuntimeError("Detectron2 distribution origin is not the pinned upstream repository")
    vcs = direct.get("vcs_info")
    if not isinstance(vcs, dict) or vcs.get("vcs") != "git" or str(vcs.get("commit_id") or "").lower() != DETECTRON2_REVISION:
        raise RuntimeError("Detectron2 distribution revision differs from the pinned authority")

    try:
        from detectron2 import model_zoo
        from detectron2.utils.file_io import PathManager
    except ImportError as exc:
        raise RuntimeError("Detectron2 model-zoo runtime is unavailable") from exc
    cfg = model_zoo.get_config(DETECTRON2_CONFIG, trained=True)
    try:
        checkpoint_url = str(cfg.train.init_checkpoint)
    except Exception as exc:
        raise RuntimeError("Detectron2 trained config lacks checkpoint URL") from exc
    if checkpoint_url != DETECTRON2_CHECKPOINT_URL:
        raise RuntimeError("Detectron2 model-zoo checkpoint URL differs from pinned authority")
    try:
        checkpoint_path = Path(PathManager.get_local_path(checkpoint_url)).expanduser().resolve()
    except Exception as exc:
        raise RuntimeError("Detectron2 checkpoint could not be resolved into local cache") from exc
    if not checkpoint_path.is_file():
        raise RuntimeError("Detectron2 checkpoint cache file is missing")
    size = checkpoint_path.stat().st_size
    if size != DETECTRON2_CHECKPOINT_BYTES:
        raise RuntimeError(
            f"Detectron2 checkpoint size changed: {size} != {DETECTRON2_CHECKPOINT_BYTES}"
        )
    digest = _sha256_file(checkpoint_path)
    if digest != DETECTRON2_CHECKPOINT_SHA256:
        raise RuntimeError("Detectron2 checkpoint SHA-256 differs from pinned authority")
    return {
        "detectron2_revision": DETECTRON2_REVISION,
        "config": DETECTRON2_CONFIG,
        "checkpoint_url": DETECTRON2_CHECKPOINT_URL,
        "checkpoint_bytes": DETECTRON2_CHECKPOINT_BYTES,
        "checkpoint_sha256": digest,
        "mask_adapter": MASK_ADAPTER,
        "mask_revision": MASK_REVISION,
    }


def _decode_mask(raw: object) -> object:
    try:
        import numpy as np
        from pycocotools import mask as mask_utils
    except ImportError as exc:
        raise RuntimeError("PHALP instance-mask extraction requires NumPy and pycocotools") from exc
    decoded = mask_utils.decode(raw)
    array = np.asarray(decoded)
    if array.ndim == 3:
        if array.shape[2] != 1:
            raise RuntimeError("PHALP mask contains multiple encoded instances in one track state")
        array = array[:, :, 0]
    if array.ndim != 2:
        raise RuntimeError("PHALP mask decode did not produce one 2D instance mask")
    return array


def _run_source_mask(
    repo: Path,
    source: Path,
    loader_env: dict[str, str],
    *,
    selected_track_id: str,
    requested_timestamps_ms: list[int],
) -> dict[str, object]:
    try:
        import joblib
    except ImportError as exc:
        raise RuntimeError("joblib is required in the 4D-Humans environment") from exc

    with tempfile.TemporaryDirectory(prefix="bodyrig-phalp-mask-") as temp_dir_raw:
        output_dir = Path(temp_dir_raw) / "output"
        command = base._track_command(repo, source, output_dir)  # noqa: SLF001
        completed = subprocess.run(
            command,
            cwd=repo,
            env=loader_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.stdout:
            print(completed.stdout[-12000:], file=sys.stderr)
        if completed.returncode != 0:
            raise RuntimeError(f"4D-Humans PHALP mask pass failed with exit code {completed.returncode}")
        pkls = sorted((output_dir / "results").glob("*.pkl"))
        if len(pkls) != 1:
            raise RuntimeError(f"expected exactly one PHALP mask result pickle, found {len(pkls)}")
        frame_results = joblib.load(pkls[0])
        if not isinstance(frame_results, dict):
            raise RuntimeError("unexpected PHALP mask result shape")
        review = canonicalize_attested_track_masks(
            frame_results,
            fps=base._video_fps(source),  # noqa: SLF001
            source_index=0,
            selected_track_id=selected_track_id,
            requested_timestamps_ms=requested_timestamps_ms,
            decode_mask=_decode_mask,
        )
        return {
            "source_index": 0,
            "source_media_sha256": _sha256_file(source),
            "mask_review": review,
        }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Rerun pinned PHALP and export instance masks only for an externally human-attested track/timestamps."
    )
    parser.add_argument("--repo", required=True, help="Pinned shubham-goel/4D-Humans checkout")
    parser.add_argument("--phalp-repo", required=True, help="Exact pinned PHALP checkout authority")
    parser.add_argument("--selected-track-id", required=True)
    parser.add_argument("--timestamp-ms", type=int, action="append", required=True)
    args = parser.parse_args()
    try:
        repo = Path(args.repo).expanduser().resolve()
        phalp_repo = Path(args.phalp_repo).expanduser().resolve()
        timestamps = sorted(args.timestamp_ms)
        if timestamps != sorted(set(timestamps)):
            raise RuntimeError("requested mask timestamps must be unique")

        base._verify_repo(repo)  # noqa: SLF001
        base._verify_phalp_install(phalp_repo)  # noqa: SLF001
        base._verify_nmr_install()  # noqa: SLF001
        detector = _verify_detectron2_authority()
        loader_env = base._recovery_loader_env()  # noqa: SLF001
        base._verify_cuda_loader_env(loader_env)  # noqa: SLF001
        base._ensure_phalp_smpl_cache(repo)  # noqa: SLF001
        sources = base._read_request()  # noqa: SLF001
        if len(sources) != 1:
            raise RuntimeError("attested PHALP mask bridge requires exactly one source")
        row = _run_source_mask(
            repo,
            sources[0],
            loader_env,
            selected_track_id=args.selected_track_id,
            requested_timestamps_ms=timestamps,
        )
        payload = {
            "format": FORMAT,
            "version": VERSION,
            "adapter": ADAPTER_NAME,
            "revision": ADAPTER_REVISION,
            "detector": detector,
            "source": row,
            "selected_track_id_input": args.selected_track_id,
            "requested_timestamps_ms": timestamps,
            "track_identity_inferred_by_bridge": False,
            "human_attestation_verified_by_bridge": False,
            "appearance_embeddings_exported": False,
            "source_paths_exported": False,
            "hidden_pixels_inferred": False,
            "generative_pixels_used": False,
            "target_mask_authority": False,
            "photoidentity_source_evidence_authority": False,
            "reconstruction_permitted": False,
            "production_activation": False,
        }
        json.dump(payload, sys.stdout, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        print(f"BodyRig PHALP attested-track mask bridge: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
