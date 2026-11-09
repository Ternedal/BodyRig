"""Local-only bounded video frame sampler for BodyRig digital-twin bootstrap.

No Stash connection, person identification, pose inference or 3D reconstruction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time


def _run(argv: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=True)


def sample_timestamps(duration: float, max_frames: int) -> list[float]:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("video duration must be finite and positive")
    if not 1 <= max_frames <= 64:
        raise ValueError("max_frames must be 1..64")
    count = min(max_frames, max(1, math.ceil(duration)))
    return [round(duration * (i + 0.5) / count, 3) for i in range(count)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sample_video(source: Path, output: Path, *, max_frames: int = 12,
                 ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> dict:
    start = time.monotonic()
    source = source.absolute()
    output = output.absolute()
    if source.is_symlink() or not source.is_file():
        raise ValueError("source must be a regular non-symlink local file")
    if output == source or output in source.parents or source in output.parents:
        raise ValueError("source and output paths must be separate")
    if output.exists():
        raise FileExistsError("output directory already exists; refusing overwrite")
    probe = _run([ffprobe, "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=codec_name,width,height,duration:format=duration",
                  "-of", "json", str(source)], 45)
    data = json.loads(probe.stdout)
    streams = data.get("streams") or []
    if not streams:
        raise ValueError("video stream not found")
    stream = streams[0]
    duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0)
    timestamps = sample_timestamps(duration, max_frames)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".twin-sample-", dir=output.parent) as scratch:
        work = Path(scratch)
        frames = []
        for index, seconds in enumerate(timestamps):
            frame = work / f"frame-{index:03d}.jpg"
            _run([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
                  "-ss", str(seconds), "-i", str(source), "-map", "0:v:0",
                  "-frames:v", "1", "-q:v", "4", "-y", str(frame)], 60)
            if not frame.is_file() or frame.stat().st_size == 0:
                raise RuntimeError(f"frame extraction failed at {seconds}s")
            frames.append({"timestamp_ms": round(seconds * 1000),
                           "file": frame.name, "sha256": _sha256(frame)})
        manifest = {"schema": "bodyrig-video-samples-v1",
                    "state": "FRAMES_READY", "source_sha256": _sha256(source),
                    "duration_ms": round(duration * 1000),
                    "codec": stream.get("codec_name"), "width": stream.get("width"),
                    "height": stream.get("height"), "frames": frames,
                    "elapsed_ms": round((time.monotonic() - start) * 1000)}
        (work / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(work, output)
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-frames", type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(sample_video(args.source, args.out, max_frames=args.max_frames), indent=2))


if __name__ == "__main__":
    main()
