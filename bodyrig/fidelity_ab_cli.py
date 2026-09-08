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


def _expected_revision_pair(args: argparse.Namespace) -> tuple[str, str] | None:
    left = args.expected_left_builder_revision
    right = args.expected_right_builder_revision
    supplied = left is not None or right is not None
    if args.require_clean_appearance_ab or supplied:
        if not isinstance(left, str) or not left.strip() or not isinstance(right, str) or not right.strip():
            raise FidelityAbError(
                "revision-bound A/B requires both --expected-left-builder-revision and --expected-right-builder-revision"
            )
        return left.strip(), right.strip()
    return None


def _bind_expected_revisions(evidence: dict, expected: tuple[str, str] | None) -> None:
    if expected is None:
        return
    expected_left, expected_right = expected
    actual_left = evidence["left"].get("builder_revision")
    actual_right = evidence["right"].get("builder_revision")
    mismatches: list[str] = []
    if actual_left != expected_left:
        mismatches.append(f"left builder revision {actual_left!r} != expected {expected_left!r}")
    if actual_right != expected_right:
        mismatches.append(f"right builder revision {actual_right!r} != expected {expected_right!r}")
    if mismatches:
        raise FidelityAbError("revision-bound A/B failed: " + "; ".join(mismatches))
    evidence["revision_binding"] = {
        "expected_left_builder_revision": expected_left,
        "expected_right_builder_revision": expected_right,
        "passed": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two validated .mrbody packages and prove a clean appearance-only fidelity A/B boundary."
    )
    parser.add_argument("left")
    parser.add_argument("right")
    parser.add_argument("--out")
    parser.add_argument("--expected-left-builder-revision")
    parser.add_argument("--expected-right-builder-revision")
    parser.add_argument(
        "--require-clean-appearance-ab",
        action="store_true",
        help=(
            "fail unless body id, BodyPrint, geometry, skin binding and rig are identical while appearance differs; "
            "also requires explicit expected builder revisions for both packages"
        ),
    )
    args = parser.parse_args(argv)
    try:
        expected_revisions = _expected_revision_pair(args)
        evidence = compare_packages(args.left, args.right)
        _bind_expected_revisions(evidence, expected_revisions)
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
        if args.out:
            _write_create_only(Path(args.out).expanduser().resolve(), evidence)
    except (FidelityAbError, OSError, ValueError) as exc:
        print(f"BodyRig fidelity A/B evidence: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
