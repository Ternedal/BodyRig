from __future__ import annotations

import argparse
import json
import sys

from .digital_twin_operator_status import (
    DigitalTwinOperatorStatusError,
    inspect_operator_status,
)
from .storage import person_library


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only BodyRig full digital-twin operator status and exact next gate."
    )
    parser.add_argument("--composition-authority-dir", required=True)
    parser.add_argument("--acceptance-dir", required=True)
    parser.add_argument("--library-root", default=None)
    parser.add_argument(
        "--operator-root",
        default=None,
        help="BodyRig Git checkout used only to authorize an executable next command.",
    )
    args = parser.parse_args(argv)

    try:
        result = inspect_operator_status(
            composition_authority_dir=args.composition_authority_dir,
            acceptance_dir=args.acceptance_dir,
            library_root=args.library_root or person_library(),
            operator_root=args.operator_root,
        )
    except (DigitalTwinOperatorStatusError, OSError, ValueError) as exc:
        print(f"BodyRig digital-twin operator status: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 3 if result.get("state") in {"blocked", "invalid"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
