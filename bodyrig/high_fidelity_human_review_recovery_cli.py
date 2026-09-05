from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .high_fidelity_human_review import HighFidelityHumanReviewError, archive_invalid_review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Archive one invalid create-only high-fidelity human-review receipt without deleting its bytes, "
            "so the exact package can receive a new explicit review."
        )
    )
    parser.add_argument("--package", required=True, type=Path, help="Exact promoted .mrbody package path.")
    args = parser.parse_args(argv)

    try:
        result = archive_invalid_review(args.package)
    except (HighFidelityHumanReviewError, OSError) as exc:
        print(f"BodyRig high-fidelity human review recovery: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
