from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .acceptance_status import AcceptanceStatus, AcceptanceStatusError, inspect_acceptance_dir


# Higher means farther through the expensive/physical acceptance chain.
# This intentionally describes the evidence revision's own structural state;
# current-checkout renderer policy is applied only after the exact evidence
# revision has been selected/re-entered.
GATE_PROGRESS = {
    "gate-a": 10,
    "windows-probe": 20,
    "windows-attestation": 30,
    "quest-probe": 40,
    "quest-attestation": 50,
    "release": 60,
}


def progress_rank(status: AcceptanceStatus) -> int:
    if status.state == "complete":
        return 100
    if status.state == "blocked":
        return 0
    return GATE_PROGRESS.get(status.gate, 0)


def inspect_for_rig_window(path: str | Path) -> dict[str, Any]:
    acceptance_dir = Path(path).expanduser().resolve()
    status = inspect_acceptance_dir(acceptance_dir)
    payload = asdict(status)
    payload["progress_rank"] = progress_rank(status)
    payload["read_only"] = True
    payload["policy_scope"] = "evidence-revision-structural"
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect one BodyRig acceptance for reuse-first rig-window ranking without rebinding it to current operator policy."
    )
    parser.add_argument("acceptance_dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = inspect_for_rig_window(args.acceptance_dir)
    except AcceptanceStatusError as exc:
        print(
            json.dumps(
                {"state": "error", "error": str(exc), "read_only": True},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 2
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
