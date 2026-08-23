from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .sith_input import load_captured_identity
from .sith_preflight import SITH_CENTRALIZE_RGBA_BLOB, SITH_REVISION

STAGE_FORMAT = "bodyrig-sith-input-stage"
PREP_FORMAT = "bodyrig-sith-prepared-input"
VERSION = 1
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PINNED_CENTRALIZE = {"size": 1024, "ratio": 0.85}
PINNED_OPENPOSE = {
    "model": "BODY_25",
    "number_people_max": 1,
    "net_resolution": "-1x544",
    "scale_number": 3,
    "scale_gap": 0.25,
    "hand": True,
    "face": True,
}


class SithPrepareError(RuntimeError):
    pass


def _run_wsl(
    *,
    wsl_exe: str,
    distribution: str,
    command: Sequence[str],
    timeout: int = 1800,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [wsl_exe, "-d", distribution, "--", *command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        check=False,
        timeout=timeout,
    )


def _checked_wsl(
    *,
    wsl_exe: str,
    distribution: str,
    command: Sequence[str],
    label: str,
    timeout: int = 1800,
) -> str:
    try:
        completed = _run_wsl(
            wsl_exe=wsl_exe,
            distribution=distribution,
            command=command,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SithPrepareError(f"{label} could not complete") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-2000:]
        raise SithPrepareError(f"{label} failed with exit code {completed.returncode}: {detail}")
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise SithPrepareError(f"{label} must be lowercase SHA-256")
    return value


def _png_size(path: Path, *, label: str) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise SithPrepareError(f"{label} is not a canonical PNG")
    width, height = struct.unpack(">II", header[16:24])
    if not 1 <= width <= 16384 or not 1 <= height <= 16384:
        raise SithPrepareError(f"{label} dimensions are invalid")
    return width, height


def _read_json(path: Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
    if not path.is_file():
        raise SithPrepareError(f"{label} not found: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SithPrepareError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SithPrepareError(f"{label} must be an object")
    return raw, value


def load_stage(workspace: str | Path) -> tuple[Path, dict[str, Any], str]:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise SithPrepareError(f"identity workspace not found: {root}")
    try:
        captured = load_captured_identity(root)
    except ValueError as exc:
        raise SithPrepareError(f"captured identity binding is invalid: {exc}") from exc

    stage = root / "sith-input-v1"
    raw, manifest = _read_json(stage / "stage.json", label="SiTH stage manifest")
    required = {
        "format",
        "version",
        "capture_manifest_sha256",
        "subject_track_id",
        "source_rgba_sha256",
        "input_width",
        "input_height",
        "staged_rgba",
        "centralize",
        "openpose",
    }
    if set(manifest) != required:
        raise SithPrepareError("SiTH stage manifest fields must match v1 exactly")
    if manifest["format"] != STAGE_FORMAT or manifest["version"] != VERSION:
        raise SithPrepareError("unsupported SiTH stage format/version")
    if manifest["capture_manifest_sha256"] != captured.capture_manifest_sha256:
        raise SithPrepareError("SiTH stage is not bound to the current private capture manifest")
    if manifest["subject_track_id"] != captured.capture_manifest["subject_track_id"]:
        raise SithPrepareError("SiTH stage subject track does not match private capture")
    if _hash(manifest["source_rgba_sha256"], label="source_rgba_sha256") != captured.rgba_sha256:
        raise SithPrepareError("SiTH stage source RGBA hash does not match private capture")
    if manifest["staged_rgba"] != "rgba/000.png":
        raise SithPrepareError("SiTH stage must use canonical rgba/000.png")
    if isinstance(manifest["input_width"], bool) or not isinstance(manifest["input_width"], int):
        raise SithPrepareError("SiTH stage input_width must be an integer")
    if isinstance(manifest["input_height"], bool) or not isinstance(manifest["input_height"], int):
        raise SithPrepareError("SiTH stage input_height must be an integer")
    expected_size = captured.rgba_size
    if (manifest["input_width"], manifest["input_height"]) != expected_size:
        raise SithPrepareError("SiTH stage dimensions do not match private capture")
    if manifest["centralize"] != PINNED_CENTRALIZE:
        raise SithPrepareError("SiTH stage centralize profile is not the pinned v1 profile")
    if manifest["openpose"] != PINNED_OPENPOSE:
        raise SithPrepareError("SiTH stage OpenPose profile is not the pinned v1 profile")

    rgba = stage / "rgba" / "000.png"
    if not rgba.is_file() or _sha256(rgba) != captured.rgba_sha256:
        raise SithPrepareError("SiTH staged RGBA byte hash mismatch")
    if _png_size(rgba, label="SiTH staged RGBA") != expected_size:
        raise SithPrepareError("SiTH staged RGBA dimensions do not match private capture")
    return stage, manifest, hashlib.sha256(raw).hexdigest()


def _linux_path(path: Path, *, wsl_exe: str, distribution: str) -> str:
    value = _checked_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        command=["wslpath", "-a", str(path)],
        label="WSL path translation",
        timeout=30,
    ).strip()
    if not value.startswith("/") or "\n" in value or "\r" in value:
        raise SithPrepareError("wslpath returned an invalid absolute Linux path")
    return value


def _openpose_model_root(openpose: str) -> str:
    executable = PurePosixPath(openpose)
    suffix = PurePosixPath("build/examples/openpose/openpose.bin")
    suffix_parts = suffix.parts
    if len(executable.parts) <= len(suffix_parts) or tuple(executable.parts[-len(suffix_parts):]) != suffix_parts:
        raise SithPrepareError(
            "OpenPose executable must use the standard <root>/build/examples/openpose/openpose.bin layout"
        )
    root = PurePosixPath(*executable.parts[:-len(suffix_parts)])
    models = str(root / "models")
    if not models.startswith("/"):
        raise SithPrepareError("could not derive absolute OpenPose model directory")
    return models


def verify_sith_authority(*, distribution: str, repo: str, wsl_exe: str) -> None:
    if not repo.startswith("/"):
        raise SithPrepareError("SiTH repo must be an absolute Linux path")
    head = _checked_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        command=["git", "-C", repo, "rev-parse", "HEAD"],
        label="SiTH Git HEAD",
        timeout=30,
    ).lower()
    if head != SITH_REVISION:
        raise SithPrepareError(f"SiTH revision mismatch: {head or 'unknown'}")
    dirty = _checked_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        command=["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"],
        label="SiTH tracked-file status",
        timeout=30,
    )
    if dirty.strip():
        raise SithPrepareError("SiTH checkout has modified tracked files")
    centralizer = _checked_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        command=["git", "-C", repo, "hash-object", "tools/centralize_rgba.py"],
        label="SiTH centralize_rgba.py blob",
        timeout=30,
    ).lower()
    if centralizer != SITH_CENTRALIZE_RGBA_BLOB:
        raise SithPrepareError(f"SiTH centralize_rgba.py blob mismatch: {centralizer}")


def _triples(value: Any, *, label: str, expected_points: int) -> list[tuple[float, float, float]]:
    if not isinstance(value, list) or len(value) != expected_points * 3:
        raise SithPrepareError(f"OpenPose {label} must contain {expected_points * 3} values")
    result: list[tuple[float, float, float]] = []
    for index in range(expected_points):
        try:
            x, y, confidence = (float(item) for item in value[index * 3 : index * 3 + 3])
        except (TypeError, ValueError) as exc:
            raise SithPrepareError(f"OpenPose {label} contains a non-numeric value") from exc
        if not all(math.isfinite(item) for item in (x, y, confidence)):
            raise SithPrepareError(f"OpenPose {label} contains a non-finite value")
        if not 0.0 <= confidence <= 1.0:
            raise SithPrepareError(f"OpenPose {label} confidence is outside 0..1")
        result.append((x, y, confidence))
    return result


def validate_openpose_result(path: str | Path) -> dict[str, int]:
    _, payload = _read_json(Path(path).expanduser().resolve(), label="OpenPose keypoint result")
    people = payload.get("people")
    if not isinstance(people, list) or len(people) != 1 or not isinstance(people[0], Mapping):
        raise SithPrepareError("OpenPose result must contain exactly one person")
    person = people[0]
    body = _triples(person.get("pose_keypoints_2d"), label="BODY_25", expected_points=25)
    left = _triples(person.get("hand_left_keypoints_2d"), label="left hand", expected_points=21)
    right = _triples(person.get("hand_right_keypoints_2d"), label="right hand", expected_points=21)
    face = _triples(person.get("face_keypoints_2d"), label="face", expected_points=70)
    counts = {
        "body_confident": sum(conf >= 0.15 for _, _, conf in body),
        "left_hand_confident": sum(conf >= 0.10 for _, _, conf in left),
        "right_hand_confident": sum(conf >= 0.10 for _, _, conf in right),
        "face_confident": sum(conf >= 0.10 for _, _, conf in face),
    }
    if counts["body_confident"] < 8:
        raise SithPrepareError("OpenPose result has insufficient confident BODY_25 points")
    if counts["face_confident"] < 5:
        raise SithPrepareError("OpenPose result has insufficient confident face points")
    if counts["left_hand_confident"] < 1 or counts["right_hand_confident"] < 1:
        raise SithPrepareError("OpenPose result needs at least one confident point for each hand")
    return counts


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise SithPrepareError(f"SiTH prep evidence already exists: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def prepare_sith_input(
    *,
    workspace: str | Path,
    distribution: str,
    repo: str,
    python: str,
    openpose: str,
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    for label, value in (
        ("distribution", distribution),
        ("repo", repo),
        ("python", python),
        ("openpose", openpose),
        ("wsl_exe", wsl_exe),
    ):
        if not isinstance(value, str) or not value.strip():
            raise SithPrepareError(f"SiTH {label} is required")
    if not python.startswith("/") or not openpose.startswith("/"):
        raise SithPrepareError("SiTH Python and OpenPose paths must be absolute Linux paths")

    stage, stage_manifest, stage_sha = load_stage(workspace)
    prep_path = stage / "prep.json"
    if prep_path.exists():
        raise SithPrepareError("SiTH input has already been prepared; refusing cross-run reuse")
    images = stage / "images"
    if not images.is_dir() or any(images.iterdir()):
        raise SithPrepareError("SiTH images directory must exist and be empty before preparation")

    verify_sith_authority(distribution=distribution, repo=repo, wsl_exe=wsl_exe)
    linux_stage = _linux_path(stage, wsl_exe=wsl_exe, distribution=distribution)
    linux_rgba = f"{linux_stage}/rgba"
    linux_images = f"{linux_stage}/images"

    _checked_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        command=[
            python,
            f"{repo.rstrip('/')}/tools/centralize_rgba.py",
            "-i", linux_rgba,
            "-o", linux_images,
            "--ratio", "0.85",
            "--size", "1024",
        ],
        label="SiTH RGBA centralization",
        timeout=600,
    )
    centralized = images / "000.png"
    if sorted(path.name for path in images.iterdir()) != ["000.png"]:
        raise SithPrepareError("SiTH centralizer must produce exactly images/000.png")
    if _png_size(centralized, label="SiTH centralized image") != (1024, 1024):
        raise SithPrepareError("SiTH centralized image must be exactly 1024x1024")

    _checked_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        command=[
            openpose,
            "--image_dir", linux_images,
            "--write_json", linux_images,
            "--display", "0",
            "--model_pose", "BODY_25",
            "--model_folder", _openpose_model_root(openpose),
            "--net_resolution", "-1x544",
            "--scale_number", "3",
            "--scale_gap", "0.25",
            "--hand",
            "--face",
            "--render_pose", "0",
            "--number_people_max", "1",
        ],
        label="SiTH OpenPose keypoint extraction",
        timeout=1200,
    )
    keypoints = images / "000_keypoints.json"
    if sorted(path.name for path in images.iterdir()) != ["000.png", "000_keypoints.json"]:
        raise SithPrepareError("SiTH OpenPose stage must contain exactly 000.png and 000_keypoints.json")
    counts = validate_openpose_result(keypoints)

    prep = {
        "format": PREP_FORMAT,
        "version": VERSION,
        "stage_manifest_sha256": stage_sha,
        "subject_track_id": stage_manifest["subject_track_id"],
        "sith_revision": SITH_REVISION,
        "centralizer_blob": SITH_CENTRALIZE_RGBA_BLOB,
        "centralized_image_sha256": _sha256(centralized),
        "openpose_keypoints_sha256": _sha256(keypoints),
        "centralized_size": [1024, 1024],
        "openpose_quality": counts,
    }
    _write_new_json(prep_path, prep)
    return prep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a private BodyRig identity capture for pinned SiTH through WSL.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--repo", required=True, help="Absolute Linux path to pinned SiTH checkout")
    parser.add_argument("--python", required=True, help="Absolute Linux path to SiTH environment Python")
    parser.add_argument("--openpose", required=True, help="Absolute Linux path to OpenPose executable")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)
    try:
        prep = prepare_sith_input(
            workspace=args.workspace,
            distribution=args.distribution,
            repo=args.repo,
            python=args.python,
            openpose=args.openpose,
            wsl_exe=args.wsl_exe,
        )
    except (OSError, SithPrepareError) as exc:
        print(f"BodyRig SiTH prepare: FAIL: {exc}", file=sys.stderr)
        return 1
    quality = prep["openpose_quality"]
    print(
        "BodyRig SiTH prepare: PASS | "
        f"BODY_25={quality['body_confident']} | face={quality['face_confident']} | "
        f"hands={quality['left_hand_confident']}+{quality['right_hand_confident']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
