"""Offline inventory of local 3D assets. Never executes embedded asset code."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import time
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

EXTENSIONS = {".blend", ".fbx", ".obj", ".glb", ".gltf"}
REPARSE_POINT = 0x400
MAX_SCENE_JSON_BYTES = 16 * 1024 * 1024


def _safe_file(root: Path, path: Path) -> Path:
    # Check every component, not only the leaf: a linked parent can redirect
    # an otherwise ordinary dependency outside its intended directory.
    for component in (path, *path.parents):
        if component == root.parent:
            break
        if component.is_symlink() or (os.name == "nt" and component.lstat().st_file_attributes & REPARSE_POINT):
            raise ValueError(f"link/reparse point prohibited: {component}")
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


def _mtl_texture_reference(line: str) -> str:
    """Parse common Wavefront MTL options and retain filenames with spaces."""
    args = line.strip().split()[1:]
    i = 0
    one = {"-blendu", "-blendv", "-cc", "-clamp", "-texres", "-imfchan", "-bm", "-boost", "-type"}
    while i < len(args) and args[i].startswith("-"):
        option = args[i].lower()
        if option in one:
            count = 1
        elif option == "-mm":
            count = 2
        elif option in {"-o", "-s", "-t"}:
            count = 0
            for candidate in args[i + 1:i + 4]:
                try:
                    float(candidate)
                except ValueError:
                    break
                count += 1
            if count == 0:
                raise ValueError("invalid MTL vector option")
        else:
            raise ValueError(f"unsupported MTL option: {option}")
        i += 1 + count
        if i > len(args):
            raise ValueError("truncated MTL option")
    filename = " ".join(args[i:])
    if not filename:
        raise ValueError("missing MTL texture filename")
    return filename


def _dependencies(root: Path, path: Path) -> list[dict]:
    paths: set[Path] = set()
    if path.suffix.lower() in {".gltf", ".glb"}:
        if path.suffix.lower() == ".glb":
            with path.open("rb") as stream:
                header = stream.read(20)
                if len(header) != 20:
                    raise ValueError("truncated GLB header")
                magic, version, total_length, chunk_length, chunk_type = struct.unpack("<4sIIII", header)
                if magic != b"glTF" or version != 2 or chunk_type != 0x4E4F534A:
                    raise ValueError("invalid GLB header or first JSON chunk")
                if (total_length != path.stat().st_size or chunk_length > total_length - 20
                        or chunk_length > MAX_SCENE_JSON_BYTES):
                    raise ValueError("invalid GLB length")
                document = json.loads(stream.read(chunk_length).decode("utf-8"))
        else:
            if path.stat().st_size > MAX_SCENE_JSON_BYTES:
                raise ValueError("glTF JSON exceeds size limit")
            document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("invalid glTF document")
        for section in ("buffers", "images"):
            items = document.get(section, [])
            if not isinstance(items, list):
                raise ValueError(f"invalid glTF {section}: expected array")
            for item in items:
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
                raw = tokens[1].replace(chr(92), "/")
                try:
                    mtls = [_reference(root, path.parent, raw)]
                except FileNotFoundError:
                    mtls = [_reference(root, path.parent, item) for item in raw.split()]
                for mtl in mtls:
                    if mtl is None:
                        continue
                    paths.add(mtl)
                    for material_line in mtl.read_text(encoding="utf-8", errors="replace").splitlines():
                        parts = material_line.strip().split()
                        if parts and (parts[0].lower().startswith("map_") or parts[0].lower() in {"bump", "disp", "decal", "refl"}):
                            filename = _mtl_texture_reference(material_line)
                            if len(filename) >= 2 and filename[1] == ":":
                                raise ValueError("absolute MTL texture path prohibited")
                            tex = _reference(root, mtl.parent, filename.replace(chr(92), "/"))
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
    started_ns = time.perf_counter_ns()
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
            asset_started_ns = time.perf_counter_ns()
            try:
                sha = _hash(path)
                dependencies = _dependencies(root, path)
                status, reasons = "ok", []
            except FileNotFoundError as exc:
                sha, dependencies = _hash(path), []
                status, reasons = "degraded", [f"missing dependency: {exc.filename}"]
            except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
                sha, dependencies = None, []
                status, reasons = "rejected", [f"{type(exc).__name__}: {exc}"]
            entries.append({"path": rel, "format": path.suffix.lower()[1:],
                            "bytes": path.stat().st_size, "sha256": sha,
                            "duplicate": sha in seen if sha is not None else False,
                            "dependencies": dependencies, "status": status, "reasons": reasons,
                            "inventory_ms": round((time.perf_counter_ns() - asset_started_ns) / 1_000_000, 3),
                            "provenance": source, "provenance_status": "provided" if source else "unknown",
                            "share_alike": source.get("license") == "CC-BY-SA-4.0",
                            "likeness_authority": False, "readiness": "INVENTORIED"})
            if sha is not None:
                seen.add(sha)
    return {"schema_version": 2, "inventory_total_ms": round((time.perf_counter_ns() - started_ns) / 1_000_000, 3),
            "likeness_authority": False,
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
