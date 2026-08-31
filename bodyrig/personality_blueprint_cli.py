from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from .package import MRBodyError, validate_package
from .personality_blueprint import (
    PersonalityBlueprintError,
    build_blueprint,
    compile_blueprint,
)

RESULT_FORMAT = "bodyrig-personality-blueprint-result"
RESULT_VERSION = 1


def _write_create_only(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path)
        except FileExistsError as exc:
            raise PersonalityBlueprintError(
                f"blueprint output already exists: {path}"
            ) from exc
        except OSError as exc:
            raise PersonalityBlueprintError(
                "could not commit personality blueprint output create-only"
            ) from exc
    finally:
        temp.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a grounded BodyRig personality blueprint and compile it to the "
            "existing ModelRig-ready personality candidate fields."
        )
    )
    parser.add_argument("--default-language", default="da")
    parser.add_argument("--directness", type=float, default=0.5)
    parser.add_argument("--warmth", type=float, default=0.5)
    parser.add_argument("--playfulness", type=float, default=0.5)
    parser.add_argument("--formality", type=float, default=0.5)
    parser.add_argument("--verbosity", type=float, default=0.5)
    parser.add_argument("--initiative", type=float, default=0.5)
    parser.add_argument("--authored-notes", default="")
    parser.add_argument(
        "--body-package",
        default="",
        help="Optional validated .mrbody used only to seed observable embodiment/mannerism fields.",
    )
    parser.add_argument(
        "--body-revision",
        default="",
        help="Required body-rXXXX binding when --body-package is supplied.",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Optional create-only JSON result path. JSON is always also printed to stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bodyprint = None
    body_revision = None

    try:
        if bool(args.body_package) != bool(args.body_revision):
            raise PersonalityBlueprintError(
                "--body-package and --body-revision must be supplied together"
            )
        if args.body_package:
            package = Path(args.body_package).expanduser().resolve()
            if not package.is_file():
                raise PersonalityBlueprintError(f"body package not found: {package}")
            try:
                bodyprint = validate_package(package).bodyprint
            except (MRBodyError, OSError) as exc:
                raise PersonalityBlueprintError(f"body package is invalid: {exc}") from exc
            body_revision = args.body_revision

        communication = {
            "directness": args.directness,
            "warmth": args.warmth,
            "playfulness": args.playfulness,
            "formality": args.formality,
            "verbosity": args.verbosity,
            "initiative": args.initiative,
        }
        blueprint = build_blueprint(
            default_language=args.default_language,
            communication=communication,
            authored_notes=args.authored_notes,
            bodyprint=bodyprint,
            body_revision=body_revision,
        )
        candidate = compile_blueprint(blueprint)
        result = {
            "format": RESULT_FORMAT,
            "version": RESULT_VERSION,
            "blueprint": blueprint,
            "candidate": candidate,
        }
        if args.out:
            _write_create_only(Path(args.out).expanduser().resolve(), result)
    except PersonalityBlueprintError as exc:
        print(f"BodyRig personality blueprint: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
