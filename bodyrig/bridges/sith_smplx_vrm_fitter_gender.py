#!/usr/bin/env python
"""Gender-aware entrypoint for BodyRig's pinned SiTH -> SMPL-X VRM bridge.

The production bridge used to hard-code SMPL-X ``male`` in the final rigging
stage.  This wrapper keeps the reviewed bridge implementation byte-for-byte as
the authority, but replaces that single pinned constructor argument in-memory
for the current process.  The source checkout is never modified.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

GENDERS = ("female", "male", "neutral")
MARKER = 'gender="male",'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--bodyrig-smplx-gender", required=True, choices=GENDERS)
    args, remainder = parser.parse_known_args(argv)

    target = Path(__file__).resolve().with_name("sith_smplx_vrm_fitter_adjusted.py")
    if not target.is_file():
        print("BodyRig gender-aware fitter: FAIL: adjusted fitter source is missing", file=sys.stderr)
        return 1
    try:
        source = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"BodyRig gender-aware fitter: FAIL: could not read adjusted fitter: {exc}", file=sys.stderr)
        return 1

    if source.count(MARKER) != 1:
        print(
            "BodyRig gender-aware fitter: FAIL: expected exactly one pinned male SMPL-X constructor marker",
            file=sys.stderr,
        )
        return 1

    patched = source.replace(MARKER, f'gender={args.bodyrig_smplx_gender!r},', 1)
    patched = patched.replace(
        'failed to load the licensed SMPL-X male model',
        f'failed to load the licensed SMPL-X {args.bodyrig_smplx_gender} model',
        1,
    )

    sys.path.insert(0, str(target.parent))
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
