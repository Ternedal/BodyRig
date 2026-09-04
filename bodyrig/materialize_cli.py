from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .materialize import RUNTIME_MANIFEST, materialize_runtime
from .package import MRBodyError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize validated renderer assets from one .mrbody package."
    )
    parser.add_argument("package", help="Validated .mrbody package")
    parser.add_argument("--out", required=True, help="New runtime asset directory (must not already exist)")
    args = parser.parse_args(argv)

    package = Path(args.package).expanduser().resolve()
    destination = Path(args.out).expanduser().resolve()
    try:
        result = materialize_runtime(package, destination)
    except (MRBodyError, OSError) as exc:
        print(f"BodyRig materialize: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": "bodyrig-materialize-result",
                "version": 1,
                "root": str(result.root),
                "avatar": str(result.avatar),
                "runtime_manifest": str(result.root / RUNTIME_MANIFEST),
                "body_id": result.manifest["body_id"],
                "package_sha256": result.manifest["package_sha256"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
