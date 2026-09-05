from __future__ import annotations

import argparse
import json
import sys

from .wardrobe_package_lineage import WardrobePackageLineageError, inspect_wardrobe_package_lineage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect exact SiTH source-outer-surface lineage carried by a wardrobe review .mrbody package."
    )
    parser.add_argument("package")
    args = parser.parse_args(argv)
    try:
        value = inspect_wardrobe_package_lineage(args.package)
    except (OSError, WardrobePackageLineageError) as exc:
        print(f"BodyRig wardrobe package lineage: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
