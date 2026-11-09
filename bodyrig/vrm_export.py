"""Third-party 3D asset → VRM 1.0, fast, cached and bounded (#1393).

One asset (a model file, a folder, or a .zip pack such as an Open3DLab
download) becomes ``<out>/<name>.vrm`` plus ``<name>.vrm.json``:

- the asset is staged into a private job directory (zip entries checked for
  absolute paths, ``..``, links, entry count and total size);
- Blender runs ``blender_vrm_worker.py`` under the same bounds and isolation as
  the scene inspector (#1396): ``process_limits.run_bounded`` (Job Object on
  Windows, process group + RSS watchdog on POSIX), a scrubbed environment with a
  dead proxy and no GPU, and bubblewrap on Linux/WSL2 when available;
- the add-ons are read from a read-only ``--addons-dir`` set up once by
  ``scripts/vrm_export_setup.py`` (pinned commits, see ``ADDON_PINS``);
- the result is content-addressed: the same asset, worker, runtime, add-ons
  and options give a cache hit that only copies the finished ``.vrm``;
- the ``.vrm`` lands atomically (``.partial`` then rename), so a renderer that
  watches the output folder never reads half a file.

``watch`` keeps doing this for every file that appears in an inbox folder.

Personal use only. The VRM meta written by the worker marks every file
"only author, no redistribution, no modification". A converted third-party
model is never identity or likeness evidence: ``likeness_authority`` is always
false (#817).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from bodyrig import hashing, json_io
from bodyrig.process_limits import Limits, run_bounded, tail
from bodyrig.scene_inspector import (
    GIB,
    BlenderRuntime,
    SetupError,
    _atomic_write_json,
    _is_link,
    _remove_tree,
    _transient_start_failure,
    bwrap_available,
    bwrap_prefix,
    child_env,
)

SCHEMA = "bodyrig-vrm-export-v1"
WORKER_CONTRACT = "bodyrig-vrm-worker-v1"
EXPORT_VERSION = 1
HERE = Path(__file__).parent
WORKER_SCRIPT = HERE / "blender_vrm_worker.py"
#: Files staged next to the worker; their hashes are part of every cache key.
WORKER_FILES = (WORKER_SCRIPT, HERE / "blender_scene_worker.py", HERE / "humanoid_names.py", HERE / "vrm_paths.py",
                HERE / "blender_vrm_weights.py")
#: Suffix -> worker format. Order is the preference when a pack holds several models.
FORMATS = {".xps": "xps", ".mesh": "mesh", ".ascii": "ascii", ".fbx": "fbx", ".blend": "blend",
           ".glb": "glb", ".gltf": "gltf", ".vrm": "vrm"}
ISOLATION_MODES = ("auto", "bwrap", "none")
#: Pinned add-on sources (scripts/vrm_export_setup.py installs exactly these).
ADDON_PINS = {
    "io_scene_vrm": {"repo": "https://github.com/saturday06/VRM-Addon-for-Blender.git",
                     "commit": "f886e7fe283f08035273f5406fadebea6db64d60", "subdir": "src/io_scene_vrm"},
    "XNALara-io-Tools": {"repo": "https://github.com/Valerie-Bosco/XNALara-io-Tools.git",
                         "commit": "98e43f4f7fba9ea442884c36a7aae28acba4b0b2", "subdir": "XNALara-io-Tools",
                         "submodules": True},
}
ADDON_STAMP = "bodyrig-addons.json"
#: Report fields kept with a cache entry and restored on a cache hit.
CACHED_FIELDS = ("humanoid", "materials", "bones", "isolation", "runtime", "weight_transfer")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class VrmExportError(Exception):
    """A per-asset failure with a stable code; ``watch`` and batches continue."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ExportOptions:
    wall_seconds: float = 300.0
    memory_bytes: int | None = 8 * GIB
    cpu_seconds: int | None = None
    threads: int = 4
    isolation: str = "auto"
    max_texture: int = 2048
    max_asset_bytes: int = 8 * GIB
    max_zip_entries: int = 20_000

    def validate(self) -> "ExportOptions":
        if self.isolation not in ISOLATION_MODES:
            raise SetupError(f"isolation must be one of {', '.join(ISOLATION_MODES)}")
        if self.wall_seconds <= 0 or self.threads <= 0:
            raise SetupError("timeout and threads must be positive")
        if not 0 <= self.max_texture <= 16384:
            raise SetupError("max_texture must be between 0 (keep) and 16384")
        return self


# --- naming and staging -------------------------------------------------------------------

def output_name(asset: Path) -> str:
    name = asset.name
    for suffix in (".mesh.ascii", ".zip", *FORMATS):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return (_SAFE_NAME.sub("_", name).strip("._") or "model")[:80]


def _format_of(path: Path) -> str | None:
    return FORMATS.get(path.suffix.lower())


def choose_model(root: Path) -> Path:
    """The model file in a staged pack: best format first, then the largest file."""
    rank = {suffix: i for i, suffix in enumerate(FORMATS)}
    found = [p for p in root.rglob("*") if p.is_file() and not _is_link(p) and _format_of(p)]
    if not found:
        raise VrmExportError("no_model", "no supported model file in the asset")
    found.sort(key=lambda p: (rank[p.suffix.lower()], -p.stat().st_size, str(p)))
    return found[0]


def _zip_entry_is_link(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def extract_zip(archive: Path, dest: Path, *, max_bytes: int, max_entries: int) -> int:
    """Extract with path, link, count and size checks. Returns the bytes written."""
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            if len(infos) > max_entries:
                raise VrmExportError("invalid_asset", f"zip has {len(infos)} entries (limit {max_entries})")
            total = 0
            for info in infos:
                parts = Path(info.filename.replace("\\", "/")).parts
                if (not parts or info.filename.startswith(("/", "\\")) or ".." in parts
                        or re.match(r"^[A-Za-z]:", info.filename)):
                    raise VrmExportError("unsafe_path", f"unsafe path in zip: {info.filename!r}")
                if _zip_entry_is_link(info):
                    raise VrmExportError("unsafe_path", f"link in zip: {info.filename!r}")
                total += info.file_size
                if total > max_bytes:
                    raise VrmExportError("asset_too_large", f"zip expands beyond {max_bytes} bytes")
            dest.mkdir(parents=True, exist_ok=True)
            written = 0
            for info in infos:
                if info.is_dir():
                    continue
                target = dest.joinpath(*Path(info.filename.replace("\\", "/")).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as src, open(target, "wb") as out:
                    while chunk := src.read(1 << 20):
                        written += len(chunk)
                        if written > max_bytes:  # the header sizes can lie
                            raise VrmExportError("asset_too_large", f"zip expands beyond {max_bytes} bytes")
                        out.write(chunk)
            return written
    except zipfile.BadZipFile as exc:
        raise VrmExportError("invalid_asset", f"not a valid zip: {exc}") from exc


def copy_tree(source: Path, dest: Path, *, max_bytes: int) -> int:
    """Copy a folder without following or copying links."""
    written = 0
    for folder, dirs, files in os.walk(source, followlinks=False):
        rel = Path(folder).relative_to(source)
        dirs[:] = [d for d in dirs if not _is_link(Path(folder) / d)]
        for name in files:
            src = Path(folder) / name
            if _is_link(src):
                continue
            written += src.stat().st_size
            if written > max_bytes:
                raise VrmExportError("asset_too_large", f"folder is larger than {max_bytes} bytes")
            target = dest / rel / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
    return written


def asset_fingerprint(asset: Path) -> str:
    if asset.is_file():
        return hashing.sha256_file(asset)
    entries = []
    for path in sorted(p for p in asset.rglob("*") if p.is_file() and not _is_link(p)):
        entries.append([path.relative_to(asset).as_posix(), hashing.sha256_file(path)])
    return hashing.sha256_bytes(hashing.canonical_json_bytes(entries))


def addons_fingerprint(addons_dir: Path) -> dict[str, Any]:
    stamp = addons_dir / ADDON_STAMP
    if stamp.is_file():
        return json_io.read_json_object(stamp, error=SetupError, unreadable="add-on stamp unreadable",
                                        not_object="add-on stamp is not an object")
    listing = sorted([p.relative_to(addons_dir).as_posix(), p.stat().st_size]
                     for p in addons_dir.rglob("*.py") if p.is_file())
    return {"unstamped_listing_sha256": hashing.sha256_bytes(hashing.canonical_json_bytes(listing))}


# --- cache --------------------------------------------------------------------------------

class VrmCache:
    """``<root>/<key>/model.vrm`` + ``report.json``; entries are written whole or not at all."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _entry(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise VrmExportError("internal_error", "bad cache key")
        return self.root / key[:2] / key

    def load(self, key: str) -> tuple[dict[str, Any], Path] | None:
        entry = self._entry(key)
        vrm, report = entry / "model.vrm", entry / "report.json"
        if _is_link(entry) or not vrm.is_file() or not report.is_file() or _is_link(vrm):
            return None
        try:
            stored = json_io.read_json_object(report, error=ValueError, unreadable="x", not_object="x")
        except ValueError:
            return None
        if stored.get("cache_key") != key or stored.get("vrm_sha256") != hashing.sha256_file(vrm):
            return None
        return stored, vrm

    def store(self, key: str, report: Mapping[str, Any], vrm: Path) -> None:
        entry = self._entry(key)
        if entry.exists():
            return
        entry.parent.mkdir(parents=True, exist_ok=True)
        tmp = entry.parent / f".tmp-{uuid.uuid4().hex}"
        tmp.mkdir()
        try:
            shutil.copyfile(vrm, tmp / "model.vrm")
            _atomic_write_json(tmp / "report.json", {**report, "cache_key": key,
                                                     "vrm_sha256": hashing.sha256_file(tmp / "model.vrm")})
            try:
                os.replace(tmp, entry)
            except OSError:
                if not entry.exists():
                    raise
        finally:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)


def cache_key(runtime: BlenderRuntime, options: ExportOptions, asset_sha: str, addons: Mapping[str, Any],
              weight_reference_sha: str | None = None) -> str:
    material = {
        "schema": SCHEMA,
        "export_version": EXPORT_VERSION,
        "worker_files": {p.name: hashing.sha256_file(p) for p in WORKER_FILES},
        "runtime": {"kind": runtime.kind, "version": runtime.version},
        "addons": addons,
        "options": {"max_texture": options.max_texture},
        "asset_sha256": asset_sha,
    }
    if weight_reference_sha:  # keeps keys of exports without a reference unchanged
        material["weight_reference_sha256"] = weight_reference_sha
    return hashing.sha256_bytes(hashing.canonical_json_bytes(material))


# --- one asset ----------------------------------------------------------------------------

def _ms(start: float) -> int:
    return int(round((time.perf_counter() - start) * 1000))


def _isolation(options: ExportOptions) -> str:
    if options.isolation == "none":
        return "none"
    if bwrap_available():
        return "bwrap"
    if options.isolation == "bwrap":
        raise SetupError("isolation=bwrap requested but bubblewrap is not usable here")
    return "none"


def _stage(asset: Path, dest: Path, options: ExportOptions) -> Path:
    """Stage a file, folder or zip into ``dest`` with the same checks; return the chosen model."""
    dest.mkdir(parents=True, exist_ok=True)
    if asset.is_dir():
        copy_tree(asset, dest, max_bytes=options.max_asset_bytes)
    elif asset.suffix.lower() == ".zip":
        extract_zip(asset, dest, max_bytes=options.max_asset_bytes, max_entries=options.max_zip_entries)
    else:
        if asset.stat().st_size > options.max_asset_bytes:
            raise VrmExportError("asset_too_large", "asset is larger than the limit")
        shutil.copyfile(asset, dest / asset.name)
    return choose_model(dest)


def _deliver(vrm: Path, out_dir: Path, name: str) -> Path:
    """Copy into ``out_dir`` atomically; refuse to write through a link."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.vrm"
    if _is_link(target):
        raise VrmExportError("unsafe_path", f"output file is a link: {target}")
    partial = out_dir / f".{name}.{uuid.uuid4().hex}.vrm.partial"
    shutil.copyfile(vrm, partial)
    os.replace(partial, target)
    return target


def export_asset(asset: Path, out_dir: Path, *, runtime: BlenderRuntime, addons_dir: Path,
                 options: ExportOptions = ExportOptions(), cache_root: Path | None = None,
                 work_root: Path | None = None, weight_reference: Path | None = None) -> dict[str, Any]:
    """Convert one asset. Always writes ``<out>/<name>.vrm.json``; never raises for asset failures.

    ``weight_reference`` (#1401): a model with a good rig (file, folder or zip) whose
    hip/groin weights are transferred onto the asset. Optional; a reference that does
    not fit leaves the asset's weights unchanged and says why in ``weight_transfer``.
    """
    options = options.validate()
    started = time.perf_counter()
    asset = Path(asset)
    name = output_name(asset)
    timings: dict[str, int] = {}
    warnings: list[str] = []
    result: dict[str, Any] = {"schema": SCHEMA, "source": asset.name, "name": name, "state": "FAILED",
                              "likeness_authority": False, "timings_ms": timings, "warnings": warnings}
    jobdir: Path | None = None
    try:
        if _is_link(asset) or not asset.exists():
            raise VrmExportError("invalid_asset", "asset is missing or a link")
        step = time.perf_counter()
        asset_sha = asset_fingerprint(asset)
        addons = addons_fingerprint(Path(addons_dir))
        reference_sha = None
        if weight_reference is not None:
            weight_reference = Path(weight_reference)
            if _is_link(weight_reference) or not weight_reference.exists():
                raise VrmExportError("invalid_asset", "weight reference is missing or a link")
            reference_sha = asset_fingerprint(weight_reference)
            result["weight_reference"] = {"source": weight_reference.name, "sha256": reference_sha}
        key = cache_key(runtime, options, asset_sha, addons, reference_sha)
        result["asset_sha256"] = asset_sha
        result["cache"] = {"key": key, "hit": False}
        timings["fingerprint"] = _ms(step)

        cache = VrmCache(cache_root) if cache_root else None
        if cache is not None and (hit := cache.load(key)) is not None:
            stored, cached_vrm = hit
            step = time.perf_counter()
            target = _deliver(cached_vrm, out_dir, name)
            timings["deliver"] = _ms(step)
            result.update({k: stored[k] for k in CACHED_FIELDS if k in stored})
            result.update(state="READY", output=target.name, vrm_sha256=stored["vrm_sha256"])
            result["cache"]["hit"] = True
            return result

        step = time.perf_counter()
        mode = _isolation(options)
        base = Path(work_root) if work_root else Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        jobdir = Path(tempfile.mkdtemp(prefix="bodyrig-vrm-", dir=base)).resolve()
        src_dir, out_tmp, worker_dir = jobdir / "src", jobdir / "out", jobdir / "worker"
        for folder in (src_dir, out_tmp, worker_dir):
            folder.mkdir()
        for file in WORKER_FILES:
            shutil.copyfile(file, worker_dir / file.name)
        model = _stage(asset, src_dir, options)
        if asset_fingerprint(asset) != asset_sha:
            raise VrmExportError("source_changed", "the asset changed while it was staged")
        result["model_file"] = model.relative_to(src_dir).as_posix()
        reference_args: list[str] = []
        if weight_reference is not None:
            ref_dir = jobdir / "ref"
            ref_model = _stage(weight_reference, ref_dir, options)
            if asset_fingerprint(weight_reference) != reference_sha:
                raise VrmExportError("source_changed", "the weight reference changed while it was staged")
            result["weight_reference"]["model_file"] = ref_model.relative_to(ref_dir).as_posix()
            reference_args = ["--weight-reference", str(ref_model), "--weight-reference-format",
                              _format_of(ref_model) or "", "--weight-reference-root", str(ref_dir)]
        timings["stage"] = _ms(step)

        worker_args = ["--input", str(model), "--format", _format_of(model) or "", "--staging-root", str(src_dir),
                       "--addons-dir", str(Path(addons_dir).resolve()), "--output", str(out_tmp / "worker.json"),
                       "--output-vrm", str(out_tmp / "model.vrm"), "--name", name,
                       "--max-texture", str(options.max_texture), *reference_args]
        env = child_env(jobdir)
        argv = replace(runtime, worker_script=worker_dir / WORKER_SCRIPT.name).command(worker_args,
                                                                                        threads=options.threads)
        if mode == "bwrap":
            argv = bwrap_prefix(jobdir, [*runtime.read_only_paths(), Path(addons_dir).resolve()], env) + argv
        result["isolation"] = ({"mode": "bwrap", "network": "unshared namespace"} if mode == "bwrap" else
                               {"mode": "process-only", "network": "dead proxy only; not isolated"})
        step = time.perf_counter()
        limits = Limits(wall_seconds=options.wall_seconds, memory_bytes=options.memory_bytes,
                        cpu_seconds=options.cpu_seconds)
        attempts = 0
        while True:  # one retry, only when Blender failed to load before the worker ran (#1396 c650f273)
            attempts += 1
            run = run_bounded(argv, cwd=jobdir, env=env, limits=limits,
                              stdout_path=jobdir / "worker.stdout.txt", stderr_path=jobdir / "worker.stderr.txt")
            if attempts == 1 and _transient_start_failure(run, out_tmp / "worker.json", jobdir / "worker.stderr.txt"):
                warnings.append("Blender failed to load before the worker started (bpy import); retried once")
                time.sleep(1.0)
                continue
            break
        timings["blender"] = _ms(step)
        result["process"] = {"returncode": run.returncode, "timed_out": run.timed_out,
                             "memory_exceeded": run.memory_exceeded, "peak_memory_bytes": run.peak_memory_bytes,
                             "attempts": attempts, "limits": run.applied}
        if run.timed_out:
            raise VrmExportError("timeout", f"Blender worker exceeded {options.wall_seconds:g}s")
        if run.memory_exceeded:
            raise VrmExportError("memory_limit", "Blender worker exceeded the memory limit")
        doc_path = out_tmp / "worker.json"
        if not doc_path.is_file():
            raise VrmExportError("worker_failed", f"worker exited {run.returncode} without output: "
                                 f"{tail(jobdir / 'worker.stderr.txt', 1500)}")
        document = json_io.read_json_object(doc_path, error=ValueError, unreadable="worker output unreadable",
                                            not_object="worker output is not an object")
        if document.get("contract") != WORKER_CONTRACT or document.get("complete") is not True:
            raise VrmExportError("worker_contract", "worker output has the wrong contract or is incomplete")
        for field in ("humanoid", "materials", "bones", "addons", "importer", "security", "weight_transfer"):
            if field in document:
                result[field] = document[field]
        result["worker_timings_ms"] = document.get("timings_ms")
        result["runtime"] = {**runtime.describe(), "reported": document.get("blender")}
        warnings.extend(str(w)[:500] for w in document.get("warnings", [])[:50])
        if document.get("error"):
            error = document["error"] if isinstance(document["error"], dict) else {}
            raise VrmExportError("worker_failed", f"{error.get('type', 'error')}: {error.get('message', '')}")
        vrm = out_tmp / "model.vrm"
        if not vrm.is_file() or _is_link(vrm):
            raise VrmExportError("worker_contract", "worker reported success but wrote no VRM")
        if run.returncode != 0:
            warnings.append(f"worker exited {run.returncode} after writing a complete result")

        step = time.perf_counter()
        target = _deliver(vrm, out_dir, name)
        result.update(state="READY", output=target.name, vrm_sha256=hashing.sha256_file(target))
        timings["deliver"] = _ms(step)
        if cache is not None:
            cache.store(key, {k: result[k] for k in CACHED_FIELDS
                              if k in result}, vrm)
    except VrmExportError as exc:
        result["error"] = {"code": exc.code, "message": str(exc)[:2000]}
    except SetupError:
        raise
    except Exception as exc:  # isolate watch/batch from anything unexpected in one asset
        result["error"] = {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"[:2000]}
    finally:
        if jobdir is not None:
            removed = _remove_tree(jobdir)
            result["cleanup"] = {"staging_removed": removed}
            if not removed:
                warnings.append(f"staging directory could not be removed: {jobdir}")
        timings["total"] = _ms(started)
        _atomic_write_json(Path(out_dir) / f"{name}.vrm.json", result)
    return result


# --- watch --------------------------------------------------------------------------------

def _stable(path: Path, wait: float) -> bool:
    """True when a dropped file or folder has stopped changing size."""
    def size() -> int:
        if path.is_file():
            return path.stat().st_size
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    try:
        first = size()
        time.sleep(wait)
        return first == size() and first > 0
    except FileNotFoundError:
        return False


def _accepted(path: Path) -> bool:
    if path.name.startswith(".") or path.name in ("done", "failed") or _is_link(path):
        return False
    return path.is_dir() or path.suffix.lower() == ".zip" or _format_of(path) is not None


def watch(inbox: Path, out_dir: Path, *, runtime: BlenderRuntime, addons_dir: Path,
          options: ExportOptions = ExportOptions(), cache_root: Path | None = None,
          work_root: Path | None = None, weight_reference: Path | None = None, poll_seconds: float = 0.5, settle_seconds: float = 0.5,
          max_items: int | None = None, log: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """Convert every asset that appears in ``inbox``; move it to ``done/`` or ``failed/``."""
    inbox = Path(inbox)
    for folder in ("done", "failed"):
        (inbox / folder).mkdir(parents=True, exist_ok=True)
    log(f"watching {inbox} -> {out_dir}")
    results: list[dict[str, Any]] = []
    while max_items is None or len(results) < max_items:
        candidates = sorted(p for p in inbox.iterdir() if _accepted(p))
        for path in candidates:
            if not _stable(path, settle_seconds):
                continue
            result = export_asset(path, out_dir, runtime=runtime, addons_dir=addons_dir, options=options,
                                  cache_root=cache_root, work_root=work_root, weight_reference=weight_reference)
            destination = inbox / ("done" if result["state"] == "READY" else "failed") / path.name
            if destination.exists():
                destination = destination.with_name(f"{destination.stem}.{uuid.uuid4().hex[:8]}{destination.suffix}")
            shutil.move(str(path), destination)
            cached = " (cache)" if result.get("cache", {}).get("hit") else ""
            error = result.get("error", {}).get("message", "")
            log(f"[{result['state']}] {path.name} {result['timings_ms'].get('total')} ms{cached} {error}".rstrip())
            results.append(result)
            if max_items is not None and len(results) >= max_items:
                break
        else:
            time.sleep(poll_seconds)
    return results


def batch_summary(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {"total": len(results), "ready": sum(r["state"] == "READY" for r in results),
            "cache_hits": sum(bool(r.get("cache", {}).get("hit")) for r in results),
            "failed": [r["source"] for r in results if r["state"] != "READY"]}


def dumps(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
