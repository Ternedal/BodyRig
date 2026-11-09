"""Isolated Blender scene inspection: progressive readiness, content-addressed cache (#1393).

One asset (BLEND, FBX, OBJ, GLB, glTF) goes through these states:

``DISCOVERED``
    The path is inside the source root, no component is a symlink or Windows
    reparse point, the file is regular and the format is supported.
``SAFE_TO_INSPECT``
    The dependency closure Blender needs (glTF/GLB external buffers and images,
    the OBJ material library) is resolved with strict relative references
    only. A reference that leaves the asset's folder fails the asset here,
    before anything is copied or executed.
``MINIMUM_READY``
    Header metadata read without Blender (glTF/GLB counts, OBJ element counts,
    FBX/BLEND versions). ``scene.json`` is written at this point, so a consumer
    can show the asset within seconds while Blender is still working.
``FULLY_ANALYZED``
    A headless Blender worker read a staged private copy and reported meshes,
    armatures and bones, shape keys, materials, images and animation clips,
    plus optional pose/depth/normal conditioning outputs.

Any failure gives ``FAILED`` for that asset only, with a code and message.

Results are cached by the asset hash, the hashes of its staged dependencies,
the worker script hash, the Blender version and the output-affecting
options. A cached repeat hashes (memoised by size and mtime) and copies; it
does not start Blender.

What the isolation is, honestly:

- always: a private staging copy verified by hash after copying, a scrubbed
  environment (empty Blender user dirs and HOME, a dead proxy, no GPU
  devices visible), Blender with ``--background --factory-startup
  --disable-autoexec`` (or the bpy module with the same settings applied in
  the worker), a wall-clock limit, a memory limit, process-tree kill, and
  removal of the staging copy afterwards;
- Windows: a Job Object (see ``bodyrig.process_limits``). Blender can still
  read any file the user can read and can still open network connections;
  ``--offline-mode`` only stops Blender's own online features;
- Linux/WSL2 with bubblewrap: file-system access is limited to read-only
  system directories, the Blender/Python install and the job directory, and
  the network namespace is unshared.

``--disable-autoexec`` is not a sandbox. Every result says which isolation
was actually applied. ``likeness_authority`` is always false: a scene
inspection is never identity evidence (#817).
"""

from __future__ import annotations

import gzip
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlsplit

from bodyrig import hashing, json_io
from bodyrig.process_limits import CancelledRun, Limits, run_bounded, tail

SCHEMA = "bodyrig-scene-inspection-v1"
BATCH_SCHEMA = "bodyrig-scene-inspection-batch-v1"
WORKER_CONTRACT = "bodyrig-scene-worker-v1"
INSPECTOR_VERSION = 1
FORMATS = {".blend": "blend", ".fbx": "fbx", ".obj": "obj", ".glb": "glb", ".gltf": "gltf"}
CONDITIONING = ("pose", "openpose", "depth", "normal")
CONDITIONING_FILES = {"pose": ("pose.json", "pose.png"), "openpose": ("openpose.json", "openpose.png"),
                      "depth": ("depth.png",), "normal": ("normal.png",)}
MAX_FRAMES = 600
# The only file names a cache entry or an output folder may ever hold besides scene.json.
OUTPUT_FILES = frozenset(name for names in CONDITIONING_FILES.values() for name in names)
# A frame sequence adds "f<6-digit index>_" in front of the same names; nothing else is ever allowed.
_OUTPUT_NAME = re.compile(r"(?:f[0-9]{6}_)?(?:" + "|".join(re.escape(n) for n in sorted(OUTPUT_FILES)) + r")")


def is_output_name(name: object) -> bool:
    """An exact allowlisted conditioning file name: no folder, no ``..``, no other file."""
    return isinstance(name, str) and _OUTPUT_NAME.fullmatch(name) is not None  # not "$": it accepts a final "\n"


_CACHE_KEY = re.compile(r"[0-9a-f]{64}")  # used with fullmatch: "$" would also accept a trailing newline
MTL_TEXTURE_STATEMENTS = ("map_", "bump", "disp", "decal", "refl", "norm")
ISOLATION_MODES = ("auto", "bwrap", "none")
WORKER_SCRIPT = Path(__file__).with_name("blender_scene_worker.py")
REPARSE_POINT = 0x400
# Prints the bpy version and exits without Blender's teardown (it hangs on Linux
# after some importers and crashes on os._exit on Windows).
MODULE_VERSION_PROBE = (
    "import bpy, os, sys; sys.stdout.write(bpy.app.version_string); sys.stdout.flush(); "
    "import ctypes; os.name == 'nt' and ctypes.windll.kernel32.TerminateProcess("
    "ctypes.c_void_p(-1), ctypes.c_uint(0)); os._exit(0)"
)
DEAD_PROXY = "http://127.0.0.1:9"
OBJ_COUNT_LIMIT_BYTES = 256 * 1024 * 1024
GIB = 1024 * 1024 * 1024
MIN_WORKER_SECONDS = 1.0
BUDGET_RERUN = "Re-run the same command to continue: finished assets come from the cache."
BUDGET_NOT_STARTED = "not started: the run's time budget was used up. " + BUDGET_RERUN
# #1393 fast-path targets. They are targets: a PASS on another machine says nothing about the rig.
SLO_TARGETS_MS = {
    "metadata": 5_000,          # identify, hash, header metadata (minimum_ready_at, p95)
    "analysis": 30_000,         # Blender scene inspection without conditioning (fully_analyzed_at, p95)
    "analysis_conditioning": 90_000,  # inspection 30 s + optional pose/depth/normal 60 s
    "first_usable": 120_000,    # first asset usable after the run started
    "cached": 2_000,            # a cached repeat (total, p95)
}


class SceneInspectionError(Exception):
    """A per-asset failure with a stable code; the batch continues."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SetupError(Exception):
    """The inspector itself cannot run (no Blender, bad options). Not per asset."""


class _InvalidAsset(SceneInspectionError):
    def __init__(self, message: str) -> None:
        super().__init__("invalid_asset", message)


@dataclass(frozen=True)
class InspectOptions:
    conditioning: tuple[str, ...] = ()
    frames: tuple[int, int, int] | None = None  # (start, end, step), end inclusive
    yaw_deg: float = 0.0  # conditioning camera orbit around Z; 0 = front, 180 = back
    resolution: int = 512
    wall_seconds: float = 120.0
    memory_bytes: int | None = 8 * GIB
    cpu_seconds: int | None = None
    threads: int = 2
    isolation: str = "auto"
    minimum_only: bool = False
    max_asset_bytes: int = 8 * GIB
    use_hash_memo: bool = True

    def validate(self) -> "InspectOptions":
        unknown = sorted(set(self.conditioning) - set(CONDITIONING))
        if unknown:
            raise SetupError(f"unknown conditioning output(s): {', '.join(unknown)}")
        if self.isolation not in ISOLATION_MODES:
            raise SetupError(f"isolation must be one of {', '.join(ISOLATION_MODES)}")
        if not 16 <= self.resolution <= 2048:
            raise SetupError("resolution must be between 16 and 2048")
        if self.wall_seconds <= 0 or self.threads <= 0:
            raise SetupError("timeout and threads must be positive")
        if not -360.0 <= float(self.yaw_deg) <= 360.0:
            raise SetupError("view yaw must be between -360 and 360 degrees")
        if self.frames is not None:
            start, end, step = self.frames
            if step < 1 or end < start:
                raise SetupError("frames must be START:END[:STEP] with END >= START and STEP >= 1")
            if len(range(start, end + 1, step)) > MAX_FRAMES:
                raise SetupError(f"at most {MAX_FRAMES} frames per asset")
            if not self.conditioning:
                raise SetupError("frames need at least one conditioning output")
        return replace(self, conditioning=tuple(sorted(set(self.conditioning))))

    def frame_list(self) -> list[int]:
        if self.frames is None:
            return []
        start, end, step = self.frames
        return list(range(start, end + 1, step))


def parse_frames(text: str) -> tuple[int, int, int] | None:
    """``START:END[:STEP]`` (inclusive) for --frames; empty means a single frame (the scene start)."""
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]), int(parts[1]), 1
        if len(parts) == 3:
            return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        pass
    raise SetupError(f"frames must be START:END[:STEP], got {text!r}")


@dataclass(frozen=True)
class BlenderRuntime:
    """How to start Blender: the ``blender`` executable ("cli") or a Python with ``bpy`` ("module")."""

    kind: str
    executable: Path
    version: str
    offline_flag: bool = False
    worker_script: Path = WORKER_SCRIPT

    def command(self, worker_args: Sequence[str], *, threads: int) -> list[str]:
        if self.kind == "cli":
            argv = [str(self.executable), "--background", "--factory-startup", "--disable-autoexec"]
            if self.offline_flag:
                argv.append("--offline-mode")
            argv += ["-noaudio", "--threads", str(threads), "--python-exit-code", "3",
                     "--python", str(self.worker_script), "--", *worker_args]
            return argv
        if self.kind == "module":
            return [str(self.executable), "-I", "-B", str(self.worker_script), "--", *worker_args]
        raise SetupError(f"unknown runtime kind {self.kind!r}")

    def read_only_paths(self) -> list[Path]:
        """Directories the worker must be able to read inside a bubblewrap sandbox."""
        exe = Path(self.executable)
        paths = {exe.resolve().parent}
        if self.kind == "module":
            paths.add(exe.parent.parent)  # a venv root (site-packages with bpy)
            paths.add(exe.resolve().parent.parent)
        else:
            paths.add(exe.parent)
        return sorted(p for p in paths if p.exists())

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "version": self.version, "offline_flag": self.offline_flag}


# --- paths and references ----------------------------------------------------------------

def _is_link(path: Path) -> bool:
    """Symlink or Windows reparse point (junctions included). A missing path is not a link."""
    try:
        if path.is_symlink():
            return True
        if os.name == "nt":
            return bool(path.lstat().st_file_attributes & REPARSE_POINT)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return False


def _relative_parts(rel: str, *, code: str) -> tuple[str, ...]:
    if not isinstance(rel, str) or not rel or "\x00" in rel or "\\" in rel:
        raise SceneInspectionError(code, f"invalid relative path: {rel!r}")
    pure = PurePosixPath(rel)
    if pure.is_absolute() or (len(rel) > 1 and rel[1] == ":"):
        raise SceneInspectionError(code, f"absolute path not allowed: {rel!r}")
    parts = tuple(part for part in pure.parts if part != ".")
    if not parts or ".." in parts:
        raise SceneInspectionError(code, f"path escapes its folder: {rel!r}")
    return parts


def contained_file(root: Path, rel: str, *, code: str = "unsafe_path") -> Path:
    """``root/rel`` as a regular file inside ``root`` with no link on the way, or raise."""
    current = root
    for part in _relative_parts(rel, code=code):
        current = current / part
        if _is_link(current):
            raise SceneInspectionError(code, f"symlink or reparse point not allowed: {rel}")
    try:
        resolved = current.resolve(strict=True)
    except OSError as exc:
        raise SceneInspectionError("missing_file", f"not found: {rel}") from exc
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise SceneInspectionError(code, f"not a regular file inside the root: {rel}")
    return resolved


def reference_path(uri: str) -> str:
    """A glTF/OBJ reference as a strict relative POSIX path, or raise ``unsafe_reference``."""
    if not isinstance(uri, str) or not uri:
        raise SceneInspectionError("unsafe_reference", "empty or non-string reference")
    parsed = urlsplit(uri)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise SceneInspectionError("unsafe_reference", f"external reference not allowed: {uri}")
    decoded = unquote(uri)
    _relative_parts(decoded, code="unsafe_reference")
    return decoded


def _gltf_document(path: Path, fmt: str) -> dict[str, Any]:
    if fmt == "gltf":
        return json_io.read_json_object(path, error=_InvalidAsset, unreadable="unreadable glTF JSON",
                                        not_object="glTF document is not an object")
    with path.open("rb") as handle:
        header = handle.read(20)
        if len(header) < 20:
            raise _InvalidAsset("truncated GLB header")
        magic, version, _length, chunk_length, chunk_type = struct.unpack("<IIIII", header)
        if magic != 0x46546C67 or version != 2 or chunk_type != 0x4E4F534A:
            raise _InvalidAsset("not a glTF 2.0 binary with a leading JSON chunk")
        if chunk_length > 256 * 1024 * 1024:
            raise _InvalidAsset("GLB JSON chunk too large")
        raw = handle.read(chunk_length)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise _InvalidAsset("unreadable GLB JSON chunk") from exc
    if not isinstance(document, dict):
        raise _InvalidAsset("GLB JSON chunk is not an object")
    return document


def _gltf_references(document: Mapping[str, Any]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for section in ("buffers", "images"):
        items = document.get(section, [])
        if not isinstance(items, list):
            raise _InvalidAsset(f"glTF {section} is not an array")
        for item in items:
            if not isinstance(item, dict):
                raise _InvalidAsset(f"glTF {section} entry is not an object")
            uri = item.get("uri")
            if uri is None:
                continue
            if not isinstance(uri, str):
                raise _InvalidAsset(f"glTF {section} uri is not a string")
            if not uri.startswith("data:"):
                found.append((section, uri))
    return found


def _obj_material_libraries(path: Path) -> list[str]:
    """The text after each ``mtllib`` keyword (one or more names, possibly with spaces)."""
    names: list[str] = []
    with path.open("rb") as handle:
        for line in handle:
            if line[:6].lower() == b"mtllib" and line[6:7] in (b" ", b"\t"):
                name = line[6:].strip().decode("utf-8", "replace")
                if name:
                    names.append(name)
    return names


def _mtl_texture_problem(mtl: Path) -> str | None:
    """Why a material library must not be staged, or None.

    Blender's OBJ importer opens every texture statement it reads, as given.
    Texture files are never staged, so a relative in-folder name only yields a
    missing texture. Anything that could point elsewhere (absolute, drive,
    UNC, backslash, ``..``, a scheme) keeps the whole library out of staging;
    the OBJ is then imported with default materials instead.
    """
    with mtl.open("rb") as handle:
        for raw in handle:
            text = raw.decode("utf-8", "replace").strip()
            keyword = text.split(None, 1)[0].lower() if text else ""
            if not keyword.startswith(MTL_TEXTURE_STATEMENTS):
                continue
            for token in text.split()[1:]:
                if token.startswith("-"):
                    continue
                if ("\\" in token or ":" in token or token.startswith("/") or token.startswith("~")
                        or ".." in PurePosixPath(token).parts):
                    return f"texture reference may leave the asset folder: {token[:120]}"
    return None


def _obj_library_names(text: str) -> list[str]:
    """``mtllib`` may name several libraries; a single name may contain spaces."""
    return [text] if " " not in text.strip() else [text, *text.split()]


def resolve_dependencies(asset: Path, fmt: str, warnings: list[str]) -> list[tuple[str, Path]]:
    """(relative-to-asset-folder, absolute path) for what Blender needs. Raises on unsafe or missing buffers."""
    folder = asset.parent
    deps: dict[str, Path] = {}
    if fmt in ("gltf", "glb"):
        for section, uri in _gltf_references(_gltf_document(asset, fmt)):
            rel = reference_path(uri)
            try:
                deps[rel] = contained_file(folder, rel, code="unsafe_reference")
            except SceneInspectionError as exc:
                if exc.code == "missing_file" and section == "images":
                    warnings.append(f"image not found, not staged: {rel}")
                    continue
                if exc.code == "missing_file":
                    raise SceneInspectionError("missing_dependency", f"glTF buffer not found: {rel}") from exc
                raise
    elif fmt == "obj":
        for text in _obj_material_libraries(asset):
            # Blender opens whatever mtllib names, so an unsafe name fails the asset (fail closed);
            # only a missing in-folder library is tolerated.
            candidates = _obj_library_names(text)
            for name in candidates:
                reference_path(name)
            found = False
            for name in candidates:
                try:
                    library = contained_file(folder, name, code="unsafe_reference")
                except SceneInspectionError as exc:
                    if exc.code == "missing_file":
                        continue
                    raise
                problem = _mtl_texture_problem(library)
                if problem:
                    warnings.append(f"material library not staged, {problem}; default materials used: {name[:200]}")
                else:
                    deps[name] = library
                found = True
                if name == text:
                    break
            if not found:
                warnings.append(f"material library not found, default materials used: {text[:200]}")
    return sorted(deps.items())


# --- header probes (MINIMUM_READY) ---------------------------------------------------------

def _gltf_minimum(document: Mapping[str, Any]) -> dict[str, Any]:
    def count(key: str) -> int:
        value = document.get(key)
        return len(value) if isinstance(value, list) else 0

    asset = document.get("asset") if isinstance(document.get("asset"), dict) else {}
    used = document.get("extensionsUsed")
    return {
        "gltf_version": str(asset.get("version", ""))[:16],
        "generator": str(asset.get("generator", ""))[:200],
        "extensions_used": sorted(str(e)[:100] for e in used)[:100] if isinstance(used, list) else [],
        **{key: count(key) for key in ("scenes", "nodes", "meshes", "skins", "animations",
                                         "materials", "images", "textures", "accessors")},
    }


def _obj_minimum(path: Path, size: int) -> dict[str, Any]:
    if size > OBJ_COUNT_LIMIT_BYTES:
        return {"counted": False, "reason": "larger than the header-count limit"}
    counts = {"vertices": 0, "uvs": 0, "normals": 0, "faces": 0, "objects": 0, "groups": 0, "materials_used": 0}
    keys = {b"v": "vertices", b"vt": "uvs", b"vn": "normals", b"f": "faces", b"o": "objects", b"g": "groups",
            b"usemtl": "materials_used"}
    with path.open("rb") as handle:
        for line in handle:
            head = line.split(None, 1)[0] if line[:1] not in (b"#", b"\n", b"\r") and line.strip() else b""
            name = keys.get(head)
            if name:
                counts[name] += 1
    return {"counted": True, **counts}


def _fbx_minimum(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        head = handle.read(64)
    if head.startswith(b"Kaydara FBX Binary  \x00"):
        return {"encoding": "binary", "fbx_version": struct.unpack("<I", head[23:27])[0]}
    if head.lstrip().startswith(b"; FBX"):
        return {"encoding": "ascii", "header": head.split(b"\n", 1)[0].decode("ascii", "replace").strip()[:80]}
    raise _InvalidAsset("not an FBX file")


def _blend_minimum(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        head = handle.read(32)
    compression = None
    if head.startswith(b"\x28\xb5\x2f\xfd"):
        return {"compression": "zstd", "blender_version": None}
    if head.startswith(b"\x1f\x8b"):
        compression = "gzip"
        with gzip.open(path, "rb") as handle:
            head = handle.read(32)
    if not head.startswith(b"BLENDER"):
        raise _InvalidAsset("not a .blend file")
    rest = head[7:]
    if rest[:1] in (b"_", b"-"):
        version = rest[2:5].decode("ascii", "replace")
        info = {"pointer_size": 4 if rest[:1] == b"_" else 8, "endian": "little" if rest[1:2] == b"v" else "big"}
    else:  # Blender 5.x header "BLENDER17-01v0500": header size, "-", format version, endian, 4-digit version
        version = rest[6:10].decode("ascii", "replace").lstrip("0")
        info = {"pointer_size": 8, "endian": "little" if rest[5:6] == b"v" else "big"}
    if version.isdigit():
        version = f"{int(version) // 100}.{int(version) % 100}"
    return {"compression": compression, "blender_version": version, **info}


def minimum_metadata(path: Path, fmt: str, size: int) -> dict[str, Any]:
    if fmt in ("gltf", "glb"):
        return _gltf_minimum(_gltf_document(path, fmt))
    if fmt == "obj":
        return _obj_minimum(path, size)
    if fmt == "fbx":
        return _fbx_minimum(path)
    return _blend_minimum(path)


# --- cache --------------------------------------------------------------------------------

def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class SceneCache:
    """Content-addressed results under ``root/objects/<key[:2]>/<key>/``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)
        self._memo_path = self.root / "hash-memo.json"
        self._lock = threading.Lock()
        try:
            loaded = json_io.read_json_object(self._memo_path, error=ValueError, unreadable="memo", not_object="memo")
        except ValueError:
            loaded = {}
        self._memo: dict[str, Any] = loaded
        self._memo_dirty = False

    def file_sha(self, path: Path, *, use_memo: bool = True) -> str:
        stat = path.stat()
        key = str(path)
        stamp = [stat.st_size, stat.st_mtime_ns]
        if use_memo:
            with self._lock:
                hit = self._memo.get(key)
            if isinstance(hit, dict) and hit.get("stamp") == stamp and isinstance(hit.get("sha256"), str):
                return hit["sha256"]
        digest = hashing.sha256_file(path)
        with self._lock:
            self._memo[key] = {"stamp": stamp, "sha256": digest}
            self._memo_dirty = True
        return digest

    def save_memo(self) -> None:
        with self._lock:
            if self._memo_dirty:
                _atomic_write_json(self._memo_path, self._memo)
                self._memo_dirty = False

    def _entry(self, key: str) -> Path:
        if not isinstance(key, str) or not _CACHE_KEY.fullmatch(key):
            raise SceneInspectionError("internal_error", "invalid cache key")
        return self.objects / key[:2] / key

    def _entry_is_safe(self, entry: Path) -> bool:
        """No link anywhere from the cache root down to the entry, and the entry inside the root."""
        current = self.root
        for part in entry.relative_to(self.root).parts:
            current = current / part
            if _is_link(current):
                return False
        try:
            return entry.resolve(strict=True).is_relative_to(self.root.resolve(strict=True))
        except OSError:
            return False

    def load(self, key: str) -> tuple[dict[str, Any], Path] | None:
        """A verified entry, or None. Cache metadata is never trusted as a path source."""
        entry = self._entry(key)
        if not entry.is_dir() or not self._entry_is_safe(entry) or _is_link(entry / "result.json"):
            return None
        try:
            stored = json_io.read_json_object(entry / "result.json", error=ValueError, unreadable="cache", not_object="cache")
        except ValueError:
            return None
        files = stored.get("files", {})
        if stored.get("cache_key") != key or not isinstance(files, dict):
            return None
        if not all(is_output_name(name) for name in files):  # exact allowlisted names only: no paths, no ..
            return None
        for name, digest in files.items():
            candidate = entry / name
            if (_is_link(candidate) or not candidate.is_file() or not isinstance(digest, str)
                    or hashing.sha256_file(candidate) != digest):
                return None
        return stored, entry

    def store(self, key: str, payload: Mapping[str, Any], files: Mapping[str, Path]) -> None:
        unknown = sorted(name for name in files if not is_output_name(name))
        if unknown:
            raise SceneInspectionError("internal_error", f"refusing to cache unexpected files: {unknown}")
        entry = self._entry(key)
        if entry.exists():
            return
        entry.parent.mkdir(parents=True, exist_ok=True)
        if not self._entry_is_safe(entry.parent):
            raise SceneInspectionError("unsafe_path", "the cache directory contains a link")
        entry.parent.mkdir(parents=True, exist_ok=True)
        tmp = entry.parent / f".tmp-{uuid.uuid4().hex}"
        tmp.mkdir()
        try:
            for name, source in files.items():
                shutil.copyfile(source, tmp / name)
            _atomic_write_json(tmp / "result.json", {**payload, "cache_key": key})
            try:
                os.replace(tmp, entry)
            except OSError:
                if not entry.exists():
                    raise
        finally:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)


# --- runtime and isolation ----------------------------------------------------------------

def child_env(jobdir: Path) -> dict[str, str]:
    """A minimal environment: empty Blender/user dirs, a dead proxy, no GPUs."""
    home = jobdir / "home"
    tmp = jobdir / "tmp"
    user = jobdir / "blender-user"
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
                                             "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "LANG", "LC_ALL")
           if key in os.environ}
    dirs = {
        "HOME": home, "USERPROFILE": home, "APPDATA": home / "AppData" / "Roaming",
        "LOCALAPPDATA": home / "AppData" / "Local", "XDG_CONFIG_HOME": home / ".config",
        "XDG_CACHE_HOME": home / ".cache", "XDG_DATA_HOME": home / ".local" / "share",
        "TMP": tmp, "TEMP": tmp, "TMPDIR": tmp,
        "BLENDER_USER_RESOURCES": user, "BLENDER_USER_CONFIG": user / "config",
        "BLENDER_USER_SCRIPTS": user / "scripts", "BLENDER_USER_DATAFILES": user / "datafiles",
        "BLENDER_USER_EXTENSIONS": user / "extensions",
    }
    for key, path in dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env.update({
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
        "CUDA_VISIBLE_DEVICES": "", "HIP_VISIBLE_DEVICES": "", "ROCR_VISIBLE_DEVICES": "",
        "http_proxy": DEAD_PROXY, "https_proxy": DEAD_PROXY, "HTTP_PROXY": DEAD_PROXY,
        "HTTPS_PROXY": DEAD_PROXY, "ALL_PROXY": DEAD_PROXY, "all_proxy": DEAD_PROXY,
        "NO_PROXY": "", "no_proxy": "",
    })
    return env


_BWRAP_OK: bool | None = None


def bwrap_available() -> bool:
    global _BWRAP_OK
    if _BWRAP_OK is None:
        exe = shutil.which("bwrap") if sys.platform.startswith("linux") else None
        if exe is None:
            _BWRAP_OK = False
        else:
            try:
                probe = subprocess.run([exe, "--ro-bind", "/", "/", "--unshare-all", "--die-with-parent", "true"],
                                       capture_output=True, timeout=20)
                _BWRAP_OK = probe.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                _BWRAP_OK = False
    return _BWRAP_OK


def bwrap_prefix(jobdir: Path, read_only: Iterable[Path], env: Mapping[str, str]) -> list[str]:
    """bubblewrap argv: system dirs and the runtime read-only, only ``jobdir`` writable, no network."""
    argv = [shutil.which("bwrap") or "bwrap", "--die-with-parent", "--new-session", "--unshare-all", "--clearenv",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for system_dir in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/lib32", "/etc"):
        argv += ["--ro-bind-try", system_dir, system_dir]
    for path in read_only:
        argv += ["--ro-bind", str(path), str(path)]
    argv += ["--bind", str(jobdir), str(jobdir), "--chdir", str(jobdir)]
    for key, value in sorted(env.items()):
        argv += ["--setenv", key, value]
    argv.append("--")
    return argv


def _probe_output(argv: list[str], *, timeout: float = 120.0) -> str:
    with tempfile.TemporaryDirectory(prefix="bodyrig-blender-probe-") as tmp:
        jobdir = Path(tmp)
        out, err = jobdir / "stdout.txt", jobdir / "stderr.txt"
        result = run_bounded(argv, cwd=jobdir, env=child_env(jobdir), limits=Limits(wall_seconds=timeout),
                             stdout_path=out, stderr_path=err)
        text = tail(out, 200_000)
        if result.timed_out or result.returncode != 0:
            raise SetupError(f"runtime probe failed ({result.returncode}): {tail(err, 1000) or text[-1000:]}")
        return text


def detect_runtime(*, blender: Path | None = None, bpy_python: Path | None = None,
                   cache_root: Path | None = None) -> BlenderRuntime:
    """Probe the Blender version once per executable (cached by path, size and mtime)."""
    if (blender is None) == (bpy_python is None):
        raise SetupError("give exactly one of --blender or --bpy-python")
    kind, exe = ("cli", Path(blender)) if blender is not None else ("module", Path(bpy_python))
    # absolute but NOT resolved: a venv's python is a symlink and must stay the venv's
    exe = Path(os.path.abspath(shutil.which(str(exe)) or exe))
    if not exe.is_file():
        raise SetupError(f"runtime executable not found: {exe}")
    stat = exe.stat()
    stamp = {"kind": kind, "path": str(exe.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
             "worker_sha256": hashing.sha256_file(WORKER_SCRIPT)}
    cache_file = Path(cache_root) / "runtime.json" if cache_root else None
    if cache_file is not None:
        try:
            cached = json_io.read_json_object(cache_file, error=ValueError, unreadable="x", not_object="x")
            if cached.get("stamp") == stamp:
                return BlenderRuntime(kind, exe, str(cached["version"]), bool(cached.get("offline_flag")))
        except (ValueError, KeyError):
            pass
    if kind == "cli":
        version_text = _probe_output([str(exe), "--factory-startup", "--version"])
        first = next((line for line in version_text.splitlines() if line.startswith("Blender ")), "")
        version = first.split()[1] if len(first.split()) > 1 else ""
        offline = "--offline-mode" in _probe_output([str(exe), "--help"])
    else:
        version = _probe_output([str(exe), "-I", "-c", MODULE_VERSION_PROBE]).strip().split()[0:1]
        version = version[0] if version else ""
        offline = False
    if not version:
        raise SetupError("could not read the Blender version")
    if cache_file is not None:
        _atomic_write_json(cache_file, {"stamp": stamp, "version": version, "offline_flag": offline})
    return BlenderRuntime(kind, exe, version, offline)


# --- one asset ----------------------------------------------------------------------------

def _ms(start: float) -> int:
    return int(round((time.perf_counter() - start) * 1000))


def _remove_tree(path: Path) -> bool:
    for _ in range(10):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return True
        time.sleep(0.2)  # Windows can hold handles briefly after a kill
    return not path.exists()


def _cache_key(runtime: BlenderRuntime, options: InspectOptions, fmt: str, asset_sha: str,
               deps: Sequence[Mapping[str, Any]], worker_sha: str) -> str:
    material = {
        "schema": SCHEMA,
        "inspector_version": INSPECTOR_VERSION,
        "worker_sha256": worker_sha,
        "runtime": {"kind": runtime.kind, "version": runtime.version},
        "options": {"conditioning": list(options.conditioning), "resolution": options.resolution,
                    "frames": list(options.frames) if options.frames else None,
                    "yaw_deg": float(options.yaw_deg)},
        "asset": {"format": fmt, "sha256": asset_sha},
        "dependencies": [[d["path"], d["sha256"]] for d in deps],
    }
    return hashing.sha256_bytes(hashing.canonical_json_bytes(material))


def _isolation(options: InspectOptions) -> str:
    if options.isolation == "none":
        return "none"
    if bwrap_available():
        return "bwrap"
    if options.isolation == "bwrap":
        raise SetupError("isolation=bwrap requested but bubblewrap is not usable here")
    return "none"


def _isolation_report(mode: str) -> dict[str, Any]:
    if mode == "bwrap":
        return {"mode": "bwrap", "filesystem": "read-only system and runtime dirs; only the job dir writable",
                "network": "unshared namespace"}
    return {"mode": "process-only",
            "filesystem": "not isolated: the worker can read files the user can read",
            "network": "not isolated: dead proxy only; Blender online features off"}


PROGRESS_WRITE_SECONDS = 0.5


def _progress_relay(source: Path, out_dir: Path, result: dict[str, Any]) -> Any:
    """Copy the worker's progress.json into out_dir/scene.json while it runs (rate-limited)."""
    state = {"last": None, "written_at": 0.0}

    def relay() -> None:
        now = time.perf_counter()
        if now - state["written_at"] < PROGRESS_WRITE_SECONDS:
            return
        try:
            progress = json_io.read_json_object(source, error=ValueError, unreadable="p", not_object="p")
        except ValueError:
            return
        snapshot = {key: progress.get(key) for key in ("stage", "frames_done", "frames_total")}
        if not isinstance(snapshot["stage"], str):
            return
        snapshot["stage"] = snapshot["stage"][:40]
        for key in ("frames_done", "frames_total"):
            if not isinstance(snapshot[key], int) or isinstance(snapshot[key], bool) or snapshot[key] < 0:
                snapshot[key] = 0
        if snapshot == state["last"]:
            return
        state["last"], state["written_at"] = dict(snapshot), now
        result["progress"] = snapshot
        _atomic_write_json(out_dir / "scene.json", result)

    return relay


PROGRESS_MAX_BYTES = 64 * 1024


def _keep_partial_frames(worker_out: Path, out_dir: Path, options: InspectOptions,
                         result: dict[str, Any]) -> str:
    """After a stopped frame-sequence worker: keep the frames it finished, never a half-written one.

    The worker publishes ``frames_done = k`` (atomically) before it starts frame ``k``, so frames
    below ``k`` are complete. Only allowlisted names of those frames are copied; the asset stays
    FAILED and nothing is cached. Returns a note for the error message.
    """
    frames = options.frame_list()
    source = worker_out / "progress.json"
    if not frames or not source.is_file() or _is_link(source) or source.stat().st_size > PROGRESS_MAX_BYTES:
        return ""
    try:
        progress = json_io.read_json_object(source, error=ValueError, unreadable="p", not_object="p")
    except ValueError:
        return ""
    done = progress.get("frames_done")
    if progress.get("frames_total") != len(frames) or not isinstance(done, int) or isinstance(done, bool) \
            or not 0 < done <= len(frames):
        return ""
    files: dict[str, str] = {}
    kept = 0
    for index in range(done):
        names = [f"f{index:06d}_{name}" for kind in options.conditioning for name in CONDITIONING_FILES[kind]]
        produced = [worker_out / name for name in names]
        if not all(path.is_file() and not _is_link(path) for path in produced):
            break  # stop at the first incomplete frame: a sequence with a gap is not kept past it
        for name, path in zip(names, produced):
            shutil.copyfile(path, _output_target(out_dir, name))
            files[name] = hashing.sha256_file(out_dir / name)
        kept = index + 1
    if not kept:
        return ""
    camera = progress.get("camera")
    result["partial"] = {"frames_done": kept, "frames_total": len(frames), "frames": frames[:kept],
                         "camera": camera if isinstance(camera, dict) else None, "files": files,
                         "note": "frames finished before the worker was stopped; the asset is FAILED and "
                                 "this is not cached"}
    return f" {kept} of {len(frames)} frames were finished and are kept (partial)."


def _transient_start_failure(run: Any, output: Path, stderr: Path) -> bool:
    """Blender itself failed to load, before any asset byte was read.

    Seen once on the windows-2025 runner with several workers starting at the
    same time: "DLL load failed while importing bpy". The worker had not run
    (no output document), so one retry cannot hide an asset problem; a second
    failure is reported as usual.
    """
    if run.timed_out or run.memory_exceeded or run.returncode == 0 or output.exists():
        return False
    text = tail(stderr, 4000)
    return "DLL load failed while importing bpy" in text or "No module named 'bpy'" in text


def _worker_document(path: Path) -> dict[str, Any]:
    return json_io.read_json_object(path, error=_InvalidAsset, unreadable="worker output unreadable",
                                    not_object="worker output is not an object")


def _output_target(out_dir: Path, name: str) -> Path:
    """An allowlisted file name in ``out_dir`` that is not a link (a link would be written through)."""
    if not is_output_name(name):
        raise SceneInspectionError("internal_error", f"unexpected output file name: {name!r}")
    target = out_dir / name
    if _is_link(target):
        raise SceneInspectionError("unsafe_path", f"output file is a link: {target}")
    return target


def _apply_inventory(entry: Mapping[str, Any] | None, asset_sha: str, result: dict[str, Any]) -> None:
    """Honour a #1394 inventory decision for this asset (schema_version 2)."""
    if entry is None:
        return
    status = entry.get("status")
    reasons = [str(r)[:300] for r in entry.get("reasons", [])][:10] if isinstance(entry.get("reasons"), list) else []
    result["inventory"] = {"status": status, "reasons": reasons, "readiness": entry.get("readiness")}
    if status == "rejected":
        raise SceneInspectionError("inventory_rejected", "; ".join(reasons) or "rejected by the inventory")
    if status not in ("ok", "degraded"):
        detail = "; ".join(reasons) or f"inventory status {status!r}"
        raise SceneInspectionError("inventory_mismatch", detail)
    if entry.get("sha256") != asset_sha:
        raise SceneInspectionError("inventory_mismatch", "asset changed since the inventory was taken")
    if status == "degraded":
        result["warnings"].append(f"inventory: degraded ({'; '.join(reasons)})")


def _compare_inventory_dependencies(entry: Mapping[str, Any] | None, asset_rel: str,
                                    staged: Sequence[Mapping[str, Any]], result: dict[str, Any]) -> None:
    """Inventory dependencies are root-relative; the inspector's are relative to the asset folder."""
    if entry is None or not isinstance(entry.get("dependencies"), list):
        return
    folder = PurePosixPath(asset_rel).parent
    listed = {}
    for dep in entry["dependencies"]:
        if isinstance(dep, dict) and isinstance(dep.get("path"), str):
            path = PurePosixPath(dep["path"])
            rel = path.relative_to(folder).as_posix() if folder != PurePosixPath(".") and path.is_relative_to(folder) else path.as_posix()
            listed[rel] = dep.get("sha256")
    mine = {d["path"]: d["sha256"] for d in staged}
    result["inventory"]["dependencies_not_staged"] = sorted(set(listed) - set(mine))
    disagree = sorted(rel for rel in set(listed) & set(mine) if listed[rel] != mine[rel])
    extra = sorted(set(mine) - set(listed))
    if disagree:
        raise SceneInspectionError("inventory_mismatch", f"dependency changed since the inventory: {disagree[:5]}")
    if extra:
        result["warnings"].append(f"staged dependencies the inventory did not list: {extra[:5]}")


def inspect_asset(source_root: Path, asset_rel: str, out_dir: Path, *, runtime: BlenderRuntime | None,
                  cache: SceneCache, options: InspectOptions, work_root: Path | None = None,
                  inventory_entry: Mapping[str, Any] | None = None, cancel: Any = None,
                  deadline: float | None = None) -> dict[str, Any]:
    """Inspect one asset. Always returns a result and writes ``out_dir/scene.json``; never raises per asset.

    ``deadline`` is a ``time.perf_counter()`` value: the run's total time budget. An asset that
    would start after it is not started, and a Blender worker never runs past it.
    """
    started = time.perf_counter()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timings: dict[str, int] = {}
    result: dict[str, Any] = {
        "schema": SCHEMA, "inspector_version": INSPECTOR_VERSION, "state": "PENDING", "states_reached": [],
        "likeness_authority": False, "production_activation": False,
        "asset": {"path": asset_rel}, "dependencies": [], "minimum": None, "scene": None, "conditioning": None,
        "cache": {"key": None, "hit": False}, "runtime": runtime.describe() if runtime else None,
        "isolation": None, "process": None, "timings_ms": timings, "warnings": [], "error": None, "cleanup": None,
    }
    warnings: list[str] = result["warnings"]

    def reach(state: str, *, write: bool = False) -> None:
        result["state"] = state
        result["states_reached"].append(state)
        timings[f"{state.lower()}_at"] = _ms(started)
        if write:
            _atomic_write_json(out_dir / "scene.json", result)

    jobdir: Path | None = None
    try:
        if cancel is not None and cancel.is_set():
            raise SceneInspectionError("cancelled", "the batch was cancelled before this asset started")
        if deadline is not None and time.perf_counter() >= deadline:
            raise SceneInspectionError("budget_exhausted", BUDGET_NOT_STARTED)
        root = Path(source_root).resolve(strict=True)
        step = time.perf_counter()
        asset = contained_file(root, asset_rel)
        fmt = FORMATS.get(asset.suffix.lower())
        if fmt is None:
            raise SceneInspectionError("unsupported_format", f"unsupported extension: {asset.suffix}")
        size = asset.stat().st_size
        if size > options.max_asset_bytes:
            raise SceneInspectionError("too_large", f"asset is {size} bytes; limit {options.max_asset_bytes}")
        asset_sha = cache.file_sha(asset, use_memo=options.use_hash_memo)
        result["asset"].update({"format": fmt, "bytes": size, "sha256": asset_sha})
        timings["discover"] = _ms(step)
        reach("DISCOVERED")
        _apply_inventory(inventory_entry, asset_sha, result)

        step = time.perf_counter()
        deps = [{"path": rel, "bytes": path.stat().st_size, "sha256": cache.file_sha(path, use_memo=options.use_hash_memo),
                 "source": path} for rel, path in resolve_dependencies(asset, fmt, warnings)]
        result["dependencies"] = [{k: v for k, v in d.items() if k != "source"} for d in deps]
        _compare_inventory_dependencies(inventory_entry, asset_rel, result["dependencies"], result)
        timings["dependencies"] = _ms(step)
        reach("SAFE_TO_INSPECT")

        worker_sha = hashing.sha256_file(runtime.worker_script if runtime else WORKER_SCRIPT)
        if runtime is not None:
            key = _cache_key(runtime, options, fmt, asset_sha, result["dependencies"], worker_sha)
            result["cache"]["key"] = key
            step = time.perf_counter()
            hit = cache.load(key)
            timings["cache_lookup"] = _ms(step)
            if hit is not None and not options.minimum_only:
                stored, entry = hit
                for name in stored.get("files", {}):
                    shutil.copyfile(entry / name, _output_target(out_dir, name))
                if stored.get("files"):
                    timings["conditioning_ready_at"] = _ms(started)
                for field in ("minimum", "scene", "conditioning", "process", "isolation", "worker_timings_ms",
                              "runtime"):
                    result[field] = stored.get(field)
                warnings.extend(w for w in stored.get("warnings", []) if w not in warnings)
                result["cache"]["hit"] = True
                result["states_reached"].append("MINIMUM_READY")
                reach("FULLY_ANALYZED")
                timings["total"] = _ms(started)
                _atomic_write_json(out_dir / "scene.json", result)
                return result

        step = time.perf_counter()
        result["minimum"] = minimum_metadata(asset, fmt, size)
        timings["minimum"] = _ms(step)
        reach("MINIMUM_READY", write=True)
        if options.minimum_only or runtime is None:
            timings["total"] = _ms(started)
            _atomic_write_json(out_dir / "scene.json", result)
            return result

        step = time.perf_counter()
        mode = _isolation(options)
        base = Path(work_root) if work_root else Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        jobdir = Path(tempfile.mkdtemp(prefix="bodyrig-scene-", dir=base)).resolve()
        src_dir, worker_out, worker_dir = jobdir / "src", jobdir / "out", jobdir / "worker"
        for folder in (src_dir, worker_out, worker_dir):
            folder.mkdir()
        # The worker runs from a copy inside the job dir, so a sandbox needs no view of the checkout.
        worker_copy = worker_dir / Path(runtime.worker_script).name
        shutil.copyfile(runtime.worker_script, worker_copy)
        if hashing.sha256_file(worker_copy) != worker_sha:
            raise SceneInspectionError("source_changed", "worker script changed while staging")
        staged_asset = src_dir / asset.name
        for target, source, expected in [(staged_asset, asset, asset_sha)] + [
                (src_dir / d["path"], d["source"], d["sha256"]) for d in deps]:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if hashing.sha256_file(target) != expected:
                raise SceneInspectionError("source_changed", f"source changed while staging: {target.name}")
        timings["stage"] = _ms(step)

        worker_args = ["--input", str(staged_asset), "--format", fmt, "--staging-root", str(src_dir),
                       "--output", str(worker_out / "worker.json"), "--resolution", str(options.resolution),
                       "--conditioning", ",".join(options.conditioning),
                       "--frames", ":".join(str(v) for v in options.frames) if options.frames else "",
                       "--yaw", repr(float(options.yaw_deg))]
        env = child_env(jobdir)
        argv = replace(runtime, worker_script=worker_copy).command(worker_args, threads=options.threads)
        if mode == "bwrap":
            argv = bwrap_prefix(jobdir, runtime.read_only_paths(), env) + argv
        result["isolation"] = _isolation_report(mode)
        step = time.perf_counter()
        wall = options.wall_seconds
        if deadline is not None:
            remaining = deadline - time.perf_counter()
            if remaining < MIN_WORKER_SECONDS:
                raise SceneInspectionError("budget_exhausted", "the run's time budget was used up before Blender "
                                           "started; metadata is kept. " + BUDGET_RERUN)
            wall = min(wall, remaining)
        limits = Limits(wall_seconds=wall, memory_bytes=options.memory_bytes, cpu_seconds=options.cpu_seconds)
        attempts = 0
        while True:
            attempts += 1
            try:
                run = run_bounded(argv, cwd=jobdir, env=env, limits=limits, cancel=cancel,
                                  on_poll=_progress_relay(worker_out / "progress.json", out_dir, result),
                                  stdout_path=jobdir / "worker.stdout.txt", stderr_path=jobdir / "worker.stderr.txt")
            except CancelledRun as exc:
                raise SceneInspectionError("cancelled", "the batch was cancelled; the worker was stopped") from exc
            if attempts == 1 and _transient_start_failure(run, worker_out / "worker.json", jobdir / "worker.stderr.txt"):
                warnings.append("Blender failed to load before the worker started (bpy import); retried once")
                time.sleep(1.0)
                continue
            break
        timings["blender"] = _ms(step)
        result["process"] = {"returncode": run.returncode, "timed_out": run.timed_out,
                             "memory_exceeded": run.memory_exceeded, "peak_memory_bytes": run.peak_memory_bytes,
                             "attempts": attempts, "limits": run.applied}
        if run.timed_out:
            kept = _keep_partial_frames(worker_out, out_dir, options, result)
            if wall < options.wall_seconds:
                raise SceneInspectionError("budget_exhausted", f"stopped at the run's time budget after {wall:.0f}s; "
                                           "metadata is kept." + kept + " " + BUDGET_RERUN)
            raise SceneInspectionError("timeout", f"Blender worker exceeded {options.wall_seconds:g}s." + kept)
        if run.memory_exceeded:
            raise SceneInspectionError("memory_limit", "Blender worker exceeded the memory limit")
        output = worker_out / "worker.json"
        if not output.is_file():
            raise SceneInspectionError("worker_failed", f"worker exited {run.returncode} without output: "
                                       f"{tail(jobdir / 'worker.stderr.txt', 1500)}")
        document = _worker_document(output)
        if document.get("contract") != WORKER_CONTRACT:
            raise SceneInspectionError("worker_contract", "worker output has the wrong contract")
        if document.get("error"):
            error = document["error"] if isinstance(document["error"], dict) else {}
            raise SceneInspectionError("worker_failed", f"{error.get('type', 'error')}: {error.get('message', '')}")
        if document.get("complete") is not True:
            raise SceneInspectionError("worker_contract", "worker output is not marked complete")
        if run.returncode != 0:
            # The document is written atomically as the worker's last step, so a non-zero code
            # here comes from Blender's own teardown; keep the result and say so.
            warnings.append(f"worker exited {run.returncode} after writing a complete result")
        scene = document.get("scene")
        if not isinstance(scene, dict):
            raise SceneInspectionError("worker_contract", "worker output has no scene")
        result["scene"] = scene
        result["worker_timings_ms"] = document.get("timings_ms")
        result["runtime"] = {**runtime.describe(), "reported": document.get("blender"),
                             "importer": document.get("importer"), "security": document.get("security")}
        warnings.extend(str(w)[:500] for w in document.get("warnings", [])[:50])

        files: dict[str, Path] = {}
        prefixes = [f"f{index:06d}_" for index in range(len(options.frame_list()))] or [""]
        missing = []
        for prefix in prefixes:
            for kind in options.conditioning:
                for name in CONDITIONING_FILES[kind]:
                    produced = worker_out / (prefix + name)
                    if produced.is_file() and not _is_link(produced):
                        files[prefix + name] = produced
                    else:
                        missing.append(prefix + name)
        if missing:
            warnings.append(f"conditioning output missing ({len(missing)}): {', '.join(missing[:10])}")
        conditioning = document.get("conditioning")
        if isinstance(conditioning, dict):
            conditioning = {**conditioning, "files": {name: hashing.sha256_file(path) for name, path in files.items()}}
        result["conditioning"] = conditioning
        for name, path in files.items():
            shutil.copyfile(path, _output_target(out_dir, name))
        if files:
            timings["conditioning_ready_at"] = _ms(started)
        result.pop("progress", None)
        reach("FULLY_ANALYZED")
        cache.store(result["cache"]["key"], {
            field: result[field] for field in ("minimum", "scene", "conditioning", "process", "isolation",
                                                "warnings", "worker_timings_ms", "runtime")
        } | {"files": conditioning.get("files", {}) if isinstance(conditioning, dict) else {}}, files)
    except SceneInspectionError as exc:
        result["state"] = "FAILED"
        result["error"] = {"code": exc.code, "message": str(exc)[:2000]}
    except SetupError:
        raise
    except Exception as exc:  # isolate the batch from anything unexpected in one asset
        result["state"] = "FAILED"
        result["error"] = {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"[:2000]}
    finally:
        if jobdir is not None:
            removed = _remove_tree(jobdir)
            result["cleanup"] = {"staging_removed": removed}
            if not removed:
                warnings.append(f"staging directory could not be removed: {jobdir}")
    timings["total"] = _ms(started)
    _atomic_write_json(out_dir / "scene.json", result)
    return result


# --- batch, statistics, bench --------------------------------------------------------------

def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile; None for no values."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, math.ceil(q / 100.0 * len(ordered)))
    return ordered[rank - 1]


def timing_stats(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = ("total", "minimum_ready_at", "conditioning_ready_at", "fully_analyzed_at", "blender", "stage", "discover")
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for item in results:
        groups.setdefault("all", []).append(item)
        groups.setdefault(str(item.get("asset", {}).get("format", "unknown")), []).append(item)
    stats: dict[str, Any] = {}
    for group, items in sorted(groups.items()):
        entry: dict[str, Any] = {"n": len(items), "failed": sum(1 for i in items if i.get("state") == "FAILED"),
                                 "cache_hits": sum(1 for i in items if i.get("cache", {}).get("hit"))}
        for metric in metrics:
            values = [i["timings_ms"][metric] for i in items if isinstance(i.get("timings_ms", {}).get(metric), int)]
            if values:
                entry[metric] = {"p50": percentile(values, 50), "p95": percentile(values, 95), "max": max(values)}
        stats[group] = entry
    return stats


def _verdict(target_ms: int, value: int | None, n: int, *, what: str) -> dict[str, Any]:
    if value is None or n == 0:
        return {"verdict": "NOT_MEASURED", "target_ms": target_ms, "n": 0, "what": what}
    return {"verdict": "PASS" if value <= target_ms else "FAIL", "target_ms": target_ms, "value_ms": value,
            "n": n, "what": what}


def slo_report(results: Sequence[Mapping[str, Any]], *, conditioning: Sequence[str],
               first_usable_ms: int | None, nothing_usable_after_ms: int | None = None) -> dict[str, Any]:
    """PASS/FAIL/NOT_MEASURED against the #1393 targets for one run on this machine.

    An asset whose Blender worker was stopped (by --timeout or the budget) counts with its elapsed
    time, a lower bound, so a slow asset can only make the analysis verdict worse, never disappear
    from it. Assets that never started a worker are not samples.
    """
    fresh = [r for r in results if not r.get("cache", {}).get("hit")]
    cached = [r for r in results if r.get("cache", {}).get("hit")]

    def values(items: Iterable[Mapping[str, Any]], key: str, *, slow_too: bool = False) -> list[int]:
        out = []
        for item in items:
            timings = item.get("timings_ms", {})
            if isinstance(timings.get(key), int):
                out.append(timings[key])
            elif slow_too and (item.get("process") or {}).get("timed_out") is True \
                    and isinstance(timings.get("total"), int):
                out.append(timings["total"])  # a worker stopped by --timeout or the budget: a lower bound
        return out

    metadata = values(fresh, "minimum_ready_at")
    analysis = values(fresh, "fully_analyzed_at", slow_too=True)
    hits = values(cached, "total")
    analysis_target = SLO_TARGETS_MS["analysis_conditioning" if conditioning else "analysis"]
    first_usable = _verdict(SLO_TARGETS_MS["first_usable"], first_usable_ms, 1 if first_usable_ms is not None else 0,
                            what="first asset usable (conditioning written, or analyzed) after the run started")
    if first_usable_ms is None and nothing_usable_after_ms is not None:
        first_usable = {"verdict": "FAIL", "target_ms": SLO_TARGETS_MS["first_usable"],
                        "value_ms": nothing_usable_after_ms, "n": 0,
                        "what": "no asset became usable in this run; value is the whole run time"}
    return {
        "metadata": _verdict(SLO_TARGETS_MS["metadata"], percentile(metadata, 95), len(metadata),
                             what="p95 minimum_ready_at, uncached assets"),
        "analysis": _verdict(analysis_target, percentile(analysis, 95), len(analysis),
                             what="p95 fully_analyzed_at, uncached assets; timeouts count with their elapsed time"),
        "first_usable": first_usable,
        "cached": _verdict(SLO_TARGETS_MS["cached"], percentile(hits, 95), len(hits), what="p95 total, cache hits"),
        "machine": {"platform": sys.platform, "cpus": os.cpu_count()},
        "note": "#1393 targets; measured on this machine. Only a run on the physical rig validates them.",
    }


def _slug(rel: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in rel.replace("/", "__"))[:180] or "asset"


def load_inventory(path: Path) -> dict[str, dict[str, Any]]:
    """A #1394 inventory manifest (schema_version 2) as {asset path: entry}."""
    document = json_io.read_json_object(path, error=SetupError, unreadable=f"inventory unreadable: {path}",
                                        not_object="inventory is not a JSON object")
    if document.get("schema_version") != 2 or document.get("likeness_authority") is not False:
        raise SetupError("inventory must be schema_version 2 with likeness_authority false (#1394)")
    assets = document.get("assets")
    if not isinstance(assets, list):
        raise SetupError("inventory has no assets list")
    entries: dict[str, dict[str, Any]] = {}
    for entry in assets:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise SetupError("inventory asset entry without a path")
        entries[entry["path"]] = entry
    return entries


def inspect_batch(source_root: Path, assets: Sequence[str], out_root: Path, *, runtime: BlenderRuntime | None,
                  cache: SceneCache, options: InspectOptions, jobs: int = 1, work_root: Path | None = None,
                  inventory: Mapping[str, Mapping[str, Any]] | None = None,
                  budget_seconds: float | None = None) -> dict[str, Any]:
    """Inspect many assets. ``budget_seconds`` bounds the whole run: no asset starts after it and
    no worker runs past it; what finished is kept and a re-run continues from the cache."""
    options = options.validate()
    if budget_seconds is not None and budget_seconds <= 0:
        raise SetupError("the time budget must be positive (or omitted for no budget)")
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    targets = []
    for rel in assets:
        slug = _slug(rel)
        while slug in used:
            slug += "_"
        used.add(slug)
        targets.append((rel, out_root / slug))

    cancel = threading.Event()
    started = time.perf_counter()
    deadline = started + budget_seconds if budget_seconds is not None else None
    offsets: dict[int, int] = {}

    def one(index: int, item: tuple[str, Path]) -> dict[str, Any]:
        entry = None
        if inventory is not None:
            entry = inventory.get(item[0]) or {"status": "missing", "reasons": ["asset is not in the inventory"]}
        offsets[index] = _ms(started)
        return inspect_asset(source_root, item[0], item[1], runtime=runtime, cache=cache, options=options,
                             work_root=work_root, inventory_entry=entry, cancel=cancel, deadline=deadline)

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = [pool.submit(one, index, item) for index, item in enumerate(targets)]
        try:
            results = [future.result() for future in futures]
        except BaseException:  # Ctrl+C: stop running workers within a poll, skip the rest
            cancel.set()
            for future in futures:
                future.cancel()
            raise
    cache.save_memo()
    states: dict[str, int] = {}
    for item in results:
        states[item["state"]] = states.get(item["state"], 0) + 1
    first: dict[str, int] = {}
    for index, item in enumerate(results):
        for key in ("minimum_ready_at", "conditioning_ready_at", "fully_analyzed_at"):
            value = item["timings_ms"].get(key)
            if isinstance(value, int) and index in offsets:
                first[key] = min(first.get(key, value + offsets[index]), value + offsets[index])
    usable = first.get("conditioning_ready_at" if options.conditioning else "fully_analyzed_at")
    not_reached = sum(1 for r in results if (r["error"] or {}).get("code") == "budget_exhausted")
    summary = {
        "schema": BATCH_SCHEMA,
        "likeness_authority": False,
        "runtime": runtime.describe() if runtime else None,
        "options": {"conditioning": list(options.conditioning), "resolution": options.resolution,
                    "frames": list(options.frames) if options.frames else None, "timeout_s": options.wall_seconds, "jobs": jobs, "isolation": options.isolation},
        "states": dict(sorted(states.items())),
        "wall_ms": _ms(started),
        "budget": {"seconds": budget_seconds, "not_reached": not_reached},
        "first_result_ms": first,
        "assets": [{"path": r["asset"]["path"], "out": str(t[1].relative_to(out_root)), "state": r["state"],
                    "error": r["error"], "cache_hit": r["cache"]["hit"], "timings_ms": r["timings_ms"]}
                   for r, t in zip(results, targets)],
        "timings": timing_stats(results),
        "slo": slo_report(results, conditioning=options.conditioning, first_usable_ms=usable,
                          nothing_usable_after_ms=_ms(started) if runtime is not None and not options.minimum_only
                          and results else None),
    }
    _atomic_write_json(out_root / "summary.json", summary)
    return summary


def bench(source_root: Path, assets: Sequence[str], out_root: Path, *, runtime: BlenderRuntime,
          options: InspectOptions, runs: int = 3, work_root: Path | None = None) -> dict[str, Any]:
    """Cold runs (empty cache each time) and warm runs (shared, primed cache); p50/p95 per format."""
    options = options.validate()
    out_root = Path(out_root)
    cold: list[dict[str, Any]] = []
    warm: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="bodyrig-scene-bench-") as tmp:
        for run in range(runs):
            cache = SceneCache(Path(tmp) / f"cold-{run}")
            for index, rel in enumerate(assets):
                cold.append(inspect_asset(source_root, rel, out_root / f"cold-{run}" / str(index), runtime=runtime,
                                          cache=cache, options=replace(options, use_hash_memo=False),
                                          work_root=work_root))
        shared = SceneCache(Path(tmp) / "warm")
        for index, rel in enumerate(assets):
            inspect_asset(source_root, rel, out_root / "prime" / str(index), runtime=runtime, cache=shared,
                          options=options, work_root=work_root)
        for run in range(runs):
            for index, rel in enumerate(assets):
                warm.append(inspect_asset(source_root, rel, out_root / f"warm-{run}" / str(index), runtime=runtime,
                                          cache=shared, options=options, work_root=work_root))
    ready = "conditioning_ready_at" if options.conditioning else "fully_analyzed_at"
    first_usable = percentile([r["timings_ms"][ready] for r in cold if isinstance(r["timings_ms"].get(ready), int)]
                              + [r["timings_ms"]["total"] for r in cold
                                 if (r["error"] or {}).get("code") in ("timeout", "budget_exhausted")], 95)
    slo = slo_report(cold + warm, conditioning=options.conditioning, first_usable_ms=first_usable)
    slo["first_usable"]["what"] = "p95 over cold runs of one asset each: time until it is usable; timeouts count"
    report = {"schema": "bodyrig-scene-inspection-bench-v1", "runtime": runtime.describe(), "runs": runs,
              "assets": list(assets), "cold": timing_stats(cold), "warm": timing_stats(warm), "slo": slo,
              "note": "measured on this machine; SLO targets in #1393 are validated only on the physical rig"}
    _atomic_write_json(out_root / "bench.json", report)
    return report
