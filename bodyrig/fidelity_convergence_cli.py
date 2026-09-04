from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from .fidelity_convergence import FidelityConvergenceError, FidelityPolicy, decide_convergence


def _read_measurement(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FidelityConvergenceError(f"fidelity history item is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FidelityConvergenceError("fidelity history item must be an object")
    if value.get("format") == "bodyrig-fidelity-evaluation":
        measurement = value.get("measurement")
        if not isinstance(measurement, dict):
            raise FidelityConvergenceError("fidelity evaluation does not contain a measurement")
        return measurement
    return value


def _write_create_only(path: Path, value: dict) -> None:
    if path.exists():
        raise FidelityConvergenceError(f"convergence decision output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path)
        except FileExistsError as exc:
            raise FidelityConvergenceError(f"convergence decision output already exists: {path}") from exc
    finally:
        temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decide whether BodyRig visual fidelity should iterate, converge or escalate.")
    parser.add_argument("evaluations", nargs="+")
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--plateau-window", type=int, default=3)
    parser.add_argument("--min-improvement", type=float, default=0.01)
    args = parser.parse_args(argv)

    try:
        paths = [Path(item).expanduser().resolve() for item in args.evaluations]
        measurements = [_read_measurement(path) for path in paths]
        policy = FidelityPolicy(
            max_iterations=args.max_iterations,
            plateau_window=args.plateau_window,
            min_improvement=args.min_improvement,
        )
        result = decide_convergence(measurements, policy=policy)
        _write_create_only(Path(args.out).expanduser().resolve(), result)
    except (FidelityConvergenceError, OSError, ValueError) as exc:
        print(f"BodyRig fidelity convergence: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
