from __future__ import annotations

import argparse
import json
import sys

from .skin_qa import SkinQaError, write_report
from .skin_qa_gate import analyze_package


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Gate A skin QA with current appearance-authority validation.")
    parser.add_argument("package", help="Validated high-fidelity .mrbody package")
    parser.add_argument("--out", required=True, help="Create-only bodyrig-skin-qa v1 JSON report")
    args = parser.parse_args(argv)
    try:
        report = analyze_package(args.package)
        output = write_report(args.out, report)
    except (SkinQaError, OSError, ValueError) as exc:
        print(f"BodyRig Gate A skin QA: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"report": str(output), "assessment": report["automated_assessment"]}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
