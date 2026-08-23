from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


class IdentityCapturePreflightError(RuntimeError):
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


def _probe_script() -> str:
    return r'''
import json
result = {}
try:
    import cv2
    import numpy as np
    result["cv2_import"] = True
    result["numpy_import"] = True
    result["cv2_version"] = str(getattr(cv2, "__version__", "unknown"))
    result["numpy_version"] = str(getattr(np, "__version__", "unknown"))
    detector = cv2.HOGDescriptor_getDefaultPeopleDetector()
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(detector)
    result["hog_people_detector"] = bool(len(detector) > 0)
    front = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    profile = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
    result["haar_frontal"] = not front.empty()
    result["haar_profile"] = not profile.empty()
    result["grabcut"] = callable(getattr(cv2, "grabCut", None))
except Exception as exc:
    result["error"] = type(exc).__name__ + ": " + str(exc)
print(json.dumps(result, separators=(",", ":")))
'''


def run_preflight(*, external_python: str) -> dict[str, Any]:
    python_path = Path(external_python).expanduser().resolve()
    if not python_path.is_file():
        raise IdentityCapturePreflightError(f"external identity-capture Python not found: {python_path}")

    result: dict[str, Any] = {
        "format": "bodyrig-identity-capture-preflight",
        "version": 1,
        "ok": False,
        "checks": {},
        "errors": [],
    }
    errors: list[str] = result["errors"]
    try:
        completed = _run([str(python_path), "-c", _probe_script()])
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IdentityCapturePreflightError("identity capture capability probe could not run") from exc

    if completed.returncode != 0:
        errors.append(f"identity capture capability probe failed with exit code {completed.returncode}")
        probe: dict[str, Any] = {}
    else:
        try:
            probe = json.loads(completed.stdout)
        except json.JSONDecodeError:
            probe = {}
            errors.append("identity capture capability probe returned invalid JSON")

    result["checks"]["opencv_identity_capture"] = probe
    for field in (
        "cv2_import",
        "numpy_import",
        "hog_people_detector",
        "haar_frontal",
        "haar_profile",
        "grabcut",
    ):
        if probe.get(field) is not True:
            errors.append(f"identity capture capability missing: {field}")

    result["ok"] = not errors
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed preflight for BodyRig built-in identity capture.")
    parser.add_argument("--external-python", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    try:
        result = run_preflight(external_python=args.external_python)
    except IdentityCapturePreflightError as exc:
        print(f"BodyRig identity capture preflight: FAIL: {exc}", file=sys.stderr)
        return 1

    if args.out:
        output = Path(args.out).expanduser().resolve()
        if output.exists():
            print(f"BodyRig identity capture preflight: FAIL: output already exists: {output}", file=sys.stderr)
            return 1
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )

    if not result["ok"]:
        for error in result["errors"]:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    probe = result["checks"]["opencv_identity_capture"]
    print(
        "BodyRig identity capture preflight: OK | "
        f"OpenCV {probe.get('cv2_version', 'unknown')} | "
        f"NumPy {probe.get('numpy_version', 'unknown')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
