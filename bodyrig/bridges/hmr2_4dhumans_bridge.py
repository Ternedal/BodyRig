#!/usr/bin/env python
"""JSON-command bridge for pinned 4D-Humans/HMR2 + PHALP."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(_PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_PARENT))

from bodyrig.bridges.hmr2_config import (  # noqa: E402
    ADAPTER_NAME,
    ADAPTER_REVISION,
    FOUR_D_HUMANS_REVISION,
    NMR_REMOTE,
    NMR_REVISION,
    PHALP_REVISION,
    PHALP_TRACKER_BLOB_SHA1,
)
from bodyrig.bridges.phalp import canonicalize_phalp_results  # noqa: E402

SMPL_FILENAME = "basicModel_neutral_lbs_10_207_0_v1.0.0.pkl"
PHALP_SMPL_FILENAME = "SMPL_NEUTRAL.pkl"
PHALP_SMPL_SOURCE_HASH_FILENAME = ".bodyrig-source-sha256"
WSL_CUDA_DRIVER_LIB = Path("/usr/lib/wsl/lib")
CUDA_TOOLKIT_LIB = Path("/usr/local/cuda-11.7/lib64")

# PHALP's pinned tracker always initializes a second Detectron2 RPN model even
# though that model is only used when frames carry ground-truth boxes. BodyRig's
# recovery inputs are ordinary MP4 observation segments, for which PHALP's IO
# manager leaves additional_data empty. Patch only that unused initializer at
# process start so the large detector_x model never occupies GPU memory. The
# authoritative PHALP and 4D-Humans checkouts remain byte-for-byte untouched.
_PHALP_MP4_LOW_VRAM_LAUNCHER = (
    "import runpy,sys;"
    "from phalp.trackers.PHALP import PHALP;"
    "track_path=sys.argv[1];"
    "PHALP.setup_detectron2_with_RPN=lambda self:setattr(self,'detector_x',None);"
    "sys.argv=[track_path,*sys.argv[2:]];"
    "runpy.run_path(track_path,run_name='__main__')"
)


def _git_blob_sha1_bytes(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _source_blob_matches(path: Path, expected: str) -> bool:
    data = path.read_bytes()
    if _git_blob_sha1_bytes(data) == expected:
        return True
    normalized = data.replace(b"\r\n", b"\n")
    return normalized != data and _git_blob_sha1_bytes(normalized) == expected


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _normalize_git_url(value: str) -> str:
    normalized = value.strip().lower().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized


def _find_external_phalp_spec():
    """Find the installed PHALP package without the bridge-local phalp.py shadow.

    When this file is executed directly, Python adds ``bodyrig/bridges`` to
    ``sys.path``. That directory also contains BodyRig's conversion helper
    ``phalp.py``. A plain ``find_spec('phalp')`` can therefore resolve the
    helper module instead of the external PHALP package that preflight already
    validated. Temporarily exclude only this bridge directory while preserving
    the normal import machinery (including editable-install finders).
    """

    bridge_dir = Path(__file__).resolve().parent
    original = list(sys.path)
    filtered: list[str] = []
    for entry in original:
        try:
            candidate = Path(entry or os.getcwd()).resolve()
        except (OSError, RuntimeError):
            filtered.append(entry)
            continue
        if candidate == bridge_dir:
            continue
        filtered.append(entry)
    try:
        sys.path[:] = filtered
        return importlib.util.find_spec("phalp")
    finally:
        sys.path[:] = original


def _verify_nmr_install() -> None:
    """Require the exact pinned neural-renderer source at point of use."""

    try:
        __import__("neural_renderer")
    except ImportError as exc:
        raise RuntimeError("neural_renderer is not installed in the external recovery environment") from exc

    try:
        distribution = importlib.metadata.distribution("neural-renderer-pytorch")
        direct_raw = distribution.read_text("direct_url.json")
        direct = json.loads(direct_raw) if direct_raw else {}
    except (importlib.metadata.PackageNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError("could not verify neural-renderer installation authority") from exc

    url = direct.get("url")
    vcs_info = direct.get("vcs_info")
    commit = vcs_info.get("commit_id") if isinstance(vcs_info, dict) else None
    if not isinstance(url, str) or _normalize_git_url(url) != _normalize_git_url(NMR_REMOTE):
        raise RuntimeError(f"neural_renderer source must be {NMR_REMOTE}; got {url!r}")
    if commit != NMR_REVISION:
        raise RuntimeError(f"neural_renderer must be pinned to {NMR_REVISION}; got {commit!r}")


def _torch_lib_dir() -> Path:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("torch is required in the 4D-Humans environment") from exc
    torch_file = getattr(torch, "__file__", None)
    if not isinstance(torch_file, str) or not torch_file:
        raise RuntimeError("could not determine the installed torch package root")
    torch_lib = Path(torch_file).resolve().parent / "lib"
    if not torch_lib.is_dir():
        raise RuntimeError(f"torch library directory is missing: {torch_lib}")
    return torch_lib


def _recovery_loader_env() -> dict[str, str]:
    """Build the exact loader environment physically required by WSL HMR2.

    WSL exposes the Windows NVIDIA driver stub in /usr/lib/wsl/lib, while the
    PyTorch cu117 wheel carries cuDNN under torch/lib. The pinned tracker starts
    a fresh Python process, so bind those locations explicitly instead of
    depending on an operator shell's LD_LIBRARY_PATH.
    """

    torch_lib = _torch_lib_dir()
    required = [WSL_CUDA_DRIVER_LIB, torch_lib, CUDA_TOOLKIT_LIB]
    for directory in required:
        if not directory.is_dir():
            raise RuntimeError(f"required recovery library directory is missing: {directory}")
    if not (WSL_CUDA_DRIVER_LIB / "libcuda.so").is_file():
        raise RuntimeError("WSL CUDA driver stub is missing: /usr/lib/wsl/lib/libcuda.so")
    if not (torch_lib / "libcudnn_cnn_infer.so.8").is_file():
        raise RuntimeError(f"PyTorch cuDNN CNN inference library is missing: {torch_lib}/libcudnn_cnn_infer.so.8")

    entries = [str(path) for path in required]
    for entry in os.environ.get("LD_LIBRARY_PATH", "").split(":"):
        if entry and entry not in entries:
            entries.append(entry)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = ":".join(entries)
    return env


def _verify_cuda_loader_env(loader_env: dict[str, str]) -> None:
    probe = (
        "import ctypes; "
        "ctypes.CDLL('libcuda.so'); "
        "ctypes.CDLL('libcudnn_cnn_infer.so.8'); "
        "print('BodyRig CUDA loader: OK')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        env=loader_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stdout.strip()[-2000:]
        raise RuntimeError("CUDA/cuDNN loader preflight failed" + (f": {detail}" if detail else ""))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_phalp_smpl_cache(repo: Path) -> Path:
    """Seed PHALP's converted SMPL cache from BodyRig's local licensed model.

    The pinned PHALP revision falls back to an obsolete public URL when its
    cache is empty. BodyRig already requires the operator-provided neutral SMPL
    model under ``4D-Humans/data``. Reuse that authority instead of networking.
    A source SHA-256 sidecar prevents reuse of cache bytes derived from a
    different local model.
    """

    source = (repo / "data" / SMPL_FILENAME).resolve()
    if not source.is_file():
        raise RuntimeError(f"required SMPL model missing: data/{SMPL_FILENAME}")

    source_hash = _sha256_file(source)
    cache_dir = Path.home() / ".cache" / "phalp" / "3D" / "models" / "smpl"
    cache_path = cache_dir / PHALP_SMPL_FILENAME
    hash_path = cache_dir / PHALP_SMPL_SOURCE_HASH_FILENAME

    try:
        cached_hash = hash_path.read_text(encoding="ascii").strip().lower()
    except (OSError, UnicodeError):
        cached_hash = ""
    if cache_path.is_file() and cached_hash == source_hash:
        return cache_path

    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bodyrig-phalp-smpl-") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        staged_source = temp_dir / SMPL_FILENAME
        converted = temp_dir / f"{Path(SMPL_FILENAME).stem}_p3.pkl"
        shutil.copy2(source, staged_source)
        command = [
            sys.executable,
            "-c",
            "from phalp.utils.utils import convert_pkl; "
            f"convert_pkl({SMPL_FILENAME!r})",
        ]
        completed = subprocess.run(
            command,
            cwd=temp_dir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stdout.strip()[-2000:]
            raise RuntimeError(
                "could not convert local SMPL model for PHALP cache"
                + (f": {detail}" if detail else "")
            )
        if not converted.is_file():
            raise RuntimeError("PHALP SMPL conversion did not produce the expected Python 3 pickle")

        cache_tmp = cache_dir / f".{PHALP_SMPL_FILENAME}.bodyrig-tmp"
        hash_tmp = cache_dir / f".{PHALP_SMPL_SOURCE_HASH_FILENAME}.tmp"
        shutil.copy2(converted, cache_tmp)
        hash_tmp.write_text(source_hash + "\n", encoding="ascii")
        os.replace(cache_tmp, cache_path)
        os.replace(hash_tmp, hash_path)

    if not cache_path.is_file():
        raise RuntimeError("PHALP SMPL cache was not published")
    return cache_path


def _read_request() -> list[Path]:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise RuntimeError("invalid request JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"format", "version", "sources"}:
        raise RuntimeError("request fields must match BodyRig recovery request v1")
    if payload["format"] != "bodyrig-recovery-request" or payload["version"] != 1:
        raise RuntimeError("unsupported recovery request")
    raw_sources = payload["sources"]
    if not isinstance(raw_sources, list) or not 1 <= len(raw_sources) <= 10:
        raise RuntimeError("sources must contain 1..10 local video files")
    sources: list[Path] = []
    for raw in raw_sources:
        if not isinstance(raw, str) or not raw:
            raise RuntimeError("invalid source path")
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError(f"source is not a local file: {path}")
        sources.append(path)
    return sources


def _video_fps(source: Path) -> float:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("opencv/cv2 is required in the 4D-Humans environment") from exc
    capture = cv2.VideoCapture(str(source))
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
    finally:
        capture.release()
    if not (0.0 < fps <= 1000.0):
        raise RuntimeError(f"could not determine valid FPS for {source.name}")
    return fps


def _quoted_hydra_path(path: Path) -> str:
    escaped = path.as_posix().replace('"', '\\"')
    return f'"{escaped}"'


def _git_head(repo: Path, label: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    actual = completed.stdout.strip().lower()
    if completed.returncode != 0 or len(actual) != 40:
        raise RuntimeError(f"could not verify {label} Git HEAD")
    return actual


def _git_tracked_clean(repo: Path, label: str) -> bool:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"could not verify {label} tracked-file status")
    return not completed.stdout.strip()


def _verify_phalp_install(expected_repo: Path) -> None:
    expected_repo = expected_repo.expanduser().resolve()
    if not (expected_repo / "phalp").is_dir():
        raise RuntimeError(f"--phalp-repo does not look like a PHALP checkout: {expected_repo}")
    actual_head = _git_head(expected_repo, "PHALP")
    if actual_head != PHALP_REVISION:
        raise RuntimeError(
            f"PHALP checkout must be pinned to {PHALP_REVISION}; got {actual_head}"
        )
    if not _git_tracked_clean(expected_repo, "PHALP"):
        raise RuntimeError("PHALP checkout has modified tracked files; recovery is refused")

    spec = _find_external_phalp_spec()
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("PHALP is not installed in the external recovery environment")
    package_root = Path(next(iter(spec.submodule_search_locations))).resolve()
    expected_package_root = (expected_repo / "phalp").resolve()
    if not _same_path(package_root, expected_package_root):
        raise RuntimeError(
            f"installed PHALP import is not sourced from the authority checkout: {package_root}"
        )
    tracker = package_root / "trackers" / "PHALP.py"
    if not tracker.is_file():
        raise RuntimeError("PHALP tracker source could not be located")
    if not _source_blob_matches(tracker, PHALP_TRACKER_BLOB_SHA1):
        raise RuntimeError("PHALP tracker source does not match the pinned BodyRig revision")


def _track_command(repo: Path, source: Path, output_dir: Path) -> list[str]:
    track_script = str(repo / "track.py")
    overrides = [
        f"video.source={_quoted_hydra_path(source)}",
        f"video.output_dir={_quoted_hydra_path(output_dir)}",
        "render.enable=false",
        "overwrite=true",
    ]
    if source.suffix.lower() == ".mp4":
        return [
            sys.executable,
            "-c",
            _PHALP_MP4_LOW_VRAM_LAUNCHER,
            track_script,
            *overrides,
        ]
    return [sys.executable, track_script, *overrides]


def _run_source(repo: Path, source: Path, source_index: int, loader_env: dict[str, str]) -> list[dict]:
    try:
        import joblib
    except ImportError as exc:
        raise RuntimeError("joblib is required in the 4D-Humans environment") from exc
    with tempfile.TemporaryDirectory(prefix="bodyrig-4dh-") as temp_dir_raw:
        output_dir = Path(temp_dir_raw) / "output"
        command = _track_command(repo, source, output_dir)
        if source.suffix.lower() == ".mp4":
            print(
                "BodyRig recovery VRAM: skipped unused PHALP ground-truth RPN detector",
                file=sys.stderr,
            )
        completed = subprocess.run(
            command,
            cwd=repo,
            env=loader_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.stdout:
            print(completed.stdout[-12000:], file=sys.stderr)
        if completed.returncode != 0:
            raise RuntimeError(f"4D-Humans track.py failed with exit code {completed.returncode}")
        pkls = sorted((output_dir / "results").glob("*.pkl"))
        if len(pkls) != 1:
            raise RuntimeError(f"expected exactly one PHALP result pickle, found {len(pkls)}")
        frame_results = joblib.load(pkls[0])
        if not isinstance(frame_results, dict):
            raise RuntimeError("unexpected PHALP result shape")
        return canonicalize_phalp_results(frame_results, fps=_video_fps(source), source_index=source_index)


def _verify_repo(repo: Path) -> None:
    if not (repo / "track.py").is_file() or not (repo / "hmr2").is_dir():
        raise RuntimeError("--repo does not look like a 4D-Humans checkout")
    actual_head = _git_head(repo, "4D-Humans")
    if actual_head != FOUR_D_HUMANS_REVISION:
        raise RuntimeError(
            f"4D-Humans checkout must be pinned to {FOUR_D_HUMANS_REVISION}; got {actual_head}"
        )
    if not _git_tracked_clean(repo, "4D-Humans"):
        raise RuntimeError("4D-Humans checkout has modified tracked files; recovery is refused")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="Pinned shubham-goel/4D-Humans checkout")
    parser.add_argument("--phalp-repo", required=True, help="Exact pinned PHALP checkout authority")
    args = parser.parse_args()
    try:
        repo = Path(args.repo).expanduser().resolve()
        phalp_repo = Path(args.phalp_repo).expanduser().resolve()
        _verify_repo(repo)
        _verify_phalp_install(phalp_repo)
        _verify_nmr_install()
        loader_env = _recovery_loader_env()
        _verify_cuda_loader_env(loader_env)
        _ensure_phalp_smpl_cache(repo)
        sources = _read_request()
        tracks: list[dict] = []
        for index, source in enumerate(sources):
            tracks.extend(_run_source(repo, source, index, loader_env))
        if not tracks:
            raise RuntimeError("4D-Humans produced no track with at least two observed frames")
        json.dump({"format":"bodyrig-recovery","version":1,"adapter":ADAPTER_NAME,"revision":ADAPTER_REVISION,"tracks":tracks}, sys.stdout, separators=(",", ":"), allow_nan=False)
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        print(f"BodyRig 4D-Humans bridge: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())