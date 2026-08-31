from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .fidelity_checkpoint import (
    FidelityCheckpointError,
    _read_json,
    validate_checkpoint,
    verify_checkpoint_artifacts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a candidate fidelity checkpoint and all bound artifacts before append-only publication."
    )
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--work-root", required=True)
    args = parser.parse_args(argv)
    try:
        path = Path(args.checkpoint).expanduser().resolve()
        checkpoint = validate_checkpoint(_read_json(path, label="fidelity convergence checkpoint"))
        verify_checkpoint_artifacts(checkpoint, work_root=args.work_root)
    except (FidelityCheckpointError, OSError, ValueError) as exc:
        print(f"BodyRig fidelity checkpoint verify: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"ok": True, "sequence": checkpoint["sequence"], "stage": checkpoint["stage"]},
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
