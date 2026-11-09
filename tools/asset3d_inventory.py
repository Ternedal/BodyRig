"""Offline, fail-closed inventory of externally sourced 3D assets.

No Blender loading, network calls or embedded script execution occurs here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXTENSIONS = {".blend", ".fbx", ".obj", ".glb", ".gltf"}
ALLOWED_LICENSES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0"}


def inventory(root: Path, provenance: dict) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("root must be a directory")
    entries = []
    seen = set()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink prohibited: {path}")
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        rel = path.relative_to(root).as_posix()
        source = provenance.get(rel)
        if not isinstance(source, dict):
            raise ValueError(f"missing provenance: {rel}")
        if source.get("license") not in ALLOWED_LICENSES:
            raise ValueError(f"unapproved license: {rel}")
        if not source.get("url") or not source.get("rights_verified"):
            raise ValueError(f"unverified rights/source: {rel}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        sha = digest.hexdigest()
        entries.append({"path": rel, "format": path.suffix.lower()[1:],
                        "bytes": path.stat().st_size, "sha256": sha,
                        "duplicate": sha in seen, "provenance": source})
        seen.add(sha)
    return {"schema_version": 1, "assets": entries}


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
