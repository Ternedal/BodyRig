from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .fidelity_ab import FidelityAbError, compare_packages


def _write_create_only(path: Path, value: dict) -> None:
    if path.exists():
        raise FidelityAbError(f"A/B evidence output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two validated .mrbody packages and prove a clean appearance-only fidelity A/B boundary."
    )
    parser.add_argument("left")
    parser.add_argument("right")
    parser.add_argument("--out")
    parser.add_argument(
        "--require-clean-appearance-ab",
        action="store_true",
        help="fail unless body id, BodyPrint, geometry, skin binding and rig are identical while appearance differs",
    )
    args = parser.parse_args(argv)
    try:
        evidence = compare_packages(args.left, args.right)
        if args.out:
            _write_create_only(Path(args.out).expanduser().resolve(), evidence)
        if args.require_clean_appearance_ab and not evidence["invariants"]["clean_appearance_ab"]:
            failed = [
                key
                for key in (
                    "body_id_identical",
                    "bodyprint_identical",
                    "geometry_identical",
                    "skin_binding_identical",
                    "rig_identical",
                    "appearance_changed",
                )
                if not evidence["invariants"][key]
            ]
            raise FidelityAbError("clean appearance A/B invariant failed: " + ", ".join(failed))
    except (FidelityAbError, OSError, ValueError) as exc:
        print(f"BodyRig fidelity A/B evidence: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
