from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .sith_preflight import OPENPOSE_REVISION, SITH_REVISION

FORMAT = "bodyrig-sith-setup"
VERSION = 3
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SithSetupError(ValueError):
    pass


def _nonempty(value: Any, *, field: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise SithSetupError(f"{field} must contain 1..{maximum} characters")
    return value.strip()


def _linux_path(value: Any, *, field: str) -> str:
    value = _nonempty(value, field=field, maximum=2000)
    if not value.startswith("/") or "\n" in value or "\r" in value:
        raise SithSetupError(f"{field} must be an absolute Linux path")
    return value


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SithSetupError(f"{field} must be a positive integer")
    return value


def _sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise SithSetupError(f"{field} must be lowercase SHA-256")
    return value


def validate_setup_report(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    required = {"format", "version", "distribution", "sith", "openpose", "diffusion_model"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise SithSetupError("SiTH setup report fields must match v3 exactly")
    if value["format"] != FORMAT or value["version"] != VERSION:
        raise SithSetupError("unsupported SiTH setup report format/version")

    distribution = _nonempty(value["distribution"], field="distribution", maximum=160)

    sith = value["sith"]
    if not isinstance(sith, Mapping) or set(sith) != {"repository", "revision", "python"}:
        raise SithSetupError("SiTH setup sith fields must match v3 exactly")
    sith_repo = _linux_path(sith["repository"], field="sith.repository")
    sith_python = _linux_path(sith["python"], field="sith.python")
    if sith["revision"] != SITH_REVISION:
        raise SithSetupError("SiTH setup revision does not match BodyRig pinned revision")

    openpose = value["openpose"]
    openpose_fields = {
        "repository",
        "revision",
        "executable",
        "sha256",
        "byte_count",
        "models_sha256",
        "models_file_count",
        "models_byte_count",
    }
    if not isinstance(openpose, Mapping) or set(openpose) != openpose_fields:
        raise SithSetupError("SiTH setup openpose fields must match v3 exactly")
    openpose_repo = _linux_path(openpose["repository"], field="openpose.repository")
    openpose_exe = _linux_path(openpose["executable"], field="openpose.executable")
    if openpose["revision"] != OPENPOSE_REVISION:
        raise SithSetupError("OpenPose setup revision does not match BodyRig pinned revision")
    openpose_sha256 = _sha256(openpose["sha256"], field="openpose.sha256")
    openpose_byte_count = _positive_int(openpose["byte_count"], field="openpose.byte_count")
    openpose_models_sha256 = _sha256(openpose["models_sha256"], field="openpose.models_sha256")
    openpose_models_file_count = _positive_int(openpose["models_file_count"], field="openpose.models_file_count")
    openpose_models_byte_count = _positive_int(openpose["models_byte_count"], field="openpose.models_byte_count")

    diffusion = value["diffusion_model"]
    if not isinstance(diffusion, Mapping) or set(diffusion) != {"path", "sha256", "file_count", "byte_count"}:
        raise SithSetupError("SiTH setup diffusion_model fields must match v3 exactly")
    diffusion_path = _linux_path(diffusion["path"], field="diffusion_model.path")
    diffusion_sha256 = _sha256(diffusion["sha256"], field="diffusion_model.sha256")
    file_count = _positive_int(diffusion["file_count"], field="diffusion_model.file_count")
    byte_count = _positive_int(diffusion["byte_count"], field="diffusion_model.byte_count")

    return {
        "format": FORMAT,
        "version": VERSION,
        "distribution": distribution,
        "sith": {"repository": sith_repo, "revision": SITH_REVISION, "python": sith_python},
        "openpose": {
            "repository": openpose_repo,
            "revision": OPENPOSE_REVISION,
            "executable": openpose_exe,
            "sha256": openpose_sha256,
            "byte_count": openpose_byte_count,
            "models_sha256": openpose_models_sha256,
            "models_file_count": openpose_models_file_count,
            "models_byte_count": openpose_models_byte_count,
        },
        "diffusion_model": {
            "path": diffusion_path,
            "sha256": diffusion_sha256,
            "file_count": file_count,
            "byte_count": byte_count,
        },
    }


def load_setup_report(path: str | Path) -> dict[str, Any]:
    report = Path(path).expanduser().resolve()
    if not report.is_file():
        raise SithSetupError(f"SiTH setup report not found: {report}")
    try:
        value = json.loads(report.read_text(encoding="utf-8"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SithSetupError("SiTH setup report is invalid JSON") from exc
    return validate_setup_report(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a BodyRig pinned SiTH/WSL setup report.")
    parser.add_argument("report")
    args = parser.parse_args(argv)
    try:
        result = load_setup_report(args.report)
    except SithSetupError as exc:
        print(f"BodyRig SiTH setup report: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
