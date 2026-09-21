from __future__ import annotations

import argparse
import json
import sys

from .photoreal_digital_twin_operator_status import (
    PhotorealDigitalTwinOperatorStatusError,
    inspect_photoreal_operator_status,
)
from .storage import person_library


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only BodyRig Photoreal digital-twin status and exact next "
            "authority gate."
        )
    )
    parser.add_argument("--composition-authority-dir", required=True)
    parser.add_argument("--acceptance-dir", required=True)
    parser.add_argument("--photoreal-person-binding", required=True)
    parser.add_argument("--p3-physical-review", required=True)
    parser.add_argument("--library-root", default=None)
    parser.add_argument(
        "--operator-root",
        default=None,
        help="BodyRig Git checkout used only to authorize an executable next command.",
    )
    args = parser.parse_args(argv)

    try:
        result = inspect_photoreal_operator_status(
            composition_authority_dir=args.composition_authority_dir,
            acceptance_dir=args.acceptance_dir,
            library_root=args.library_root or person_library(),
            photoreal_person_binding=args.photoreal_person_binding,
            p3_physical_review=args.p3_physical_review,
            operator_root=args.operator_root,
        )
    except (PhotorealDigitalTwinOperatorStatusError, OSError, ValueError) as exc:
        print(f"BodyRig Photoreal digital-twin operator status: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 3 if result.get("state") in {"blocked", "invalid"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
