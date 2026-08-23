from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


class ObservationPreflightError(RuntimeError):
    pass


def _run(command: Sequence[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        check=False,
        timeout=timeout,
    )


def _opencv_probe_script() -> str:
    return r'''
import json
result = {}
try:
    import cv2
    result["cv2_import"] = True
    result["cv2_version"] = str(getattr(cv2, "__version__", "unknown"))
    hog = cv2.HOGDescriptor()
    detector = cv2.HOGDescriptor_getDefaultPeopleDetector()
    hog.setSVMDetector(detector)
    result["hog_people_detector"] = bool(len(detector) > 0)
    front = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    profile = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
    result["haar_frontal"] = not front.empty()
    result["haar_profile"] = not profile.empty()
except Exception as exc:
    result["cv2_import"] = False
    result["error"] = type(exc).__name__ + ": " + str(exc)
print(json.dumps(result, separators=(",", ":")))
'''


def run_preflight(*, external_python: str, ffmpeg: str, require_opencv: bool = True) -> dict[str, Any]:
    python_path = Path(external_python).expanduser().resolve()
    if not python_path.is_file():
        raise ObservationPreflightError(f"external observation Python not found: {python_path}")
    if not isinstance(ffmpeg, str) or not ffmpeg.strip():
        raise ObservationPreflightError("FFmpeg executable is required")
    if not isinstance(require_opencv, bool):
        raise ObservationPreflightError("require_opencv must be boolean")

    result: dict[str, Any] = {
        "format": "bodyrig-observation-preflight",
        "version": 1,
        "ok": False,
        "mode": "opencv+ffmpeg" if require_opencv else "ffmpeg-only",
        "checks": {},
        "errors": [],
    }
    errors: list[str] = result["errors"]

    if require_opencv:
        try:
            completed = _run([str(python_path), "-c", _opencv_probe_script()])
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ObservationPreflightError("OpenCV observation probe could not run") from exc
        if completed.returncode != 0:
            errors.append(f"OpenCV observation probe failed with exit code {completed.returncode}")
            probe: dict[str, Any] = {}
        else:
            try:
                probe = json.loads(completed.stdout)
            except json.JSONDecodeError:
                probe = {}
                errors.append("OpenCV observation probe returned invalid JSON")
        result["checks"]["opencv"] = probe
        for field in ("cv2_import", "hog_people_detector", "haar_frontal", "haar_profile"):
            if probe.get(field) is not True:
                errors.append(f"OpenCV observation capability missing: {field}")

    try:
        ffmpeg_result = _run([ffmpeg, "-hide_banner", "-version"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObservationPreflightError("FFmpeg observation probe could not run") from exc
    ffmpeg_ok = ffmpeg_result.returncode == 0 and "ffmpeg version" in (ffmpeg_result.stdout + ffmpeg_result.stderr).lower()
    result["checks"]["ffmpeg"] = {"available": ffmpeg_ok}
    if not ffmpeg_ok:
        errors.append("FFmpeg is unavailable or did not identify itself")

    result["ok"] = not errors
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed preflight for BodyRig Stash observation selection.")
    parser.add_argument("--external-python", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--ffmpeg-only", action="store_true", help="Skip built-in OpenCV/HOG/Haar checks for a custom analyzer")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        result = run_preflight(
            external_python=args.external_python,
            ffmpeg=args.ffmpeg,
            require_opencv=not args.ffmpeg_only,
        )
    except ObservationPreflightError as exc:
        print(f"BodyRig observation preflight: FAIL: {exc}", file=sys.stderr)
        return 1
    if args.out:
        output = Path(args.out).expanduser().resolve()
        if output.exists():
            print(f"BodyRig observation preflight: FAIL: output already exists: {output}", file=sys.stderr)
            return 1
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    if not result["ok"]:
        for error in result["errors"]:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if result["mode"] == "opencv+ffmpeg":
        opencv = result["checks"]["opencv"]
        print(f"BodyRig observation preflight: OK | OpenCV {opencv.get('cv2_version', 'unknown')} | FFmpeg OK")
    else:
        print("BodyRig observation preflight: OK | custom analyzer | FFmpeg OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
