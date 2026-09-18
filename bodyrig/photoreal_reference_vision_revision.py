from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

MESH_ADAPTER_NAME = "photoreal_reference_vision_adapter_mesh.py"
MESH_ADAPTER_DEPENDENCIES = (
    "bodyrig/photoreal_cubemap_deprojection.py",
    "bodyrig/photoreal_equirectangular_deprojection.py",
    "bodyrig/photoreal_mesh_deprojection.py",
    "bodyrig/photoreal_mesh_projection.py",
    "bodyrig/photoreal_model_set.py",
    "bodyrig/photoreal_reference_vision_revision.py",
    "bodyrig/photoreal_wsl_request_bridge.py",
    "bodyrig/wsl_adapter_bridge.py",
    "tools/photoreal_reference_vision_adapter.py",
    "tools/photoreal_reference_vision_adapter_mesh.py",
)


class PhotorealReferenceVisionRevisionError(ValueError):
    pass


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PhotorealReferenceVisionRevisionError(
            f"reference vision revision dependency is unreadable: {path}"
        ) from exc
    return digest.hexdigest()


def _composite_revision(root: Path, relative_paths: Iterable[str]) -> str:
    normalized = tuple(sorted(set(str(value).replace("\\", "/") for value in relative_paths)))
    if not normalized:
        raise PhotorealReferenceVisionRevisionError("reference vision revision dependency set is empty")
    digest = hashlib.sha256()
    for relative in normalized:
        candidate = (root / Path(relative)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise PhotorealReferenceVisionRevisionError(
                "reference vision revision dependency escapes repository root"
            ) from exc
        if not candidate.is_file():
            raise PhotorealReferenceVisionRevisionError(
                f"reference vision revision dependency not found: {relative}"
            )
        try:
            raw = candidate.read_bytes()
        except OSError as exc:
            raise PhotorealReferenceVisionRevisionError(
                f"reference vision revision dependency is unreadable: {relative}"
            ) from exc
        label = relative.encode("utf-8")
        digest.update(len(label).to_bytes(4, "big"))
        digest.update(label)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def compute_reference_vision_revision(adapter_path: str | Path) -> str:
    adapter = Path(adapter_path).expanduser().resolve()
    if not adapter.is_file():
        raise PhotorealReferenceVisionRevisionError(
            f"reference vision adapter not found: {adapter}"
        )

    # Preserve the legacy single-file revision for arbitrary/test adapters and the
    # legacy base adapter. The production reference entrypoint is the mesh wrapper,
    # whose behavior spans the explicit dependency set below.
    if adapter.name != MESH_ADAPTER_NAME:
        return _file_sha256(adapter)

    if adapter.parent.name != "tools":
        raise PhotorealReferenceVisionRevisionError(
            "mesh reference adapter must live in the repository tools directory"
        )
    root = adapter.parent.parent.resolve()
    expected_adapter = (root / "tools" / MESH_ADAPTER_NAME).resolve()
    if adapter != expected_adapter:
        raise PhotorealReferenceVisionRevisionError(
            "mesh reference adapter path does not match canonical repository entrypoint"
        )
    return _composite_revision(root, MESH_ADAPTER_DEPENDENCIES)
