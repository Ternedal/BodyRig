from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .fidelity_convergence import FidelityConvergenceError, validate_measurement
from .rig_setup import RigSetupError, load_rig_setup
from .sith_setup import SithSetupError, load_setup_report
from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter


class FidelityEvaluatorRunnerError(RuntimeError):
    pass


def _read_result(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FidelityEvaluatorRunnerError("fidelity evaluator result is invalid JSON") from exc
    if not isinstance(value, dict):
        raise FidelityEvaluatorRunnerError("fidelity evaluator result must be an object")
    expected = {
        "format",
        "version",
        "measurement",
        "body_reference",
        "shape_hint",
        "diagnostics",
        "human_visual_authority_required",
        "semantics",
    }
    if set(value) != expected:
        raise FidelityEvaluatorRunnerError("fidelity evaluator result fields must match v1 exactly")
    if value.get("format") != "bodyrig-fidelity-evaluation" or value.get("version") != 1:
        raise FidelityEvaluatorRunnerError("fidelity evaluator result format/version mismatch")
    if value.get("human_visual_authority_required") is not True:
        raise FidelityEvaluatorRunnerError("fidelity evaluator must retain human visual authority")
    if value.get("semantics") != "visual-fidelity-not-identity-verification":
        raise FidelityEvaluatorRunnerError("fidelity evaluator semantics mismatch")
    try:
        value["measurement"] = validate_measurement(value.get("measurement"))
    except FidelityConvergenceError as exc:
        raise FidelityEvaluatorRunnerError(str(exc)) from exc
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run BodyRig's pinned OpenCV visual-fidelity evaluator through the configured WSL recovery environment."
    )
    parser.add_argument("--rig-setup", required=True)
    parser.add_argument("--reference-set", required=True)
    parser.add_argument("--render-set", required=True)
    parser.add_argument("--body-reference-rgba", default="")
    parser.add_argument("--iteration", required=True, type=int)
    parser.add_argument("--out", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)

    try:
        out = Path(args.out).expanduser().resolve()
        if out.exists():
            raise FidelityEvaluatorRunnerError(f"fidelity evaluator output already exists: {out}")
        rig = load_rig_setup(args.rig_setup, verify_files=True)
        sith = load_setup_report(rig["high_fidelity"]["setup_report"])
        distribution = str(sith["distribution"])
        external_python = str(rig["recovery"]["external_python"])
        if not distribution.strip() or not external_python.startswith("/"):
            raise FidelityEvaluatorRunnerError("rig setup does not contain a canonical WSL recovery runtime")

        converter = make_wsl_path_converter(args.wsl_exe, distribution)
        bridge = Path(__file__).resolve().parent / "bridges" / "opencv_fidelity_evaluator.py"
        if not bridge.is_file():
            raise FidelityEvaluatorRunnerError("built-in fidelity evaluator bridge is missing")
        reference = Path(args.reference_set).expanduser().resolve()
        render = Path(args.render_set).expanduser().resolve()
        if not reference.is_file() or not render.is_file():
            raise FidelityEvaluatorRunnerError("fidelity reference/render manifests must exist")
        body_reference = None
        if args.body_reference_rgba:
            body_reference = Path(args.body_reference_rgba).expanduser().resolve()
            if not body_reference.is_file():
                raise FidelityEvaluatorRunnerError("private body reference RGBA was not found")

        out.parent.mkdir(parents=True, exist_ok=True)
        command = [
            args.wsl_exe,
            "-d",
            distribution,
            "--",
            external_python,
            converter(str(bridge)),
            "--reference-set",
            converter(str(reference)),
            "--render-set",
            converter(str(render)),
            "--iteration",
            str(args.iteration),
            "--out",
            converter(str(out)),
        ]
        if body_reference is not None:
            command.extend(("--body-reference-rgba", converter(str(body_reference))))
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
            raise FidelityEvaluatorRunnerError(
                f"OpenCV fidelity evaluator exited with code {completed.returncode}: {detail}"
            )
        result = _read_result(out)
    except (
        OSError,
        subprocess.TimeoutExpired,
        RigSetupError,
        SithSetupError,
        WslBridgeError,
        FidelityEvaluatorRunnerError,
    ) as exc:
        print(f"BodyRig fidelity evaluator: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
