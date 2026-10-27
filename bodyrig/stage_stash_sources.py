"""Copy Stash-selected originals into a private, self-contained local snapshot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def stage(manifest_path, destination):
    source = Path(manifest_path).resolve()
    root = Path(destination).resolve()
    manifest = json.loads(source.read_text(encoding="utf-8-sig"))
    if manifest.get("format") != "bodyrig-stash-source-manifest" or manifest.get("version") != 1:
        raise ValueError("Unexpected source manifest format/version")
    selected = manifest.get("selected")
    if not isinstance(selected, list) or not 1 <= len(selected) <= 10:
        raise ValueError("Expected 1..10 selected source files")
    if root == source or root in source.parents:
        raise ValueError("Snapshot destination overlaps manifest")
    if root.exists():
        raise FileExistsError(f"Snapshot destination already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".bodyrig-staging-", dir=root.parent))
    try:
        for index, item in enumerate(selected, 1):
            original = Path(item["path"]).resolve(strict=True)
            if not original.is_file():
                raise ValueError(f"Not a file: {original}")
            if root == original or root in original.parents:
                raise ValueError("Snapshot destination overlaps input")
            extension = original.suffix.lower()
            filename = f"source-{index:02d}{extension}"
            target = temp / filename
            shutil.copyfile(original, target)
            if target.stat().st_size != original.stat().st_size:
                raise IOError(f"Size mismatch: {original}")
            original_hash = digest(original)
            copied_hash = digest(target)
            if copied_hash != original_hash:
                raise IOError(f"SHA256 mismatch: {original}")
            item["path"] = str(root / filename)
        (temp / "bodyrig-stash-source-manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temp, root)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return root / "bodyrig-stash-source-manifest.json"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    print(stage(args.manifest, args.destination))

if __name__ == "__main__":
    main()
