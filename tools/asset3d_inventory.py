"""Offline fail-closed inventory for untrusted 3D assets. Does not execute assets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

EXTENSIONS = {".blend", ".fbx", ".obj", ".glb", ".gltf"}
ALLOWED_LICENSES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0"}
REPARSE_POINT = 0x400


def _safe_file(root: Path, path: Path) -> Path:
    if path.is_symlink() or (path.lstat().st_file_attributes & REPARSE_POINT if os.name == "nt" else False):
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
                            # Complex MTL option syntax cannot safely be resolved here.
                            if len(parts) != 2:
                                raise ValueError("unsupported MTL texture syntax")
                            tex = _reference(root, mtl.parent, parts[1])
                            if tex:
                                paths.add(tex)
    return [{"path": p.relative_to(root).as_posix(), "sha256": _hash(p), "bytes": p.stat().st_size}
            for p in sorted(paths)]


def _validate_source(source: object, rel: str) -> dict:
    if not isinstance(source, dict):
        raise ValueError(f"missing provenance: {rel}")
    if source.get("license") not in ALLOWED_LICENSES:
        raise ValueError(f"unapproved license: {rel}")
    url = source.get("url")
    if not isinstance(url, str) or urlsplit(url).scheme != "https" or not urlsplit(url).netloc:
        raise ValueError(f"invalid source URL: {rel}")
    if source.get("rights_verified") is not True:
        raise ValueError(f"rights not verified: {rel}")
    if type(source.get("depicts_human")) is not bool:
        raise ValueError(f"human classification missing: {rel}")
    if source["depicts_human"]:
        if (source.get("depicts_real_person") is not False or
                source.get("adult_only_attested") is not True or
                source.get("third_party_character") is not False or
                not isinstance(source.get("age_statement"), str) or
                not source["age_statement"].strip()):
            raise ValueError(f"human asset authority not verified: {rel}")
    if source["license"] in {"CC-BY-4.0", "CC-BY-SA-4.0"}:
        if not source.get("author") or not source.get("attribution"):
            raise ValueError(f"attribution missing: {rel}")
    return source


def inventory(root: Path, provenance: dict) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir() or not isinstance(provenance, dict):
        raise ValueError("root must be directory and provenance must be object")
    entries = []
    seen = set()
    matched = set()
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
            source = _validate_source(provenance.get(rel), rel)
            sha = _hash(path)
            entries.append({"path": rel, "format": path.suffix.lower()[1:],
                            "bytes": path.stat().st_size, "sha256": sha,
                            "duplicate": sha in seen, "dependencies": _dependencies(root, path),
                            "provenance": source,
                            "share_alike": source["license"] == "CC-BY-SA-4.0",
                            "likeness_authority": False})
            seen.add(sha)
            matched.add(rel)
    unmatched = sorted(set(provenance) - matched)
    if unmatched:
        raise ValueError(f"unmatched provenance: {unmatched}")
    return {"schema_version": 1, "likeness_authority": False,
            "assets": sorted(entries, key=lambda entry: entry["path"])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("provenance_json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    provenance = json.loads(args.provenance_json.read_text(encoding="utf-8"))
    result = inventory(args.root, provenance)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
