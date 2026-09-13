#!/usr/bin/env python
"""Fail-closed request guard for the canonical SiTH gender-aware fitter bridge.

This script runs inside the pinned SiTH/SMPL-X Python environment before the
existing gender wrapper. It validates only the cross-process request authority
needed at point-of-use, then delegates to the unchanged canonical wrapper.
"""
from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path
from typing import Any

REQUEST_FORMAT = "bodyrig-avatar-fit-request"
IDENTITY_FORMAT = "bodyrig-visual-identity"
VERSION = 1


class SithFitterRequestGuardError(ValueError):
    pass


def _is_v1(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == VERSION


def validate_request(path: str | Path) -> dict[str, Any]:
    request_path = Path(path).expanduser().resolve()
    if not request_path.is_file():
        raise SithFitterRequestGuardError("BodyRig fitter request is missing")
    try:
        value = json.loads(
            request_path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SithFitterRequestGuardError("BodyRig fitter request is invalid JSON") from exc
    required = {"format", "version", "name", "bodyprint", "visual_identity"}
    allowed = required | {"bodyprint_adjustment"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - allowed:
        raise SithFitterRequestGuardError("BodyRig fitter request fields do not match v1")
    if value.get("format") != REQUEST_FORMAT or not _is_v1(value.get("version")):
        raise SithFitterRequestGuardError("unsupported BodyRig fitter request format/version")

    identity = value.get("visual_identity")
    if not isinstance(identity, dict):
        raise SithFitterRequestGuardError("BodyRig visual identity is missing")
    if identity.get("format") != IDENTITY_FORMAT or not _is_v1(identity.get("version")):
        raise SithFitterRequestGuardError("unsupported BodyRig visual identity format/version")
    track = identity.get("subject_track_id")
    if not isinstance(track, str) or not track or len(track) > 160:
        raise SithFitterRequestGuardError("BodyRig visual identity track id is invalid")
    if identity.get("privacy") != {
        "contains_source_media": False,
        "contains_biometric_template": False,
    }:
        raise SithFitterRequestGuardError("BodyRig visual identity privacy boundary is invalid")
    return value


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--bodyrig-request", required=True)
    try:
        args, _unknown = parser.parse_known_args(arguments)
        validate_request(args.bodyrig_request)
    except (SystemExit, SithFitterRequestGuardError) as exc:
        detail = str(exc) if not isinstance(exc, SystemExit) else "request path is missing"
        print(f"BodyRig SiTH fitter request guard: FAIL: {detail}", file=sys.stderr)
        return 1

    target = Path(__file__).resolve().with_name("sith_smplx_vrm_fitter_gender.py")
    if not target.is_file():
        print("BodyRig SiTH fitter request guard: FAIL: canonical gender wrapper is missing", file=sys.stderr)
        return 1

    previous_argv = sys.argv
    try:
        sys.argv = [str(target), *arguments]
        try:
            runpy.run_path(str(target), run_name="__main__")
        except SystemExit as exc:
            code = exc.code
            if code is None:
                return 0
            if isinstance(code, int):
                return code
            return 1
    finally:
        sys.argv = previous_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
