"""Offline inventory of local 3D assets. Never executes embedded asset code."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

EXTENSIONS = {".blend", ".fbx", ".obj", ".glb", ".gltf"}
REPARSE_POINT = 0x400


def _safe_file(root: Path, path: Path) -> Path:
    if path.is_symlink() or (os.name == "nt" and path.lstat().st_file_attributes & REPARSE_POINT):
        raise ValueError(f"link/reparse point prohibited: {path}")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"unsafe file path: {path}")
    return resolved


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reference(root: Path, parent: Path, uri: str) -> Path | None:
    if not isinstance(uri, str) or not uri:
        raise ValueError("invalid dependency URI")
    if uri.startswith("data:"):
        return None
    parsed = urlsplit(uri)
    decoded = unquote(uri)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "\\" in decoded:
        raise ValueError(f"external/unsafe dependency: {uri}")
    rel = PurePosixPath(decoded)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError(f"path traversal dependency: {uri}")
    return _safe_file(root, parent / decoded)


def _dependencies(root: Path, path: Path) -> list[dict]:
    paths: set[Path] = set()
    if path.suffix.lower() == ".gltf":
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("invalid glTF document")
        for section in ("buffers", "images"):
            for item in document.get(section, []):
                if not isinstance(item, dict):
                    raise ValueError("invalid glTF reference")
                if "uri" in item:
                    dependency = _reference(root, path.parent, item["uri"])
                    if dependency:
                        paths.add(dependency)
    elif path.suffix.lower() == ".obj":
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            tokens = line.strip().split(maxsplit=1)
            if tokens and tokens[0].lower() == "mtllib":
                if len(tokens) != 2:
                    raise ValueError("empty mtllib")
                mtl = _reference(root, path.parent, tokens[1])
                if mtl:
                    paths.add(mtl)
                    for material_line in mtl.read_text(encoding="utf-8", errors="replace").splitlines():
                        parts = material_line.strip().split()
                        if parts and (parts[0].lower().startswith("map_") or parts[0].lower() in {"bump", "disp", "decal", "refl"}):
                            if len(parts) != 2:
                                raise ValueError("unsupported MTL texture syntax")
                            tex = _reference(root, mtl.parent, parts[1])
                            if tex:
                                paths.add(tex)
    return [{"path": p.relative_to(root).as_posix(), "sha256": _hash(p), "bytes": p.stat().st_size}
            for p in sorted(paths)]


def inventory(root: Path, provenance: dict | None = None) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("root must be a directory")
    if provenance is None:
        provenance = {}
    if not isinstance(provenance, dict):
        raise ValueError("provenance must be a JSON object")
    entries = []
    seen = set()
    for current, dirs, files in os.walk(root, followlinks=False):
        parent = Path(current)
        for name in dirs + files:
            candidate = parent / name
            if candidate.is_symlink() or (os.name == "nt" and candidate.lstat().st_file_attributes & REPARSE_POINT):
                raise ValueError(f"link/reparse point prohibited: {candidate}")
            if not candidate.resolve(strict=True).is_relative_to(root):
                raise ValueError(f"path escapes root: {candidate}")
        for name in sorted(files):
            path = parent / name
            if path.suffix.lower() not in EXTENSIONS:
                continue
            path = _safe_file(root, path)
            rel = path.relative_to(root).as_posix()
            source = provenance.get(rel)
            if source is not None and not isinstance(source, dict):
                raise ValueError(f"invalid provenance object: {rel}")
            source = source or {}
            sha = _hash(path)
            entries.append({"path": rel, "format": path.suffix.lower()[1:],
                            "bytes": path.stat().st_size, "sha256": sha,
                            "duplicate": sha in seen, "dependencies": _dependencies(root, path),
                            "provenance": source, "provenance_status": "provided" if source else "unknown",
                            "share_alike": source.get("license") == "CC-BY-SA-4.0",
                            "likeness_authority": False, "readiness": "INVENTORIED"})
            seen.add(sha)
    return {"schema_version": 2, "likeness_authority": False,
            "assets": sorted(entries, key=lambda entry: entry["path"])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("provenance_json", type=Path, nargs="?")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    provenance = (json.loads(args.provenance_json.read_text(encoding="utf-8"))
                  if args.provenance_json else None)
    result = inventory(args.root, provenance)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
