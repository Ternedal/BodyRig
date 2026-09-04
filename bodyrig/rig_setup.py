from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .bridges.hmr2_config import FOUR_D_HUMANS_REVISION, PHALP_REVISION
from .sith_setup import SithSetupError, load_setup_report

FORMAT = "bodyrig-rig-setup"
VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RigSetupError(ValueError):
    pass


def _nonempty(value: Any, *, field: str, maximum: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RigSetupError(f"{field} must contain 1..{maximum} characters")
    return value.strip()


def _sha(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise RigSetupError(f"{field} must be lowercase SHA-256")
    return value


def validate_rig_setup(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"format", "version", "recovery", "high_fidelity"}:
        raise RigSetupError("rig setup fields must match v1 exactly")
    if value["format"] != FORMAT or value["version"] != VERSION:
        raise RigSetupError("unsupported rig setup format/version")

    recovery = value["recovery"]
    recovery_fields = {
        "environment_summary",
        "environment_summary_sha256",
        "preflight",
        "preflight_sha256",
        "external_python",
        "four_d_humans_repo",
        "phalp_repo",
    }
    if not isinstance(recovery, Mapping) or set(recovery) != recovery_fields:
        raise RigSetupError("rig setup recovery fields must match v1 exactly")

    high = value["high_fidelity"]
    if not isinstance(high, Mapping) or set(high) != {"setup_report", "setup_report_sha256"}:
        raise RigSetupError("rig setup high_fidelity fields must match v1 exactly")

    return {
        "format": FORMAT,
        "version": VERSION,
        "recovery": {
            "environment_summary": _nonempty(recovery["environment_summary"], field="recovery.environment_summary"),
            "environment_summary_sha256": _sha(recovery["environment_summary_sha256"], field="recovery.environment_summary_sha256"),
            "preflight": _nonempty(recovery["preflight"], field="recovery.preflight"),
            "preflight_sha256": _sha(recovery["preflight_sha256"], field="recovery.preflight_sha256"),
            "external_python": _nonempty(recovery["external_python"], field="recovery.external_python"),
            "four_d_humans_repo": _nonempty(recovery["four_d_humans_repo"], field="recovery.four_d_humans_repo"),
            "phalp_repo": _nonempty(recovery["phalp_repo"], field="recovery.phalp_repo"),
        },
        "high_fidelity": {
            "setup_report": _nonempty(high["setup_report"], field="high_fidelity.setup_report"),
            "setup_report_sha256": _sha(high["setup_report_sha256"], field="high_fidelity.setup_report_sha256"),
        },
    }


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise RigSetupError(f"{label} not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RigSetupError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise RigSetupError(f"{label} must be a JSON object")
    return value


def _verify_hash(path: Path, expected: str, *, label: str) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise RigSetupError(f"{label} SHA-256 mismatch")


def load_rig_setup(path: str | Path, *, verify_files: bool = True) -> dict[str, Any]:
    report_path = Path(path).expanduser().resolve()
    value = validate_rig_setup(_read_json(report_path, label="rig setup report"))
    if not verify_files:
        return value

    recovery = value["recovery"]
    summary = Path(recovery["environment_summary"]).expanduser().resolve()
    preflight = Path(recovery["preflight"]).expanduser().resolve()
    sith_report = Path(value["high_fidelity"]["setup_report"]).expanduser().resolve()
    _verify_hash(summary, recovery["environment_summary_sha256"], label="recovery environment summary")
    _verify_hash(preflight, recovery["preflight_sha256"], label="recovery preflight")
    _verify_hash(sith_report, value["high_fidelity"]["setup_report_sha256"], label="SiTH setup report")

    summary_value = _read_json(summary, label="recovery environment summary")
    required_summary = {
        "format",
        "version",
        "root",
        "external_python",
        "four_d_humans_repo",
        "four_d_humans_revision",
        "phalp_repo",
        "phalp_revision",
        "smpl_expected_path",
        "smpl_present",
    }
    if set(summary_value) != required_summary or summary_value.get("format") != "bodyrig-recovery-environment" or summary_value.get("version") != 1:
        raise RigSetupError("recovery environment summary contract mismatch")
    if summary_value.get("smpl_present") is not True:
        raise RigSetupError("recovery environment summary does not prove SMPL presence")
    if summary_value.get("four_d_humans_revision") != FOUR_D_HUMANS_REVISION:
        raise RigSetupError("recovery 4D-Humans revision mismatch")
    if summary_value.get("phalp_revision") != PHALP_REVISION:
        raise RigSetupError("recovery PHALP revision mismatch")
    for field in ("external_python", "four_d_humans_repo", "phalp_repo"):
        if summary_value.get(field) != recovery[field]:
            raise RigSetupError(f"recovery {field} does not match environment summary")

    preflight_value = _read_json(preflight, label="recovery preflight")
    if preflight_value.get("format") != "bodyrig-recovery-preflight" or preflight_value.get("version") != 1:
        raise RigSetupError("recovery preflight contract mismatch")
    if preflight_value.get("ok") is not True:
        raise RigSetupError("recovery preflight is not green")

    try:
        load_setup_report(sith_report)
    except SithSetupError as exc:
        raise RigSetupError(str(exc)) from exc
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate BodyRig's byte-bound full rig setup report.")
    parser.add_argument("report")
    parser.add_argument("--metadata-only", action="store_true", help="Validate report fields without reading referenced files")
    args = parser.parse_args(argv)
    try:
        value = load_rig_setup(args.report, verify_files=not args.metadata_only)
    except RigSetupError as exc:
        print(f"BodyRig rig setup report: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
