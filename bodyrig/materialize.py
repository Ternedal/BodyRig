from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .appearance_boundary import AppearanceBoundaryError, validate_pipeline
from .package import MRBodyError, validate_package

RUNTIME_MANIFEST = "runtime-manifest.json"


@dataclass(frozen=True)
class MaterializedRuntime:
    root: Path
    avatar: Path
    bodyprint: Path
    manifest: dict


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _require_production_appearance_boundary(provenance: dict) -> None:
    pipeline = provenance.get("pipeline")
    if not isinstance(pipeline, list):
        return
    fitting = next(
        (
            stage
            for stage in pipeline
            if isinstance(stage, dict) and stage.get("stage") == "avatar-fitting"
        ),
        None,
    )
    if not isinstance(fitting, dict):
        return
    if fitting.get("adapter") != "sith-smplx-vrm" or fitting.get("revision") != "1":
        return
    try:
        validate_pipeline(pipeline)
    except AppearanceBoundaryError as exc:
        raise MRBodyError(
            f"runtime materialization rejected invalid appearance boundary: {exc}"
        ) from exc


def materialize_runtime(
    package_path: str | os.PathLike[str],
    destination: str | os.PathLike[str],
) -> MaterializedRuntime:
    """Materialize only validated portable runtime payloads from one .mrbody.

    The destination must not already exist. This keeps a renderer from silently
    reusing stale assets from another package and makes the materialized tree an
    immutable consequence of one validated package hash.
    """

    package = Path(package_path).expanduser().resolve()
    validated = validate_package(package)
    _require_production_appearance_boundary(validated.provenance)
    target = Path(destination).expanduser().resolve()
    if target.exists():
        raise MRBodyError(f"runtime destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    package_sha256 = _sha256_file(package)
    payload_names = tuple(validated.payload_names)

    temp = Path(
        tempfile.mkdtemp(
            prefix=target.name + ".",
            suffix=".tmp",
            dir=target.parent,
        )
    )
    try:
        with zipfile.ZipFile(package, "r") as archive:
            for name in payload_names:
                out = temp.joinpath(*name.split("/"))
                out.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read(name)
                with out.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())

        avatar_path = temp / "avatar.vrm"
        bodyprint_path = temp / "bodyprint.json"
        if not avatar_path.is_file() or not bodyprint_path.is_file():
            raise MRBodyError("materialized runtime is missing required avatar/bodyprint payload")

        runtime_manifest = {
            "format": "bodyrig-runtime-assets",
            "version": 1,
            "body_id": validated.manifest["id"],
            "body_name": validated.manifest["name"],
            "package_sha256": package_sha256,
            "avatar": "avatar.vrm",
            "avatar_sha256": _sha256_file(avatar_path),
            "bodyprint": "bodyprint.json",
            "bodyprint_sha256": _sha256_file(bodyprint_path),
            "payloads": list(payload_names),
        }

        manifest_path = temp / RUNTIME_MANIFEST
        with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(
                runtime_manifest,
                stream,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temp, target)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise

    return MaterializedRuntime(
        root=target,
        avatar=target / "avatar.vrm",
        bodyprint=target / "bodyprint.json",
        manifest=runtime_manifest,
    )