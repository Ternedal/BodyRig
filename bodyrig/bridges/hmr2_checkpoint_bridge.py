#!/usr/bin/env python
"""Crash-resilient checkpoint layer for the pinned 4D-Humans/HMR2 bridge.

The underlying authority bridge remains responsible for dependency pinning,
CUDA/PHALP setup and canonicalization. This wrapper replaces only its per-source
runner so expensive PHALP results survive process/WSL failures and can be
resumed without recomputing already completed observation segments.
"""
from __future__ import annotations

import json
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
from bodyrig.bridges.hmr2_config import ADAPTER_NAME, ADAPTER_REVISION  # noqa: E402

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


def _checkpoint_identity_matches(payload: dict, *, source_index: int, source_sha256: str, format_name: str) -> bool:
    return (
        payload.get("format") == format_name
        and payload.get("version") == CHECKPOINT_VERSION
        and payload.get("adapter") == ADAPTER_NAME
        and payload.get("revision") == ADAPTER_REVISION
        and payload.get("source_index") == source_index
        and payload.get("source_sha256") == source_sha256
    )


def _load_canonical_checkpoint(root: Path, *, source_index: int, source_sha256: str) -> list[dict] | None:
    payload = _read_json(_canonical_path(root, source_index))
    if payload is None or not _checkpoint_identity_matches(
        payload,
        source_index=source_index,
        source_sha256=source_sha256,
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
            "tracks": tracks,
        },
    )
    return path


def _publish_raw_checkpoint(
    root: Path,
    *,
    source_index: int,
    source_sha256: str,
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
        },
    )
    return raw_path


def _load_raw_checkpoint(root: Path, *, source_index: int, source_sha256: str):
    meta = _read_json(_raw_meta_path(root, source_index))
    raw_path = _raw_path(root, source_index)
    if meta is None or not raw_path.is_file():
        return None
    if not _checkpoint_identity_matches(
        meta,
        source_index=source_index,
        source_sha256=source_sha256,
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


def _canonicalize_raw(frame_results: dict, *, source: Path, source_index: int) -> list[dict]:
    return base.canonicalize_phalp_results(
        frame_results,
        fps=base._video_fps(source),
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

    cached = _load_canonical_checkpoint(
        root,
        source_index=source_index,
        source_sha256=source_sha256,
    )
    if cached is not None:
        print(
            f"BodyRig recovery checkpoint: reusing {_segment_prefix(source_index)} ({len(cached)} track(s))",
            file=sys.stderr,
        )
        _write_status(
            root,
            source_index=source_index,
            source_sha256=source_sha256,
            state="complete",
            detail="reused canonical checkpoint",
        )
        return cached

    try:
        raw_checkpoint = _load_raw_checkpoint(
            root,
            source_index=source_index,
            source_sha256=source_sha256,
        )
        if raw_checkpoint is not None:
            print(
                f"BodyRig recovery checkpoint: resuming {_segment_prefix(source_index)} from persistent PHALP output",
                file=sys.stderr,
            )
            tracks = _canonicalize_raw(
                raw_checkpoint,
                source=source,
                source_index=source_index,
            )
            canonical = _publish_canonical_checkpoint(
                root,
                source_index=source_index,
                source_sha256=source_sha256,
                tracks=tracks,
            )
            _write_status(
                root,
                source_index=source_index,
                source_sha256=source_sha256,
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
            state="running",
        )
        log_path = _log_path(root, source_index)
        with tempfile.TemporaryDirectory(prefix="bodyrig-4dh-") as temp_dir_raw:
            output_dir = Path(temp_dir_raw) / "output"
            command = base._track_command(repo, source, output_dir)
            if source.suffix.lower() == ".mp4":
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
            # still reusable on the next invocation.
            persistent_raw = _publish_raw_checkpoint(
                root,
                source_index=source_index,
                source_sha256=source_sha256,
                source_pkl=pkls[0],
            )
            frame_results = joblib.load(persistent_raw)
            if not isinstance(frame_results, dict):
                raise RuntimeError("unexpected PHALP result shape")
            tracks = _canonicalize_raw(
                frame_results,
                source=source,
                source_index=source_index,
            )
            canonical = _publish_canonical_checkpoint(
                root,
                source_index=source_index,
                source_sha256=source_sha256,
                tracks=tracks,
            )

        _write_status(
            root,
            source_index=source_index,
            source_sha256=source_sha256,
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
                state="failed",
                detail=str(exc),
            )
        except Exception:
            pass
        raise


def main() -> int:
    # Keep every authority/preflight rule in the pinned bridge. Replace only the
    # expensive per-source execution boundary with the crash-resilient runner.
    base._run_source = _checkpointing_run_source
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
