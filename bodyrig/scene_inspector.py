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
from bodyrig.process_limits import Limits, run_bounded, tail

SCHEMA = "bodyrig-scene-inspection-v1"
BATCH_SCHEMA = "bodyrig-scene-inspection-batch-v1"
WORKER_CONTRACT = "bodyrig-scene-worker-v1"
INSPECTOR_VERSION = 1
FORMATS = {".blend": "blend", ".fbx": "fbx", ".obj": "obj", ".glb": "glb", ".gltf": "gltf"}
CONDITIONING = ("pose", "depth", "normal")
CONDITIONING_FILES = {"pose": ("pose.json", "pose.png"), "depth": ("depth.png",), "normal": ("normal.png",)}
ISOLATION_MODES = ("auto", "bwrap", "none")
WORKER_SCRIPT = Path(__file__).with_name("blender_scene_worker.py")
REPARSE_POINT = 0x400
DEAD_PROXY = "http://127.0.0.1:9"
OBJ_COUNT_LIMIT_BYTES = 256 * 1024 * 1024
GIB = 1024 * 1024 * 1024


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
        return replace(self, conditioning=tuple(sorted(set(self.conditioning))))


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
        paths = {self.worker_script.resolve().parent, exe.resolve().parent}
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
    try:
        if path.is_symlink():
            return True
        if os.name == "nt":
            return bool(path.lstat().st_file_attributes & REPARSE_POINT)
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
    names: list[str] = []
    with path.open("rb") as handle:
        for line in handle:
            if line[:6].lower() == b"mtllib":
                name = line[6:].strip().decode("utf-8", "replace")
                if name:
                    names.append(name)
    return names


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
        for name in _obj_material_libraries(asset):
            try:
                rel = reference_path(name)
                deps[rel] = contained_file(folder, rel, code="unsafe_reference")
            except SceneInspectionError as exc:
                warnings.append(f"material library not staged ({exc.code}): {name[:200]}")
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
        return self.objects / key[:2] / key

    def load(self, key: str) -> tuple[dict[str, Any], Path] | None:
        entry = self._entry(key)
        try:
            stored = json_io.read_json_object(entry / "result.json", error=ValueError, unreadable="cache", not_object="cache")
        except ValueError:
            return None
        files = stored.get("files", {})
        if stored.get("cache_key") != key or not isinstance(files, dict):
            return None
        for name, digest in files.items():
            candidate = entry / name
            if _is_link(candidate) or not candidate.is_file() or hashing.sha256_file(candidate) != digest:
                return None
        return stored, entry

    def store(self, key: str, payload: Mapping[str, Any], files: Mapping[str, Path]) -> None:
        entry = self._entry(key)
        if entry.exists():
            return
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
        version = _probe_output([str(exe), "-I", "-c", "import bpy, os, sys; sys.stdout.write(bpy.app.version_string); "
                                 "sys.stdout.flush(); os._exit(0)"]).strip().split()[0:1]
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
        "options": {"conditioning": list(options.conditioning), "resolution": options.resolution},
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


def _worker_document(path: Path) -> dict[str, Any]:
    return json_io.read_json_object(path, error=_InvalidAsset, unreadable="worker output unreadable",
                                    not_object="worker output is not an object")


def inspect_asset(source_root: Path, asset_rel: str, out_dir: Path, *, runtime: BlenderRuntime | None,
                  cache: SceneCache, options: InspectOptions, work_root: Path | None = None) -> dict[str, Any]:
    """Inspect one asset. Always returns a result and writes ``out_dir/scene.json``; never raises per asset."""
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

        step = time.perf_counter()
        deps = [{"path": rel, "bytes": path.stat().st_size, "sha256": cache.file_sha(path, use_memo=options.use_hash_memo),
                 "source": path} for rel, path in resolve_dependencies(asset, fmt, warnings)]
        result["dependencies"] = [{k: v for k, v in d.items() if k != "source"} for d in deps]
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
                    shutil.copyfile(entry / name, out_dir / name)
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
        src_dir, worker_out = jobdir / "src", jobdir / "out"
        src_dir.mkdir()
        worker_out.mkdir()
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
                       "--conditioning", ",".join(options.conditioning)]
        env = child_env(jobdir)
        argv = runtime.command(worker_args, threads=options.threads)
        if mode == "bwrap":
            argv = bwrap_prefix(jobdir, runtime.read_only_paths(), env) + argv
        result["isolation"] = _isolation_report(mode)
        step = time.perf_counter()
        run = run_bounded(argv, cwd=jobdir, env=env,
                          limits=Limits(wall_seconds=options.wall_seconds, memory_bytes=options.memory_bytes,
                                        cpu_seconds=options.cpu_seconds),
                          stdout_path=jobdir / "worker.stdout.txt", stderr_path=jobdir / "worker.stderr.txt")
        timings["blender"] = _ms(step)
        result["process"] = {"returncode": run.returncode, "timed_out": run.timed_out,
                             "memory_exceeded": run.memory_exceeded, "peak_memory_bytes": run.peak_memory_bytes,
                             "limits": run.applied}
        if run.timed_out:
            raise SceneInspectionError("timeout", f"Blender worker exceeded {options.wall_seconds:g}s")
        if run.memory_exceeded:
            raise SceneInspectionError("memory_limit", "Blender worker exceeded the memory limit")
        output = worker_out / "worker.json"
        if not output.is_file():
            raise SceneInspectionError("worker_failed", f"worker exited {run.returncode} without output: "
                                       f"{tail(jobdir / 'worker.stderr.txt', 1500)}")
        document = _worker_document(output)
        if document.get("contract") != WORKER_CONTRACT:
            raise SceneInspectionError("worker_contract", "worker output has the wrong contract")
        if run.returncode != 0 or document.get("error"):
            error = document.get("error") or {}
            raise SceneInspectionError("worker_failed", f"{error.get('type', 'exit')}: {error.get('message', run.returncode)}")
        scene = document.get("scene")
        if not isinstance(scene, dict):
            raise SceneInspectionError("worker_contract", "worker output has no scene")
        result["scene"] = scene
        result["worker_timings_ms"] = document.get("timings_ms")
        result["runtime"] = {**runtime.describe(), "reported": document.get("blender"),
                             "importer": document.get("importer"), "security": document.get("security")}
        warnings.extend(str(w)[:500] for w in document.get("warnings", [])[:50])

        files: dict[str, Path] = {}
        for kind in options.conditioning:
            for name in CONDITIONING_FILES[kind]:
                produced = worker_out / name
                if produced.is_file() and not _is_link(produced):
                    files[name] = produced
                else:
                    warnings.append(f"conditioning output missing: {name}")
        conditioning = document.get("conditioning")
        if isinstance(conditioning, dict):
            conditioning = {**conditioning, "files": {name: hashing.sha256_file(path) for name, path in files.items()}}
        result["conditioning"] = conditioning
        for name, path in files.items():
            shutil.copyfile(path, out_dir / name)
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
    metrics = ("total", "minimum_ready_at", "fully_analyzed_at", "blender", "stage", "discover")
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


def _slug(rel: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in rel.replace("/", "__"))[:180] or "asset"


def inspect_batch(source_root: Path, assets: Sequence[str], out_root: Path, *, runtime: BlenderRuntime | None,
                  cache: SceneCache, options: InspectOptions, jobs: int = 1, work_root: Path | None = None) -> dict[str, Any]:
    options = options.validate()
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

    def one(item: tuple[str, Path]) -> dict[str, Any]:
        return inspect_asset(source_root, item[0], item[1], runtime=runtime, cache=cache, options=options,
                             work_root=work_root)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        results = list(pool.map(one, targets))
    cache.save_memo()
    states: dict[str, int] = {}
    for item in results:
        states[item["state"]] = states.get(item["state"], 0) + 1
    summary = {
        "schema": BATCH_SCHEMA,
        "likeness_authority": False,
        "runtime": runtime.describe() if runtime else None,
        "options": {"conditioning": list(options.conditioning), "resolution": options.resolution,
                    "timeout_s": options.wall_seconds, "jobs": jobs, "isolation": options.isolation},
        "states": dict(sorted(states.items())),
        "wall_ms": _ms(started),
        "assets": [{"path": r["asset"]["path"], "out": str(t[1].relative_to(out_root)), "state": r["state"],
                    "error": r["error"], "cache_hit": r["cache"]["hit"], "timings_ms": r["timings_ms"]}
                   for r, t in zip(results, targets)],
        "timings": timing_stats(results),
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
    report = {"schema": "bodyrig-scene-inspection-bench-v1", "runtime": runtime.describe(), "runs": runs,
              "assets": list(assets), "cold": timing_stats(cold), "warm": timing_stats(warm),
              "note": "measured on this machine; SLO targets in #1393 are validated only on the physical rig"}
    _atomic_write_json(out_root / "bench.json", report)
    return report
