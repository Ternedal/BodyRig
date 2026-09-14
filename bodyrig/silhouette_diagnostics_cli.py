from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from .rig_setup import RigSetupError, load_rig_setup
from .sith_setup import SithSetupError, load_setup_report
from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter


FORMAT = "bodyrig-silhouette-diagnostic"
VERSION = 1
SEMANTICS = "private-diagnostic-only-not-fidelity-acceptance"


class SilhouetteDiagnosticRunnerError(RuntimeError):
    pass


def _number(value: object, *, field: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SilhouetteDiagnosticRunnerError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise SilhouetteDiagnosticRunnerError(f"{field} must be finite")
    if minimum is not None and number < minimum:
        raise SilhouetteDiagnosticRunnerError(f"{field} is below minimum")
    return number


def _sha(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise SilhouetteDiagnosticRunnerError(f"{field} must be lowercase SHA-256")
    return value


def _validate_side(value: object, *, field: str) -> dict:
    expected = {
        "mask_file",
        "profile_overlay_file",
        "mask",
        "width_profile",
        "head_shoulder_ratio",
        "head_shoulder_score",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise SilhouetteDiagnosticRunnerError(f"{field} fields must match v1 exactly")
    for name in ("mask_file", "profile_overlay_file"):
        leaf = value.get(name)
        if not isinstance(leaf, str) or Path(leaf).name != leaf or not leaf.lower().endswith(".png"):
            raise SilhouetteDiagnosticRunnerError(f"{field}.{name} must be a safe PNG filename")
    mask = value.get("mask")
    mask_fields = {
        "bbox_x",
        "bbox_y",
        "bbox_width",
        "bbox_height",
        "bbox_aspect_width_over_height",
        "foreground_fraction",
        "bbox_fill_fraction",
    }
    if not isinstance(mask, dict) or set(mask) != mask_fields:
        raise SilhouetteDiagnosticRunnerError(f"{field}.mask fields must match v1 exactly")
    for name in ("bbox_x", "bbox_y", "bbox_width", "bbox_height"):
        item = mask.get(name)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise SilhouetteDiagnosticRunnerError(f"{field}.mask.{name} must be a non-negative integer")
    for name in ("bbox_aspect_width_over_height", "foreground_fraction", "bbox_fill_fraction"):
        _number(mask.get(name), field=f"{field}.mask.{name}", minimum=0.0)
    profile = value.get("width_profile")
    if not isinstance(profile, list) or len(profile) != 9:
        raise SilhouetteDiagnosticRunnerError(f"{field}.width_profile must contain nine samples")
    for index, item in enumerate(profile):
        _number(item, field=f"{field}.width_profile[{index}]", minimum=0.0)
    _number(value.get("head_shoulder_ratio"), field=f"{field}.head_shoulder_ratio", minimum=0.0)
    score = _number(value.get("head_shoulder_score"), field=f"{field}.head_shoulder_score", minimum=0.0)
    if score > 1.0:
        raise SilhouetteDiagnosticRunnerError(f"{field}.head_shoulder_score exceeds maximum")
    return value


def _read_result(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SilhouetteDiagnosticRunnerError("silhouette diagnostic result is invalid JSON") from exc
    expected = {
        "format",
        "version",
        "evaluator_revision",
        "candidate_sha256",
        "body_reference_sha256",
        "profile_similarity",
        "candidate",
        "reference",
        "semantics",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise SilhouetteDiagnosticRunnerError("silhouette diagnostic fields must match v1 exactly")
    if value.get("format") != FORMAT or isinstance(value.get("version"), bool) or value.get("version") != VERSION:
        raise SilhouetteDiagnosticRunnerError("silhouette diagnostic format/version mismatch")
    if value.get("evaluator_revision") != "5":
        raise SilhouetteDiagnosticRunnerError("silhouette diagnostic requires evaluator revision 5")
    _sha(value.get("candidate_sha256"), field="candidate_sha256")
    _sha(value.get("body_reference_sha256"), field="body_reference_sha256")
    similarity = _number(value.get("profile_similarity"), field="profile_similarity", minimum=0.0)
    if similarity > 1.0:
        raise SilhouetteDiagnosticRunnerError("profile_similarity exceeds maximum")
    value["candidate"] = _validate_side(value.get("candidate"), field="candidate")
    value["reference"] = _validate_side(value.get("reference"), field="reference")
    if value.get("semantics") != SEMANTICS:
        raise SilhouetteDiagnosticRunnerError("silhouette diagnostic semantics mismatch")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate BodyRig silhouette mask/profile diagnostics through the configured WSL recovery environment."
    )
    parser.add_argument("--rig-setup", required=True)
    parser.add_argument("--render-set", required=True)
    parser.add_argument("--body-reference-rgba", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)

    try:
        out_dir = Path(args.out_dir).expanduser().resolve()
        if out_dir.exists():
            raise SilhouetteDiagnosticRunnerError(f"silhouette diagnostic output already exists: {out_dir}")
        render = Path(args.render_set).expanduser().resolve()
        body_reference = Path(args.body_reference_rgba).expanduser().resolve()
        if not render.is_file() or not body_reference.is_file():
            raise SilhouetteDiagnosticRunnerError("silhouette diagnostic render/body reference input was not found")

        rig = load_rig_setup(args.rig_setup, verify_files=True)
        sith = load_setup_report(rig["high_fidelity"]["setup_report"])
        distribution = str(sith["distribution"])
        external_python = str(rig["recovery"]["external_python"])
        if not distribution.strip() or not external_python.startswith("/"):
            raise SilhouetteDiagnosticRunnerError("rig setup does not contain a canonical WSL recovery runtime")

        converter = make_wsl_path_converter(args.wsl_exe, distribution)
        bridge = Path(__file__).resolve().parent / "bridges" / "opencv_silhouette_diagnostics.py"
        if not bridge.is_file():
            raise SilhouetteDiagnosticRunnerError("built-in silhouette diagnostic bridge is missing")

        command = [
            args.wsl_exe,
            "-d",
            distribution,
            "--",
            external_python,
            converter(str(bridge)),
            "--render-set",
            converter(str(render)),
            "--body-reference-rgba",
            converter(str(body_reference)),
            "--out-dir",
            converter(str(out_dir)),
        ]
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
            timeout=3600,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-3000:]
            raise SilhouetteDiagnosticRunnerError(
                f"OpenCV silhouette diagnostic exited with code {completed.returncode}: {detail}"
            )
        result = _read_result(out_dir / "silhouette-diagnostic.json")
        for side in ("candidate", "reference"):
            for field in ("mask_file", "profile_overlay_file"):
                artifact = out_dir / result[side][field]
                if not artifact.is_file():
                    raise SilhouetteDiagnosticRunnerError(f"silhouette diagnostic artifact was not written: {artifact.name}")
    except (
        OSError,
        subprocess.TimeoutExpired,
        RigSetupError,
        SithSetupError,
        WslBridgeError,
        SilhouetteDiagnosticRunnerError,
    ) as exc:
        print(f"BodyRig silhouette diagnostic: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
