from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

FORMAT = "bodyrig-photoreal-analyzer-model-set"
VERSION = 1
MAX_FILES = 10_000


class PhotorealModelSetError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(files: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        {"format": FORMAT, "version": VERSION, "files": files},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_model_set(root: str | Path) -> dict[str, Any]:
    model_root = Path(root).expanduser().resolve()
    if not model_root.is_dir():
        raise PhotorealModelSetError(f"photoreal analyzer model-set root is not a directory: {model_root}")

    paths = sorted(
        (path for path in model_root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(model_root).as_posix(),
    )
    if not paths:
        raise PhotorealModelSetError("photoreal analyzer model-set root contains no files")
    if len(paths) > MAX_FILES:
        raise PhotorealModelSetError(f"photoreal analyzer model set exceeds safety bound {MAX_FILES}")

    records: list[dict[str, Any]] = []
    total_bytes = 0
    for path in paths:
        if path.is_symlink():
            raise PhotorealModelSetError(f"photoreal analyzer model set must not contain symlinks: {path}")
        relative = path.relative_to(model_root).as_posix()
        if not relative or relative.startswith("../") or "\\" in relative:
            raise PhotorealModelSetError(f"photoreal analyzer model path is invalid: {relative}")
        size = path.stat().st_size
        if size < 1:
            raise PhotorealModelSetError(f"photoreal analyzer model asset is empty: {relative}")
        total_bytes += size
        records.append({"path": relative, "size_bytes": size, "sha256": _sha256(path)})

    model_set_sha256 = _canonical_digest(records)
    return {
        "format": FORMAT,
        "version": VERSION,
        "file_count": len(records),
        "total_bytes": total_bytes,
        "files": records,
        "model_set_sha256": model_set_sha256,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def write_model_set(root: str | Path, output_path: str | Path) -> dict[str, Any]:
    result = build_model_set(root)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealModelSetError(f"photoreal analyzer model-set manifest already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
