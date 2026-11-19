"""Copy Stash-selected originals into a private, self-contained local snapshot.

Phase 1 (needs Stash and the source share): selection, then ``stage()``.
Phase 2 (offline): every later step reads only the snapshot that ``stage()``
returns. The PowerShell launcher sets ``BODYRIG_STASH_OFFLINE=1`` after staging,
so any Stash GraphQL call from phase 2 fails closed (see ``stash_source``).

Each original is read exactly once over the share: it is hashed while it is
copied, the local copy is hashed again from local disk, and the two must match.
A size + mtime check before and after the copy catches an original that changes
mid-copy. The snapshot carries an ownership marker, so a later run can remove a
snapshot or temp directory left behind by a killed run -- and never anything
else.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

CHUNK = 4 * 1024 * 1024
MARKER_NAME = ".bodyrig-local-source-snapshot"
MARKER = {"format": "bodyrig-local-source-snapshot-marker", "version": 1}
TEMP_PREFIX = ".bodyrig-staging-"
MIN_FREE_MARGIN_BYTES = 256 * 1024 * 1024
SAFE_EXTENSION = re.compile(r"\.[a-z0-9]{1,8}")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def required_free_bytes(total_bytes):
    """Space to reserve: the sources plus a margin for manifests and filesystem slack."""
    return total_bytes + max(total_bytes // 20, MIN_FREE_MARGIN_BYTES)


def _safe_extension(original):
    extension = original.suffix.lower()
    return extension if SAFE_EXTENSION.fullmatch(extension) else ".bin"


def _write_marker(directory):
    (directory / MARKER_NAME).write_text(json.dumps(MARKER, sort_keys=True) + "\n", encoding="utf-8")


def _has_marker(directory):
    try:
        return json.loads((directory / MARKER_NAME).read_text(encoding="utf-8")) == MARKER
    except (OSError, ValueError):
        return False


def _copy_hashing(original, target):
    """Copy ``original`` to a new ``target`` in one read; return the SHA-256 of the bytes read."""
    h = hashlib.sha256()
    with original.open("rb") as src, target.open("xb") as dst:
        for chunk in iter(lambda: src.read(CHUNK), b""):
            h.update(chunk)
            dst.write(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    return h.hexdigest()


def cleanup_stale(destination):
    """Remove a snapshot and temp directories that a killed earlier run left behind.

    Only directories that carry the BodyRig ownership marker are removed. An
    existing destination without the marker raises instead of being deleted.
    Returns the number of directories removed.
    """
    root = Path(destination).resolve()
    removed = 0
    if root.exists():
        if not root.is_dir() or not _has_marker(root):
            raise FileExistsError(f"Refusing to remove {root}: it is not a BodyRig local source snapshot")
        shutil.rmtree(root)
        removed += 1
    if root.parent.is_dir():
        for temp in root.parent.glob(TEMP_PREFIX + "*"):
            if temp.is_dir() and _has_marker(temp):
                shutil.rmtree(temp, ignore_errors=True)
                removed += 1
    return removed


def stage(manifest_path, destination, *, timing_out=None):
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
    temp = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=root.parent))
    try:
        _write_marker(temp)
        seen_sources = set()
        originals = []
        total_bytes = 0
        for item in selected:
            original = Path(item["path"]).resolve(strict=True)
            if original in seen_sources:
                raise ValueError(f"Duplicate source path: {original}")
            seen_sources.add(original)
            if not original.is_file():
                raise ValueError(f"Not a file: {original}")
            if root == original or root in original.parents:
                raise ValueError("Snapshot destination overlaps input")
            total_bytes += original.stat().st_size
            originals.append(original)
        free_bytes = shutil.disk_usage(root.parent).free
        needed = required_free_bytes(total_bytes)
        if needed > free_bytes:
            raise OSError(f"Insufficient snapshot disk space: need {needed} bytes "
                          f"({total_bytes} for sources plus margin), have {free_bytes} bytes")
        copy_seconds = verify_seconds = 0.0
        copied_bytes = 0
        for index, (item, original) in enumerate(zip(selected, originals), 1):
            filename = f"source-{index:02d}{_safe_extension(original)}"
            target = temp / filename
            before = original.stat()
            started = time.perf_counter()
            read_hash = _copy_hashing(original, target)
            copy_seconds += time.perf_counter() - started
            after = original.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise IOError(f"Source changed during copy: {original}")
            if target.stat().st_size != before.st_size:
                raise IOError(f"Size mismatch: {original}")
            started = time.perf_counter()
            copied_hash = digest(target)
            verify_seconds += time.perf_counter() - started
            if copied_hash != read_hash:
                raise IOError(f"SHA256 mismatch: {original}")
            copied_bytes += before.st_size
            item["path"] = str(root / filename)
        (temp / "bodyrig-stash-source-manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temp, root)
        timing = {
            "format": "bodyrig-staging-timing",
            "version": 1,
            "staged": True,
            "files": len(originals),
            "bytes": copied_bytes,
            "copy_seconds": round(copy_seconds, 3),
            "verify_seconds": round(verify_seconds, 3),
        }
        mib = copied_bytes / (1024 * 1024)
        rate = mib / copy_seconds if copy_seconds > 0 else 0.0
        print(f"Stash local staging: {len(originals)} files, {mib:.1f} MiB; copy {copy_seconds:.2f} s "
              f"({rate:.1f} MiB/s, one read of each original), local SHA256 verify {verify_seconds:.2f} s", flush=True)
        if timing_out is not None:
            Path(timing_out).write_text(json.dumps(timing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return root / "bodyrig-stash-source-manifest.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest")
    parser.add_argument("--destination", required=True)
    parser.add_argument("--timing-out", help="write copy/verify timing JSON (no paths) to this file")
    parser.add_argument("--cleanup-stale", action="store_true",
                        help="only remove a marked snapshot/temp directory left by an earlier run, then exit")
    args = parser.parse_args()
    if args.cleanup_stale:
        print(f"Stale BodyRig source snapshots removed: {cleanup_stale(args.destination)}")
        return
    if not args.manifest:
        parser.error("--manifest is required unless --cleanup-stale is given")
    print(stage(args.manifest, args.destination, timing_out=args.timing_out))


if __name__ == "__main__":
    main()
