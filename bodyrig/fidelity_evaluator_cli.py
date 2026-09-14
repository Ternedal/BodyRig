from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from .fidelity_convergence import FidelityConvergenceError, validate_measurement
from .rig_setup import RigSetupError, load_rig_setup
from .sith_setup import SithSetupError, load_setup_report
from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter


SUPPORTED_EXTENDED_REVISIONS = {"4", "5"}
COMPONENT_VISIBILITY_FORMAT = "bodyrig-component-visibility-probe"
COMPONENT_VISIBILITY_SEMANTICS = "component-presence-and-runtime-visibility-not-visual-quality-acceptance"
REQUIRED_VISIBLE_COMPONENTS = {
    "hair": "BodyRigSourceHairReview",
    "eyes": "BodyRigSourceEyeReview",
    "face-secondary": "BodyRigFaceSecondaryReview",
    "fingernails": "BodyRigFingernailPlates",
    "toenails": "BodyRigToenailPlates",
}


class FidelityEvaluatorRunnerError(RuntimeError):
    pass


def _number(value: object, *, field: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FidelityEvaluatorRunnerError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise FidelityEvaluatorRunnerError(f"{field} must be finite")
    if minimum is not None and number < minimum:
        raise FidelityEvaluatorRunnerError(f"{field} is below minimum")
    if maximum is not None and number > maximum:
        raise FidelityEvaluatorRunnerError(f"{field} exceeds maximum")
    return number


def _load_json_object(path: Path, *, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FidelityEvaluatorRunnerError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise FidelityEvaluatorRunnerError(f"{label} must be an object")
    return value


def _lower_sha256(value: object, *, field: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise FidelityEvaluatorRunnerError(f"{field} must be a canonical lowercase SHA-256")
    return text


def _validate_component_visibility(render_manifest: Path) -> dict:
    if render_manifest.name != "fidelity-render-set.json":
        raise FidelityEvaluatorRunnerError("strict fidelity scoring requires fidelity-render-set.json")
    snapshot_root = render_manifest.parent
    render_root = snapshot_root.parent
    report_path = render_root / "component-visibility-probe.json"
    if not report_path.is_file():
        raise FidelityEvaluatorRunnerError(
            "fresh full-fidelity scoring requires component-visibility-probe.json; "
            "historical incomplete renders must use the explicit diagnostic override"
        )

    render_set = _load_json_object(render_manifest, label="fidelity render set")
    report = _load_json_object(report_path, label="component visibility probe")
    expected_fields = {
        "format",
        "version",
        "observed_at",
        "bodyrig_revision",
        "platform",
        "body_id",
        "package_sha256",
        "avatar_sha256",
        "required_component_count",
        "present_component_count",
        "visible_component_count",
        "all_required_present_and_visible",
        "components",
        "human_visual_authority_required",
        "production_activation",
        "semantics",
    }
    if set(report) != expected_fields:
        raise FidelityEvaluatorRunnerError("component visibility probe fields must match v1 exactly")
    if (
        report.get("format") != COMPONENT_VISIBILITY_FORMAT
        or isinstance(report.get("version"), bool)
        or report.get("version") != 1
        or report.get("semantics") != COMPONENT_VISIBILITY_SEMANTICS
        or report.get("human_visual_authority_required") is not True
        or report.get("production_activation") is not False
    ):
        raise FidelityEvaluatorRunnerError("component visibility probe authority is invalid")
    revision = str(report.get("bodyrig_revision") or "")
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise FidelityEvaluatorRunnerError("component visibility probe BodyRig revision is invalid")
    if report.get("platform") not in {"windows-unity-univrm", "android-quest-class"}:
        raise FidelityEvaluatorRunnerError("component visibility probe platform is invalid")
    if not isinstance(report.get("observed_at"), str) or not str(report["observed_at"]).strip():
        raise FidelityEvaluatorRunnerError("component visibility probe observed_at is invalid")
    package_sha = _lower_sha256(report.get("package_sha256"), field="component visibility package_sha256")
    _lower_sha256(report.get("avatar_sha256"), field="component visibility avatar_sha256")
    body_id = report.get("body_id")
    if not isinstance(body_id, str) or not body_id:
        raise FidelityEvaluatorRunnerError("component visibility probe body_id is invalid")
    if render_set.get("body_id") != body_id:
        raise FidelityEvaluatorRunnerError("component visibility probe body_id differs from fidelity render set")
    if _lower_sha256(render_set.get("package_sha256"), field="fidelity render-set package_sha256") != package_sha:
        raise FidelityEvaluatorRunnerError("component visibility probe package differs from fidelity render set")

    for field in ("required_component_count", "present_component_count", "visible_component_count"):
        value = report.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise FidelityEvaluatorRunnerError(f"component visibility {field} is invalid")
    expected_count = len(REQUIRED_VISIBLE_COMPONENTS)
    if report["required_component_count"] != expected_count:
        raise FidelityEvaluatorRunnerError("component visibility required component count is invalid")

    components = report.get("components")
    if not isinstance(components, list) or len(components) != expected_count:
        raise FidelityEvaluatorRunnerError("component visibility probe must contain all required components exactly once")
    expected_component_fields = {
        "label",
        "node_name",
        "present_in_avatar_bytes",
        "instantiated",
        "active_in_hierarchy",
        "visible_skinned_renderer",
        "visible_renderer_count",
    }
    observed: set[str] = set()
    for item in components:
        if not isinstance(item, dict) or set(item) != expected_component_fields:
            raise FidelityEvaluatorRunnerError("component visibility entry fields must match v1 exactly")
        label = item.get("label")
        if not isinstance(label, str) or label not in REQUIRED_VISIBLE_COMPONENTS or label in observed:
            raise FidelityEvaluatorRunnerError("component visibility entry label is invalid or duplicated")
        observed.add(label)
        if item.get("node_name") != REQUIRED_VISIBLE_COMPONENTS[label]:
            raise FidelityEvaluatorRunnerError(f"component visibility node mismatch for {label}")
        for field in (
            "present_in_avatar_bytes",
            "instantiated",
            "active_in_hierarchy",
            "visible_skinned_renderer",
        ):
            if item.get(field) is not True:
                raise FidelityEvaluatorRunnerError(
                    f"full-fidelity scoring refused: required component {label} is not physically present and visible ({field})"
                )
        renderer_count = item.get("visible_renderer_count")
        if isinstance(renderer_count, bool) or not isinstance(renderer_count, int) or renderer_count < 1:
            raise FidelityEvaluatorRunnerError(
                f"full-fidelity scoring refused: required component {label} has no visible skinned renderer"
            )
    if observed != set(REQUIRED_VISIBLE_COMPONENTS):
        raise FidelityEvaluatorRunnerError("component visibility probe component set is incomplete")
    if (
        report.get("present_component_count") != expected_count
        or report.get("visible_component_count") != expected_count
        or report.get("all_required_present_and_visible") is not True
    ):
        raise FidelityEvaluatorRunnerError(
            "full-fidelity scoring refused: physical component composition is incomplete"
        )
    return report


def _validate_plausibility(value: object) -> dict:
    expected = {
        "face_detectability",
        "bilateral_balance",
        "head_shoulder_proportion",
        "head_shoulder_ratio",
        "skin_liveliness",
        "facial_definition",
        "score",
        "semantics",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise FidelityEvaluatorRunnerError("fidelity evaluator plausibility fields must match the extended v1 contract exactly")
    if value.get("semantics") != "broad-render-plausibility-and-definition-not-age-or-identity-classification":
        raise FidelityEvaluatorRunnerError("fidelity evaluator plausibility semantics mismatch")
    for field in (
        "face_detectability",
        "bilateral_balance",
        "head_shoulder_proportion",
        "skin_liveliness",
        "facial_definition",
        "score",
    ):
        _number(value.get(field), field=f"plausibility.{field}", minimum=0.0, maximum=1.0)
    _number(value.get("head_shoulder_ratio"), field="plausibility.head_shoulder_ratio", minimum=0.0)
    return value


def _validate_facial_definition(value: object) -> dict:
    expected = {
        "score",
        "candidate",
        "reference_face_count",
        "photorealism_raw",
        "photorealism_definition_cap",
        "semantics",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise FidelityEvaluatorRunnerError("fidelity evaluator facial_definition fields must match the extended v1 contract exactly")
    if value.get("semantics") != "reference-relative-local-feature-definition-not-biometric-identification":
        raise FidelityEvaluatorRunnerError("fidelity evaluator facial_definition semantics mismatch")
    for field in ("score", "photorealism_raw", "photorealism_definition_cap"):
        _number(value.get(field), field=f"facial_definition.{field}", minimum=0.0, maximum=1.0)
    reference_face_count = value.get("reference_face_count")
    if isinstance(reference_face_count, bool) or not isinstance(reference_face_count, int) or reference_face_count < 0:
        raise FidelityEvaluatorRunnerError("facial_definition.reference_face_count must be a non-negative integer")
    candidate = value.get("candidate")
    expected_candidate = {"detail", "local_contrast", "eye_edge_density", "midface_edge_density"}
    if not isinstance(candidate, dict) or set(candidate) != expected_candidate:
        raise FidelityEvaluatorRunnerError("fidelity evaluator facial_definition candidate fields must match the extended v1 contract exactly")
    for field in expected_candidate:
        _number(candidate.get(field), field=f"facial_definition.candidate.{field}", minimum=0.0)
    return value


def _read_result(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FidelityEvaluatorRunnerError("fidelity evaluator result is invalid JSON") from exc
    if not isinstance(value, dict):
        raise FidelityEvaluatorRunnerError("fidelity evaluator result must be an object")
    legacy_expected = {
        "format",
        "version",
        "measurement",
        "body_reference",
        "shape_hint",
        "diagnostics",
        "human_visual_authority_required",
        "semantics",
    }
    extended_expected = legacy_expected | {"plausibility", "facial_definition"}
    fields = set(value)
    if fields not in (legacy_expected, extended_expected):
        raise FidelityEvaluatorRunnerError("fidelity evaluator result fields must match a supported v1 contract exactly")
    if (
        value.get("format") != "bodyrig-fidelity-evaluation"
        or isinstance(value.get("version"), bool)
        or value.get("version") != 1
    ):
        raise FidelityEvaluatorRunnerError("fidelity evaluator result format/version mismatch")
    if value.get("human_visual_authority_required") is not True:
        raise FidelityEvaluatorRunnerError("fidelity evaluator must retain human visual authority")
    if value.get("semantics") != "visual-fidelity-not-identity-verification":
        raise FidelityEvaluatorRunnerError("fidelity evaluator semantics mismatch")
    try:
        value["measurement"] = validate_measurement(value.get("measurement"))
    except FidelityConvergenceError as exc:
        raise FidelityEvaluatorRunnerError(str(exc)) from exc
    if fields == extended_expected:
        evaluator = value["measurement"].get("evaluator")
        revision = str(evaluator.get("revision") or "") if isinstance(evaluator, dict) else ""
        if revision not in SUPPORTED_EXTENDED_REVISIONS:
            raise FidelityEvaluatorRunnerError("extended fidelity evaluator result requires evaluator revision 4 or 5")
        value["plausibility"] = _validate_plausibility(value.get("plausibility"))
        value["facial_definition"] = _validate_facial_definition(value.get("facial_definition"))
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
    parser.add_argument(
        "--allow-incomplete-component-comparison",
        action="store_true",
        help="Diagnostic-only override for historical renders produced before component visibility evidence existed.",
    )
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
        bridge = Path(__file__).resolve().parent / "bridges" / "opencv_fidelity_evaluator_v5.py"
        if not bridge.is_file():
            raise FidelityEvaluatorRunnerError("built-in fidelity evaluator bridge is missing")
        reference = Path(args.reference_set).expanduser().resolve()
        render = Path(args.render_set).expanduser().resolve()
        if not reference.is_file() or not render.is_file():
            raise FidelityEvaluatorRunnerError("fidelity reference/render manifests must exist")
        if not args.allow_incomplete_component_comparison:
            _validate_component_visibility(render)
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
