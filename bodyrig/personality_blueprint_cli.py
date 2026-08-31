from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from .package import MRBodyError, validate_package
from .person_profiles import (
    PersonProfileError,
    add_personality_revision,
    load_profile,
)
from .personality_audition_suite import build_audition_suite
from .personality_blueprint import (
    PersonalityBlueprintError,
    build_blueprint,
    compile_blueprint,
)
from .storage import person_library as default_person_library

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


def _find_body_revision(profile: dict[str, Any], revision_id: str) -> dict[str, Any]:
    for item in profile.get("body_revisions", []):
        if item.get("revision_id") == revision_id:
            return dict(item)
    raise PersonalityBlueprintError(
        f"body revision {revision_id!r} is not registered on the selected person"
    )


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
        "--style-example",
        action="append",
        default=[],
        help=(
            "Operator-approved example utterance used only for phrasing/rhythm style. "
            "May be repeated up to 12 times; factual content is not treated as memory."
        ),
    )
    parser.add_argument(
        "--body-package",
        default="",
        help="Optional validated .mrbody used only to seed observable embodiment/mannerism fields.",
    )
    parser.add_argument(
        "--body-revision",
        default="",
        help=(
            "Body-rXXXX grounding. With --person-id the registered package is resolved "
            "automatically; otherwise --body-package is required."
        ),
    )
    parser.add_argument(
        "--person-library",
        default="",
        help="Optional Person Profile registry override. Defaults to BodyRig's canonical data directory.",
    )
    parser.add_argument("--person-id", default="")
    parser.add_argument(
        "--save-candidate",
        action="store_true",
        help="Append the compiled personality as a new immutable personality-rXXXX candidate.",
    )
    parser.add_argument("--feedback", default="")
    parser.add_argument(
        "--out",
        default="",
        help="Optional create-only JSON result path. Required with --save-candidate.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bodyprint = None
    body_revision = args.body_revision or None
    profile = None
    saved_revision_id = None

    try:
        if args.person_library and not args.person_id:
            raise PersonalityBlueprintError(
                "--person-library is an override and requires --person-id"
            )
        person_root = (
            Path(args.person_library).expanduser().resolve()
            if args.person_library
            else default_person_library()
        )
        if args.save_candidate and not args.person_id:
            raise PersonalityBlueprintError("--save-candidate requires --person-id")
        if args.save_candidate and not args.out:
            raise PersonalityBlueprintError(
                "--save-candidate requires --out so the authored blueprint is preserved create-only"
            )
        output = Path(args.out).expanduser().resolve() if args.out else None
        if output is not None and output.exists():
            raise PersonalityBlueprintError(f"blueprint output already exists: {output}")

        if args.person_id:
            try:
                profile = load_profile(person_root, args.person_id)
            except PersonProfileError as exc:
                raise PersonalityBlueprintError(str(exc)) from exc

        package_path = args.body_package
        if body_revision and profile is not None:
            registered = _find_body_revision(profile, body_revision)
            registered_package = str(registered["package_path"])
            if package_path:
                explicit = Path(package_path).expanduser().resolve()
                expected = Path(registered_package).expanduser().resolve()
                if explicit != expected:
                    raise PersonalityBlueprintError(
                        "--body-package does not match the package registered for --body-revision"
                    )
            package_path = registered_package
        elif bool(package_path) != bool(body_revision):
            raise PersonalityBlueprintError(
                "standalone body grounding requires --body-package and --body-revision together"
            )

        if package_path:
            package = Path(package_path).expanduser().resolve()
            if not package.is_file():
                raise PersonalityBlueprintError(f"body package not found: {package}")
            try:
                validated_body = validate_package(package)
            except (MRBodyError, OSError) as exc:
                raise PersonalityBlueprintError(f"body package is invalid: {exc}") from exc
            if profile is not None and body_revision:
                registered = _find_body_revision(profile, body_revision)
                if validated_body.manifest["id"] != registered["body_id"]:
                    raise PersonalityBlueprintError(
                        "registered body revision id does not match the validated .mrbody identity"
                    )
            bodyprint = validated_body.bodyprint

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
            style_exemplars=args.style_example,
            bodyprint=bodyprint,
            body_revision=body_revision,
        )
        candidate = compile_blueprint(blueprint)
        audition_suite = build_audition_suite(candidate["default_language"])

        if args.save_candidate:
            try:
                updated = add_personality_revision(
                    person_root,
                    args.person_id,
                    instructions=candidate["instructions"],
                    default_language=candidate["default_language"],
                    style_notes=candidate["style_notes"],
                    feedback=args.feedback,
                )
            except PersonProfileError as exc:
                raise PersonalityBlueprintError(str(exc)) from exc
            saved_revision_id = updated["personality_revisions"][-1]["revision_id"]

        result = {
            "format": RESULT_FORMAT,
            "version": RESULT_VERSION,
            "blueprint": blueprint,
            "candidate": candidate,
            "audition_suite": audition_suite,
            "person_id": args.person_id or None,
            "saved_personality_revision": saved_revision_id,
        }
        if output is not None:
            _write_create_only(output, result)
    except PersonalityBlueprintError as exc:
        print(f"BodyRig personality blueprint: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
