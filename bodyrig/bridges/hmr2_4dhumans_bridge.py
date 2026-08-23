#!/usr/bin/env python
"""JSON-command bridge for pinned 4D-Humans/HMR2 + PHALP.

Run this file with the external 4D-Humans Python runtime. It deliberately
bootstraps the BodyRig package from the filesystem containing this script, so
BodyRig does not need to be installed into the heavy recovery environment.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# When this script is executed directly, Python normally puts only
# bodyrig/bridges on sys.path. Add the package parent (repo root/site-packages)
# so the pure-Python converter/config can be imported in the external venv.
_PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(_PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_PARENT))

from bodyrig.bridges.hmr2_config import (  # noqa: E402
    ADAPTER_NAME,
    ADAPTER_REVISION,
    FOUR_D_HUMANS_REVISION,
)
from bodyrig.bridges.phalp import canonicalize_phalp_results  # noqa: E402


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


def _run_source(repo: Path, source: Path, source_index: int) -> list[dict]:
    try:
        import joblib
    except ImportError as exc:
        raise RuntimeError("joblib is required in the 4D-Humans environment") from exc

    with tempfile.TemporaryDirectory(prefix="bodyrig-4dh-") as temp_dir_raw:
        output_dir = Path(temp_dir_raw) / "output"
        command = [
            sys.executable,
            str(repo / "track.py"),
            f"video.source={_quoted_hydra_path(source)}",
            f"video.output_dir={_quoted_hydra_path(output_dir)}",
            "render.enable=false",
            "overwrite=true",
        ]
        completed = subprocess.run(
            command,
            cwd=repo,
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
        # The pickle is created inside our private temp directory by the child
        # process above. Arbitrary user-provided pickle input is never loaded.
        frame_results = joblib.load(pkls[0])
        if not isinstance(frame_results, dict):
            raise RuntimeError("unexpected PHALP result shape")
        return canonicalize_phalp_results(
            frame_results,
            fps=_video_fps(source),
            source_index=source_index,
        )


def _verify_repo(repo: Path) -> None:
    if not (repo / "track.py").is_file() or not (repo / "hmr2").is_dir():
        raise RuntimeError("--repo does not look like a 4D-Humans checkout")
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    head = completed.stdout.strip().lower()
    if completed.returncode != 0 or head != FOUR_D_HUMANS_REVISION:
        raise RuntimeError(
            f"4D-Humans checkout must be pinned to {FOUR_D_HUMANS_REVISION}; got {head or 'unknown'}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="Pinned shubham-goel/4D-Humans checkout")
    args = parser.parse_args()
    try:
        repo = Path(args.repo).expanduser().resolve()
        _verify_repo(repo)
        sources = _read_request()
        tracks: list[dict] = []
        for index, source in enumerate(sources):
            tracks.extend(_run_source(repo, source, index))
        if not tracks:
            raise RuntimeError("4D-Humans produced no track with at least two observed frames")
        json.dump({
            "format": "bodyrig-recovery",
            "version": 1,
            "adapter": ADAPTER_NAME,
            "revision": ADAPTER_REVISION,
            "tracks": tracks,
        }, sys.stdout, separators=(",", ":"), allow_nan=False)
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        print(f"BodyRig 4D-Humans bridge: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
