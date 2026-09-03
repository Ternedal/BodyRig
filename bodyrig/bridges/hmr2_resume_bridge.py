#!/usr/bin/env python
"""Cross-job resume layer for the pinned crash-resilient PHALP bridge.

The checkpoint bridge keeps authoritative per-workspace evidence beside
observation segments. This wrapper adds a content-addressed cache for the *raw*
PHALP result only. Raw PHALP output is independent of BodyRig's source index;
source-local BodyRig track ids are added later during canonicalization.

Cache reuse therefore requires exact source bytes, the exact pinned recovery
adapter revision, and the exact recovery-only temporal sampling stride.
Canonical checkpoints, status and logs remain workspace-local.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

_PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(_PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_PARENT))

from bodyrig.bridges import hmr2_checkpoint_bridge as checkpoint  # noqa: E402
from bodyrig.bridges.hmr2_config import (  # noqa: E402
    ADAPTER_NAME,
    ADAPTER_REVISION,
    RECOVERY_TEMPORAL_SAMPLING_POLICY,
)

GLOBAL_FORMAT = "bodyrig-recovery-global-phalp-cache"
GLOBAL_VERSION = 2
_GLOBAL_DIR = "recovery-phalp-cache"

_legacy_load_raw_checkpoint = checkpoint._load_raw_checkpoint
_legacy_publish_raw_checkpoint = checkpoint._publish_raw_checkpoint


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _revision_namespace() -> str:
    return hashlib.sha256(ADAPTER_REVISION.encode("utf-8")).hexdigest()[:24]


def _global_root() -> Path:
    override = os.environ.get("BODYRIG_RECOVERY_CACHE_DIR", "").strip()
    if override:
        root = Path(override).expanduser()
    else:
        xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
        root = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
        root = root / "bodyrig" / _GLOBAL_DIR
    root = root.resolve() / _revision_namespace()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _global_paths(source_sha256: str) -> tuple[Path, Path]:
    root = _global_root() / source_sha256[:2] / source_sha256
    return root / "phalp.pkl", root / "meta.json"


def _valid_global_meta(
    meta: Any,
    *,
    source_sha256: str,
    sampling_stride: int,
    pkl_path: Path,
) -> bool:
    if not isinstance(meta, dict):
        return False
    if meta.get("format") != GLOBAL_FORMAT or meta.get("version") != GLOBAL_VERSION:
        return False
    if meta.get("adapter") != ADAPTER_NAME or meta.get("revision") != ADAPTER_REVISION:
        return False
    if meta.get("sampling_policy") != RECOVERY_TEMPORAL_SAMPLING_POLICY:
        return False
    if meta.get("sampling_stride") != sampling_stride:
        return False
    if meta.get("source_sha256") != source_sha256 or not pkl_path.is_file():
        return False
    expected = str(meta.get("pkl_sha256") or "").strip().lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        return False
    try:
        return _sha256_file(pkl_path) == expected
    except OSError:
        return False


def _load_global_raw(source_sha256: str, *, sampling_stride: int):
    pkl_path, meta_path = _global_paths(source_sha256)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not _valid_global_meta(
        meta,
        source_sha256=source_sha256,
        sampling_stride=sampling_stride,
        pkl_path=pkl_path,
    ):
        return None
    try:
        import joblib

        value = joblib.load(pkl_path)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _publish_global_file(
    *,
    source_sha256: str,
    sampling_stride: int,
    source_pkl: Path,
) -> Path:
    pkl_path, meta_path = _global_paths(source_sha256)
    pkl_path.parent.mkdir(parents=True, exist_ok=True)

    # Never rewrite already-valid content-addressed evidence.
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        meta = None
    if _valid_global_meta(
        meta,
        source_sha256=source_sha256,
        sampling_stride=sampling_stride,
        pkl_path=pkl_path,
    ):
        return pkl_path

    temp = pkl_path.with_name(f".{pkl_path.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(source_pkl, temp)
        pkl_sha256 = _sha256_file(temp)
        os.replace(temp, pkl_path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass

    _atomic_write_json(
        meta_path,
        {
            "format": GLOBAL_FORMAT,
            "version": GLOBAL_VERSION,
            "adapter": ADAPTER_NAME,
            "revision": ADAPTER_REVISION,
            "sampling_policy": RECOVERY_TEMPORAL_SAMPLING_POLICY,
            "sampling_stride": sampling_stride,
            "source_sha256": source_sha256,
            "pkl_sha256": pkl_sha256,
        },
    )
    return pkl_path


def _observation_workspaces_root(local_checkpoint_root: Path) -> Path | None:
    for candidate in (local_checkpoint_root, *local_checkpoint_root.parents):
        if candidate.name == "observation-workspaces" and candidate.is_dir():
            return candidate
    return None


def _discover_legacy_raw(
    local_checkpoint_root: Path,
    *,
    source_sha256: str,
    sampling_stride: int,
):
    """Import a matching raw checkpoint from an older surviving workspace.

    Raw PHALP output has no BodyRig source-local id yet, so source_index is not
    part of cross-job reuse. Sampling identity *is* required because frame
    selection changes PHALP input and canonical timestamp spacing.
    """

    observation_root = _observation_workspaces_root(local_checkpoint_root)
    if observation_root is None:
        return None
    try:
        candidates = sorted(
            observation_root.glob("*/selected-segments/bodyrig-recovery-checkpoints/*.phalp.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None

    for meta_path in candidates[:500]:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        if meta.get("format") != checkpoint.RAW_META_FORMAT or meta.get("version") != checkpoint.CHECKPOINT_VERSION:
            continue
        if meta.get("adapter") != ADAPTER_NAME or meta.get("revision") != ADAPTER_REVISION:
            continue
        if meta.get("sampling_policy") != RECOVERY_TEMPORAL_SAMPLING_POLICY:
            continue
        if meta.get("sampling_stride") != sampling_stride:
            continue
        if meta.get("source_sha256") != source_sha256:
            continue
        raw_path = meta_path.with_suffix(".pkl")
        if not raw_path.is_file():
            continue
        try:
            import joblib

            value = joblib.load(raw_path)
        except Exception:
            continue
        if not isinstance(value, dict):
            continue
        _publish_global_file(
            source_sha256=source_sha256,
            sampling_stride=sampling_stride,
            source_pkl=raw_path,
        )
        return value
    return None


def _load_raw_checkpoint(
    root: Path,
    *,
    source_index: int,
    source_sha256: str,
    sampling_stride: int,
):
    # Current-workspace evidence wins and is also promoted into the global cache.
    current = _legacy_load_raw_checkpoint(
        root,
        source_index=source_index,
        source_sha256=source_sha256,
        sampling_stride=sampling_stride,
    )
    if current is not None:
        raw_path = checkpoint._raw_path(root, source_index)
        if raw_path.is_file():
            _publish_global_file(
                source_sha256=source_sha256,
                sampling_stride=sampling_stride,
                source_pkl=raw_path,
            )
        return current

    cached = _load_global_raw(source_sha256, sampling_stride=sampling_stride)
    if cached is not None:
        print(
            f"BodyRig recovery cache: reusing raw PHALP result for source SHA {source_sha256[:12]} "
            f"with stride={sampling_stride}",
            file=sys.stderr,
        )
        return cached

    discovered = _discover_legacy_raw(
        root,
        source_sha256=source_sha256,
        sampling_stride=sampling_stride,
    )
    if discovered is not None:
        print(
            f"BodyRig recovery cache: imported raw PHALP result from an older observation workspace "
            f"for {source_sha256[:12]} with stride={sampling_stride}",
            file=sys.stderr,
        )
        return discovered
    return None


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
    local = _legacy_publish_raw_checkpoint(
        root,
        source_index=source_index,
        source_sha256=source_sha256,
        source_fps=source_fps,
        sampling_stride=sampling_stride,
        effective_fps=effective_fps,
        source_pkl=source_pkl,
    )
    _publish_global_file(
        source_sha256=source_sha256,
        sampling_stride=sampling_stride,
        source_pkl=local,
    )
    return local


def main() -> int:
    checkpoint._load_raw_checkpoint = _load_raw_checkpoint
    checkpoint._publish_raw_checkpoint = _publish_raw_checkpoint
    return checkpoint.main()


if __name__ == "__main__":
    raise SystemExit(main())
