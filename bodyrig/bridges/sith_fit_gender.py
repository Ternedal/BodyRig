#!/usr/bin/env python
"""Run pinned SiTH fit.py with an explicit SMPL-X gender without mutating SiTH.

SiTH's pinned fit.py hard-codes ``gender='male'``. BodyRig verifies that pinned
checkout separately, then this bridge replaces exactly that constructor literal
in-memory and executes the otherwise unchanged fit.py in the SiTH repository.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

GENDERS = ("female", "male", "neutral")
MARKER = "gender='male'"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--sith-repo", required=True)
    parser.add_argument("--bodyrig-smplx-gender", required=True, choices=GENDERS)
    args, remainder = parser.parse_known_args(argv)

    repo = Path(args.sith_repo).expanduser().resolve()
    target = repo / "fit.py"
    if not target.is_file():
        print(f"BodyRig gender-aware SiTH fit: FAIL: fit.py missing: {target}", file=sys.stderr)
        return 1
    try:
        source = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"BodyRig gender-aware SiTH fit: FAIL: could not read fit.py: {exc}", file=sys.stderr)
        return 1

    if source.count(MARKER) != 1:
        print(
            "BodyRig gender-aware SiTH fit: FAIL: expected exactly one pinned male SMPL-X constructor marker",
            file=sys.stderr,
        )
        return 1

    patched = source.replace(MARKER, f"gender={args.bodyrig_smplx_gender!r}", 1)
    sys.path.insert(0, str(repo))
    os.chdir(repo)
    sys.argv = [str(target), *remainder]
    namespace = {
        "__name__": "__main__",
        "__file__": str(target),
        "__package__": None,
        "__cached__": None,
    }
    try:
        exec(compile(patched, str(target), "exec"), namespace, namespace)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(str(code), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
