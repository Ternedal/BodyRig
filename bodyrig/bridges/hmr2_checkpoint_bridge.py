#!/usr/bin/env python
"""Crash-resilient checkpoint layer for the pinned 4D-Humans/HMR2 bridge.

The underlying authority bridge remains responsible for dependency pinning,
CUDA/PHALP setup and canonicalization. This wrapper replaces only its per-source
runner so expensive PHALP results survive process/WSL failures and can be
resumed without recomputing already completed observation segments.

The throughput policy is deliberately recovery-only: selected observation MP4
bytes are never rewritten. For PHALP only, BodyRig materializes a temporary JPEG
sequence at a bounded temporal rate using the same OpenCV JPEG path that pinned
PHALP itself uses. Identity capture and high-fidelity fitting continue to consume
the original full-rate observation segment bytes.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(_PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_PARENT))

from bodyrig.bridges import hmr2_4dhumans_bridge as base  # noqa: E402
from bodyrig.bridges.hmr2_config import (  # noqa: E402
    ADAPTER_NAME,
    ADAPTER_REVISION,
    RECOVERY_MAX_FPS,
    RECOVERY_TEMPORAL_SAMPLING_POLICY,
)

CHECKPOINT_DIR_NAME = "bodyrig-recovery-checkpoints"
CHECKPOINT_FORMAT = "bodyrig-recovery-segment-checkpoint"
RAW_META_FORMAT = "bodyrig-recovery-phalp-checkpoint"
STATUS_FORMAT = "bodyrig-recovery-segment-status"
CHECKPOINT_VERSION = 1


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _segment_prefix(source_index: int) -> str:
    return f"segment-{source_index + 1:02d}"


def _checkpoint_root(source: Path) -> Path:
    root = source.resolve().parent / CHECKPOINT_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _canonical_path(root: Path, source_index: int) -> Path:
    return root / f"{_segment_prefix(source_index)}.json"


def _raw_path(root: Path, source_index: int) -> Path:
    return root / f"{_segment_prefix(source_index)}.phalp.pkl"


def _raw_meta_path(root: Path, source_index: int) -> Path:
    return root / f"{_segment_prefix(source_index)}.phalp.json"


def _status_path(root: Path, source_index: int) -> Path:
    return root / f"{_segment_prefix(source_index)}.status.json"


def _log_path(root: Path, source_index: int) -> Path:
    return root / f"{_segment_prefix(source_index)}.log"


def _sampling_details(source: Path) -> tuple[float, int, float]:
    source_fps = base._video_fps(source)
    if not math.isfinite(source_fps) or source_fps <= 0.0:
        raise RuntimeError(f"could not determine source FPS for recovery sampling: {source.name}")
    stride = max(1, int(math.ceil(source_fps / RECOVERY_MAX_FPS)))
    effective_fps = source_fps / stride
    if effective_fps <= 0.0 or effective_fps > RECOVERY_MAX_FPS + 1e-9:
        raise RuntimeError("recovery temporal sampling policy produced an invalid effective FPS")
    return source_fps, stride, effective_fps


def _checkpoint_identity_matches(
    payload: dict,
    *,
    source_index: int,
    source_sha256: str,
    sampling_stride: int,
    format_name: str,
) -> bool:
    return (
        payload.get("format") == format_name
        and payload.get("version") == CHECKPOINT_VERSION
        and payload.get("adapter") == ADAPTER_NAME
        and payload.get("revision") == ADAPTER_REVISION
        and payload.get("source_index") == source_index
        and payload.get("source_sha256") == source_sha256
        and payload.get("sampling_policy") == RECOVERY_TEMPORAL_SAMPLING_POLICY
        and payload.get("sampling_stride") == sampling_stride
    )


def _load_canonical_checkpoint(
    root: Path,
    *,
    source_index: int,
    source_sha256: str,
    sampling_stride: int,
) -> list[dict] | None:
    payload = _read_json(_canonical_path(root, source_index))
    if payload is None or not _checkpoint_identity_matches(
        payload,
        source_index=source_index,
        source_sha256=source_sha256,
        sampling_stride=sampling_stride,
        format_name=CHECKPOINT_FORMAT,
    ):
        return None
    tracks = payload.get("tracks")
    if not isinstance(tracks, list):
        return None
    if not all(isinstance(track, dict) for track in tracks):
        return None
    return tracks


def _publish_canonical_checkpoint(
    root: Path,
    *,
    source_index: int,
    source_sha256: str,
    source_fps: float,
    sampling_stride: int,
    effective_fps: float,
    tracks: list[dict],
) -> Path:
    path = _canonical_path(root, source_index)
    _atomic_write_json(
        path,
        {
            "format": CHECKPOINT_FORMAT,
            "version": CHECKPOINT_VERSION,
            "adapter": ADAPTER_NAME,
            "revision": ADAPTER_REVISION,
            "source_index": source_index,
            "source_sha256": source_sha256,
            "sampling_policy": RECOVERY_TEMPORAL_SAMPLING_POLICY,
            "source_fps": source_fps,
            "sampling_stride": sampling_stride,
            "effective_fps": effective_fps,
            "tracks": tracks,
        },
    )
    return path


def _publish_raw_checkpoint(
    root: Path,
    *,
    source_index: int,
    source_sha256: str,
    source_fps: float,
    sampling_stride: int,
    effective_fps: float,
    source_pkl: Path,
) -> Path:
    raw_path = _raw_path(root, source_index)
    temp_path = raw_path.with_name(f".{raw_path.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(source_pkl, temp_path)
        os.replace(temp_path, raw_path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
    _atomic_write_json(
        _raw_meta_path(root, source_index),
        {
            "format": RAW_META_FORMAT,
            "version": CHECKPOINT_VERSION,
            "adapter": ADAPTER_NAME,
            "revision": ADAPTER_REVISION,
            "source_index": source_index,
            "source_sha256": source_sha256,
            "sampling_policy": RECOVERY_TEMPORAL_SAMPLING_POLICY,
            "source_fps": source_fps,
            "sampling_stride": sampling_stride,
            "effective_fps": effective_fps,
        },
    )
    return raw_path


def _load_raw_checkpoint(
    root: Path,
    *,
    source_index: int,
    source_sha256: str,
    sampling_stride: int,
):
    meta = _read_json(_raw_meta_path(root, source_index))
    raw_path = _raw_path(root, source_index)
    if meta is None or not raw_path.is_file():
        return None
    if not _checkpoint_identity_matches(
        meta,
        source_index=source_index,
        source_sha256=source_sha256,
        sampling_stride=sampling_stride,
        format_name=RAW_META_FORMAT,
    ):
        return None
    try:
        import joblib
    except ImportError as exc:
        raise RuntimeError("joblib is required in the 4D-Humans environment") from exc
    frame_results = joblib.load(raw_path)
    if not isinstance(frame_results, dict):
        raise RuntimeError("persistent PHALP checkpoint has unexpected result shape")
    return frame_results


def _write_status(
    root: Path,
    *,
    source_index: int,
    source_sha256: str,
    sampling_stride: int,
    effective_fps: float,
    state: str,
    detail: str = "",
) -> None:
    payload = {
        "format": STATUS_FORMAT,
        "version": CHECKPOINT_VERSION,
        "adapter": ADAPTER_NAME,
        "revision": ADAPTER_REVISION,
        "source_index": source_index,
        "source_sha256": source_sha256,
        "sampling_policy": RECOVERY_TEMPORAL_SAMPLING_POLICY,
        "sampling_stride": sampling_stride,
        "effective_fps": effective_fps,
        "state": state,
    }
    if detail:
        payload["detail"] = detail[-4000:]
    _atomic_write_json(_status_path(root, source_index), payload)


def _tail_text(path: Path, limit: int = 12000) -> str:
    if not path.is_file():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", errors="replace")


def _materialize_recovery_frames(source: Path, destination: Path, sampling_stride: int) -> int:
    """Create PHALP-only JPEG frames without changing the source segment bytes.

    Pinned PHALP normally uses OpenCV FrameExtractor + cv2.imwrite for every MP4
    frame. BodyRig performs that same decode/JPEG boundary here but retains only
    every Nth frame. The directory is private to the temporary recovery run and
    is never reused as identity/high-fidelity source evidence.
    """
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("opencv/cv2 is required in the 4D-Humans environment") from exc
    destination.mkdir(parents=True, exist_ok=False)
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"could not open recovery source for temporal sampling: {source.name}")
    frame_index = 0
    saved = 0
    try:
        while capture.isOpened():
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % sampling_stride == 0:
                saved += 1
                target = destination / f"{saved:06d}.jpg"
                if not cv2.imwrite(str(target), frame):
                    raise RuntimeError(f"could not write recovery-only sampled frame {saved}")
            frame_index += 1
    finally:
        capture.release()
        cv2.destroyAllWindows()
    if saved < 2:
        raise RuntimeError("recovery temporal sampling produced fewer than two frames")
    return saved


def _recovery_directory_track_command(repo: Path, source_dir: Path, output_dir: Path) -> list[str]:
    """Run pinned PHALP on sampled JPEGs while retaining the existing VRAM patch."""
    track_script = str(repo / "track.py")
    overrides = [
        f"video.source={base._quoted_hydra_path(source_dir)}",
        f"video.output_dir={base._quoted_hydra_path(output_dir)}",
        "render.enable=false",
        "overwrite=true",
    ]
    return [
        sys.executable,
        "-c",
        base._PHALP_MP4_LOW_VRAM_LAUNCHER,
        track_script,
        *overrides,
    ]


def _canonicalize_raw(
    frame_results: dict,
    *,
    effective_fps: float,
    source_index: int,
) -> list[dict]:
    return base.canonicalize_phalp_results(
        frame_results,
        fps=effective_fps,
        source_index=source_index,
    )


def _checkpointing_run_source(
    repo: Path,
    source: Path,
    source_index: int,
    loader_env: dict[str, str],
) -> list[dict]:
    source = source.expanduser().resolve()
    root = _checkpoint_root(source)
    source_sha256 = base._sha256_file(source)
    source_fps, sampling_stride, effective_fps = _sampling_details(source)

    cached = _load_canonical_checkpoint(
        root,
        source_index=source_index,
        source_sha256=source_sha256,
        sampling_stride=sampling_stride,
    )
    if cached is not None:
        print(
            f"BodyRig recovery checkpoint: reusing {_segment_prefix(source_index)} ({len(cached)} track(s)) | "
            f"sampling={RECOVERY_TEMPORAL_SAMPLING_POLICY} stride={sampling_stride} effective_fps={effective_fps:.3f}",
            file=sys.stderr,
        )
        _write_status(
            root,
            source_index=source_index,
            source_sha256=source_sha256,
            sampling_stride=sampling_stride,
            effective_fps=effective_fps,
            state="complete",
            detail="reused canonical checkpoint",
        )
        return cached

    try:
        raw_checkpoint = _load_raw_checkpoint(
            root,
            source_index=source_index,
            source_sha256=source_sha256,
            sampling_stride=sampling_stride,
        )
        if raw_checkpoint is not None:
            print(
                f"BodyRig recovery checkpoint: resuming {_segment_prefix(source_index)} from persistent PHALP output | "
                f"stride={sampling_stride} effective_fps={effective_fps:.3f}",
                file=sys.stderr,
            )
            tracks = _canonicalize_raw(
                raw_checkpoint,
                effective_fps=effective_fps,
                source_index=source_index,
            )
            canonical = _publish_canonical_checkpoint(
                root,
                source_index=source_index,
                source_sha256=source_sha256,
                source_fps=source_fps,
                sampling_stride=sampling_stride,
                effective_fps=effective_fps,
                tracks=tracks,
            )
            _write_status(
                root,
                source_index=source_index,
                source_sha256=source_sha256,
                sampling_stride=sampling_stride,
                effective_fps=effective_fps,
                state="complete",
                detail=f"canonical checkpoint published: {canonical.name}",
            )
            return tracks

        try:
            import joblib
        except ImportError as exc:
            raise RuntimeError("joblib is required in the 4D-Humans environment") from exc

        _write_status(
            root,
            source_index=source_index,
            source_sha256=source_sha256,
            sampling_stride=sampling_stride,
            effective_fps=effective_fps,
            state="running",
            detail=f"sampling={RECOVERY_TEMPORAL_SAMPLING_POLICY}; source_fps={source_fps:.3f}; stride={sampling_stride}; effective_fps={effective_fps:.3f}",
        )
        log_path = _log_path(root, source_index)
        with tempfile.TemporaryDirectory(prefix="bodyrig-4dh-") as temp_dir_raw:
            temp_dir = Path(temp_dir_raw)
            output_dir = temp_dir / "output"
            if source.suffix.lower() == ".mp4" and sampling_stride > 1:
                recovery_frames = temp_dir / "sampled-frames"
                sampled_count = _materialize_recovery_frames(source, recovery_frames, sampling_stride)
                command = _recovery_directory_track_command(repo, recovery_frames, output_dir)
                print(
                    f"BodyRig recovery sampling: {source.name} | source_fps={source_fps:.3f} | "
                    f"stride={sampling_stride} | effective_fps={effective_fps:.3f} | frames={sampled_count}",
                    file=sys.stderr,
                )
                print(
                    "BodyRig recovery VRAM: skipped unused PHALP ground-truth RPN detector",
                    file=sys.stderr,
                )
            else:
                command = base._track_command(repo, source, output_dir)
                if source.suffix.lower() == ".mp4":
                    print(
                        f"BodyRig recovery sampling: source already <= {RECOVERY_MAX_FPS:g} fps; no frames skipped",
                        file=sys.stderr,
                    )
                    print(
                        "BodyRig recovery VRAM: skipped unused PHALP ground-truth RPN detector",
                        file=sys.stderr,
                    )
            with log_path.open("w", encoding="utf-8", errors="replace") as log_handle:
                completed = subprocess.run(
                    command,
                    cwd=repo,
                    env=loader_env,
                    text=True,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            tail = _tail_text(log_path)
            if tail:
                print(tail, file=sys.stderr)
            if completed.returncode != 0:
                raise RuntimeError(
                    f"4D-Humans track.py failed with exit code {completed.returncode}; log retained: {log_path}"
                )

            pkls = sorted((output_dir / "results").glob("*.pkl"))
            if len(pkls) != 1:
                raise RuntimeError(
                    f"expected exactly one PHALP result pickle, found {len(pkls)}; log retained: {log_path}"
                )

            # Publish the raw result before loading/canonicalizing it. If the
            # bridge dies anywhere after this point, the expensive PHALP pass is
            # still reusable on the next invocation. Sampling policy/stride are
            # part of checkpoint identity, so uncapped historical results cannot
            # be misread under this throughput candidate.
            persistent_raw = _publish_raw_checkpoint(
                root,
                source_index=source_index,
                source_sha256=source_sha256,
                source_fps=source_fps,
                sampling_stride=sampling_stride,
                effective_fps=effective_fps,
                source_pkl=pkls[0],
            )
            frame_results = joblib.load(persistent_raw)
            if not isinstance(frame_results, dict):
                raise RuntimeError("unexpected PHALP result shape")
            tracks = _canonicalize_raw(
                frame_results,
                effective_fps=effective_fps,
                source_index=source_index,
            )
            canonical = _publish_canonical_checkpoint(
                root,
                source_index=source_index,
                source_sha256=source_sha256,
                source_fps=source_fps,
                sampling_stride=sampling_stride,
                effective_fps=effective_fps,
                tracks=tracks,
            )

        _write_status(
            root,
            source_index=source_index,
            source_sha256=source_sha256,
            sampling_stride=sampling_stride,
            effective_fps=effective_fps,
            state="complete",
            detail=f"canonical checkpoint published: {canonical.name}",
        )
        return tracks
    except Exception as exc:
        try:
            _write_status(
                root,
                source_index=source_index,
                source_sha256=source_sha256,
                sampling_stride=sampling_stride,
                effective_fps=effective_fps,
                state="failed",
                detail=str(exc),
            )
        except Exception:
            pass
        raise


def main() -> int:
    # Keep every authority/preflight rule in the pinned bridge. Replace only the
    # expensive per-source execution boundary with the crash-resilient,
    # versioned recovery-only sampling runner.
    base._run_source = _checkpointing_run_source
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
