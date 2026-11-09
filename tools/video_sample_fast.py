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

# Containers with no external segment/playlist references.
SAFE_DEMUXERS = {
    "mov,mp4,m4a,3gp,3g2,mj2": "mov",
    "matroska,webm": "matroska",
    "avi": "avi",
    "mpegts": "mpegts",
    "flv": "flv",
    "asf": "asf",
}


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


def _has_symlink_component(path: Path) -> bool:
    return any(part.is_symlink() for part in (path, *path.parents))


def sample_video(source: Path, output: Path, *, max_frames: int = 12,
                 ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
                 max_seconds: int = 900) -> dict:
    # Validate work bounds before spawning external tools or touching paths.
    if not isinstance(max_frames, int) or isinstance(max_frames, bool) or not 1 <= max_frames <= 64:
        raise ValueError("max_frames must be an integer in 1..64")
    if not isinstance(max_seconds, int) or isinstance(max_seconds, bool) or not 1 <= max_seconds <= 86400:
        raise ValueError("max_seconds must be an integer in 1..86400")
    start = time.monotonic()

    def bounded_run(argv: list[str], stage_timeout: int) -> subprocess.CompletedProcess[str]:
        remaining = max_seconds - (time.monotonic() - start)
        if remaining <= 0:
            raise TimeoutError("video sampling total deadline exceeded")
        try:
            return _run(argv, min(stage_timeout, remaining))
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("video sampling stage or total deadline exceeded") from exc

    source = source.absolute()
    output = output.absolute()
    if _has_symlink_component(source) or not source.is_file():
        raise ValueError("source must be a regular non-symlink local file")
    if output == source or output in source.parents or source in output.parents:
        raise ValueError("source and output paths must be separate")
    if _has_symlink_component(output):
        raise ValueError("output path must not contain symlinks")
    if output.exists():
        raise FileExistsError("output directory already exists; refusing overwrite")
    preview = output.parent / (output.name + ".preview.jpg")
    checkpoint = output.parent / (output.name + ".preview.json")
    if checkpoint.exists() or checkpoint.is_symlink():
        raise FileExistsError("preview checkpoint already exists; refusing overwrite")
    if preview.exists() or preview.is_symlink():
        raise FileExistsError("preview already exists; refusing overwrite")
    probe = bounded_run([ffprobe, "-v", "error", "-protocol_whitelist", "file",
                  "-select_streams", "v:0",
                  "-show_entries", "stream=codec_name,width,height,duration:format=duration,format_name",
                  "-of", "json", str(source)], 45)
    data = json.loads(probe.stdout)
    format_name = data.get("format", {}).get("format_name")
    demuxer = SAFE_DEMUXERS.get(format_name)
    if demuxer is None:
        raise ValueError(f"unsupported or indirect media container: {format_name!r}")
    streams = data.get("streams") or []
    if not streams:
        raise ValueError("video stream not found")
    stream = streams[0]
    duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0)
    timestamps = sample_timestamps(duration, max_frames)
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    if width <= 0 or height <= 0 or width * height > 7680 * 4320:
        raise ValueError("video dimensions are invalid or exceed 8K safety cap")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".twin-sample-", dir=output.parent) as scratch:
        work = Path(scratch)
        frames = []
        # A first-frame preview survives later extraction timeouts.
        for index, seconds in enumerate(timestamps):
            frame = work / f"frame-{index:03d}.jpg"
            bounded_run([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
                  "-protocol_whitelist", "file", "-f", demuxer,
                  "-ss", str(seconds), "-i", str(source), "-map", "0:v:0",
                  "-frames:v", "1", "-q:v", "4", "-y", str(frame)], 60)
            if not frame.is_file() or frame.stat().st_size == 0:
                raise RuntimeError(f"frame extraction failed at {seconds}s")
            frames.append({"timestamp_ms": round(seconds * 1000),
                           "file": frame.name, "sha256": _sha256(frame)})
            if index == 0:
                with frame.open("rb") as src, preview.open("xb") as dst:
                    for chunk in iter(lambda: src.read(1024 * 1024), b""):
                        dst.write(chunk)
                checkpoint_data = {
                    "schema": "bodyrig-video-preview-v1",
                    "state": "PREVIEW_READY",
                    "complete": False,
                    "preview_file": preview.name,
                    "preview_sha256": frames[0]["sha256"],
                    "timestamp_ms": frames[0]["timestamp_ms"],
                    "source_sha256": _sha256(source),
                }
                # Write fully in the private scratch directory, then publish
                # with an exclusive hard link (never replace an existing checkpoint).
                staged_checkpoint = work / "preview-checkpoint.json"
                with staged_checkpoint.open("x", encoding="utf-8") as handle:
                    json.dump(checkpoint_data, handle, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.link(staged_checkpoint, checkpoint)
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
    parser.add_argument("--max-seconds", type=int, default=900)
    args = parser.parse_args()
    print(json.dumps(sample_video(args.source, args.out, max_frames=args.max_frames, max_seconds=args.max_seconds), indent=2))


if __name__ == "__main__":
    main()
