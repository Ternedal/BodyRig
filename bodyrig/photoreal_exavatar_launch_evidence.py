from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping


LAUNCH_FORMAT = "bodyrig-photoreal-exavatar-teacher-launch-authority"
COMPLETION_FORMAT = "bodyrig-photoreal-exavatar-teacher-completion-evidence"
VERSION = 1
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class PhotorealExAvatarLaunchEvidenceError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path, label: str) -> Path:
    if not path.is_file() or path.is_symlink():
        raise PhotorealExAvatarLaunchEvidenceError(f"{label} is missing/not regular: {path}")
    return path


def _read_json(path: Path, label: str) -> dict[str, Any]:
    _regular_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealExAvatarLaunchEvidenceError(f"{label} is unreadable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealExAvatarLaunchEvidenceError(f"{label} must be a JSON object: {path}")
    return value


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise PhotorealExAvatarLaunchEvidenceError(f"{label} must be a lowercase SHA-256")
    return text


def _run_id(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{32}", text):
        raise PhotorealExAvatarLaunchEvidenceError(f"{label} is invalid")
    return text


def _revision(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", text):
        raise PhotorealExAvatarLaunchEvidenceError(f"{label} is invalid")
    return text


def _validate_launch(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "run_id",
        "bodyrig_revision",
        "readiness_relative_path",
        "readiness_sha256",
        "teacher_config_sha256",
        "teacher_input_sha256",
        "training_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    }
    if set(value) != required:
        raise PhotorealExAvatarLaunchEvidenceError("launch authority fields must match v1 exactly")
    if value.get("format") != LAUNCH_FORMAT or type(value.get("version")) is not int or value.get("version") != VERSION:
        raise PhotorealExAvatarLaunchEvidenceError("launch authority format/version mismatch")
    if value.get("readiness_relative_path") != "readiness.json":
        raise PhotorealExAvatarLaunchEvidenceError("launch authority readiness path is not canonical")
    if value.get("training_authorized") is not True:
        raise PhotorealExAvatarLaunchEvidenceError("launch authority does not authorize training")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise PhotorealExAvatarLaunchEvidenceError("launch authority crossed photoreal/production authority")
    result = dict(value)
    result["run_id"] = _run_id(value.get("run_id"), "launch run_id")
    result["bodyrig_revision"] = _revision(value.get("bodyrig_revision"), "launch BodyRig revision")
    for field in ("readiness_sha256", "teacher_config_sha256", "teacher_input_sha256"):
        result[field] = _sha(value.get(field), f"launch {field}")
    return result


def _validate_completion(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "run_id",
        "bodyrig_revision",
        "launch_authority_sha256",
        "teacher_manifest_sha256",
        "training_complete",
        "human_visual_acceptance_required",
        "photoreal_acceptance_authority",
        "production_activation",
    }
    if set(value) != required:
        raise PhotorealExAvatarLaunchEvidenceError("completion evidence fields must match v1 exactly")
    if value.get("format") != COMPLETION_FORMAT or type(value.get("version")) is not int or value.get("version") != VERSION:
        raise PhotorealExAvatarLaunchEvidenceError("completion evidence format/version mismatch")
    if value.get("training_complete") is not True or value.get("human_visual_acceptance_required") is not True:
        raise PhotorealExAvatarLaunchEvidenceError("completion evidence does not preserve human-review boundary")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise PhotorealExAvatarLaunchEvidenceError("completion evidence crossed photoreal/production authority")
    result = dict(value)
    result["run_id"] = _run_id(value.get("run_id"), "completion run_id")
    result["bodyrig_revision"] = _revision(value.get("bodyrig_revision"), "completion BodyRig revision")
    result["launch_authority_sha256"] = _sha(value.get("launch_authority_sha256"), "completion launch authority SHA-256")
    result["teacher_manifest_sha256"] = _sha(value.get("teacher_manifest_sha256"), "completion teacher manifest SHA-256")
    return result


def validate_teacher_launch_evidence(teacher_work_root: str | Path) -> dict[str, Any]:
    requested_teacher = Path(teacher_work_root).expanduser()
    if requested_teacher.is_symlink():
        raise PhotorealExAvatarLaunchEvidenceError(
            f"teacher work root may not be a symlink: {requested_teacher}"
        )
    teacher = requested_teacher.resolve()
    if not teacher.is_dir():
        raise PhotorealExAvatarLaunchEvidenceError(f"teacher work root is missing/not regular: {teacher}")

    teacher_input = _regular_file(teacher / "teacher-input.json", "teacher input")
    teacher_config = _regular_file(teacher / "exavatar-teacher-config.json", "teacher config")
    teacher_manifest = _regular_file(
        teacher / "exavatar-teacher-output" / "output" / "teacher-manifest.json",
        "teacher manifest",
    )
    expected_input_sha = _sha256_file(teacher_input)
    expected_config_sha = _sha256_file(teacher_config)
    expected_manifest_sha = _sha256_file(teacher_manifest)

    evidence_root = teacher / "exavatar-teacher-launch-evidence"
    if not evidence_root.is_dir() or evidence_root.is_symlink():
        raise PhotorealExAvatarLaunchEvidenceError(
            f"ExAvatar launch evidence root is missing/not regular: {evidence_root}"
        )

    matches: list[dict[str, Any]] = []
    for launch_dir in sorted(evidence_root.iterdir()):
        if not launch_dir.is_dir():
            continue
        if launch_dir.is_symlink():
            raise PhotorealExAvatarLaunchEvidenceError(
                f"ExAvatar launch evidence directory may not be a symlink: {launch_dir}"
            )
        completion_path = launch_dir / "completion.json"
        if not completion_path.exists():
            continue

        launch_path = launch_dir / "launch-authority.json"
        readiness_path = launch_dir / "readiness.json"
        launch = _validate_launch(_read_json(launch_path, "ExAvatar launch authority"))
        completion = _validate_completion(_read_json(completion_path, "ExAvatar completion evidence"))

        if launch["run_id"] != launch_dir.name or completion["run_id"] != launch_dir.name:
            raise PhotorealExAvatarLaunchEvidenceError(
                f"ExAvatar launch evidence run_id/path mismatch: {launch_dir}"
            )
        if completion["bodyrig_revision"] != launch["bodyrig_revision"]:
            raise PhotorealExAvatarLaunchEvidenceError("completion/launch BodyRig revision mismatch")
        if completion["launch_authority_sha256"] != _sha256_file(launch_path):
            raise PhotorealExAvatarLaunchEvidenceError("launch authority bytes changed after completion")
        if launch["readiness_sha256"] != _sha256_file(_regular_file(readiness_path, "bound readiness report")):
            raise PhotorealExAvatarLaunchEvidenceError("bound readiness bytes changed after launch")

        readiness = _read_json(readiness_path, "bound readiness report")
        if readiness.get("exavatar_launch_prerequisites_ready") is not True:
            raise PhotorealExAvatarLaunchEvidenceError("bound readiness does not authorize ExAvatar launch")
        if readiness.get("bodyrig_branch") != "main" or readiness.get("bodyrig_checkout_clean") is not True:
            raise PhotorealExAvatarLaunchEvidenceError("bound readiness is not from clean canonical main")
        if _revision(readiness.get("bodyrig_revision"), "readiness BodyRig revision") != launch["bodyrig_revision"]:
            raise PhotorealExAvatarLaunchEvidenceError("readiness/launch BodyRig revision mismatch")
        if readiness.get("photoreal_acceptance_authority") is not False or readiness.get("production_activation") is not False:
            raise PhotorealExAvatarLaunchEvidenceError("bound readiness crossed photoreal/production authority")

        if (
            launch["teacher_input_sha256"] == expected_input_sha
            and launch["teacher_config_sha256"] == expected_config_sha
            and completion["teacher_manifest_sha256"] == expected_manifest_sha
        ):
            matches.append(
                {
                    "run_id": launch["run_id"],
                    "bodyrig_revision": launch["bodyrig_revision"],
                    "evidence_root": str(launch_dir),
                    "readiness_sha256": launch["readiness_sha256"],
                    "launch_authority_sha256": completion["launch_authority_sha256"],
                    "teacher_input_sha256": expected_input_sha,
                    "teacher_config_sha256": expected_config_sha,
                    "teacher_manifest_sha256": expected_manifest_sha,
                    "training_complete": True,
                    "human_visual_acceptance_required": True,
                    "photoreal_acceptance_authority": False,
                    "production_activation": False,
                }
            )

    if not matches:
        raise PhotorealExAvatarLaunchEvidenceError(
            "no completed ExAvatar launch evidence matches the current teacher input/config/manifest"
        )
    matches.sort(key=lambda item: str(item["run_id"]))
    result = dict(matches[-1])
    result["matching_completion_count"] = len(matches)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strictly validate ExAvatar teacher launch/completion evidence.")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--teacher-work-root", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        result = validate_teacher_launch_evidence(args.teacher_work_root)
    except PhotorealExAvatarLaunchEvidenceError as exc:
        print(f"BodyRig ExAvatar launch evidence: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
