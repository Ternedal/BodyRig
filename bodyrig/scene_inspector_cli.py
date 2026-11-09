"""Command line for ``bodyrig.scene_inspector`` (#1393).

Examples (Windows, Blender installed)::

    bodyrig-scene-inspect inspect --root C:\\assets\\staging --asset hero.glb --asset props\\chair.fbx ^
        --out C:\\assets\\scene-out --cache C:\\assets\\scene-cache ^
        --blender "C:\\Program Files\\Blender Foundation\\Blender 4.5\\blender.exe" --conditioning pose,depth,normal

    bodyrig-scene-inspect bench --root C:\\assets\\staging --all --out C:\\assets\\bench ^
        --blender "C:\\Program Files\\Blender Foundation\\Blender 4.5\\blender.exe" --runs 3

Exit codes: 0 every asset FULLY_ANALYZED (or MINIMUM_READY with --minimum-only),
1 at least one asset FAILED (the others were still processed), 2 setup error,
130 cancelled with Ctrl+C (running workers are killed, staging copies removed).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from bodyrig.scene_inspector import (
    CONDITIONING,
    FORMATS,
    GIB,
    InspectOptions,
    SceneCache,
    load_inventory,
    parse_frames,
    SetupError,
    bench,
    detect_runtime,
    inspect_batch,
)


def _assets(root: Path, explicit: list[str], take_all: bool) -> list[str]:
    found = [a.replace("\\", "/") for a in explicit]
    if take_all:
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not (Path(current) / d).is_symlink())
            for name in sorted(files):
                if Path(name).suffix.lower() in FORMATS:
                    found.append((Path(current) / name).relative_to(root).as_posix())
    unique = list(dict.fromkeys(found))
    if not unique:
        raise SetupError("no assets: give --asset or --all")
    return unique


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bodyrig-scene-inspect", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "bench"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--root", type=Path, required=True, help="local staging folder with the source assets")
        cmd.add_argument("--asset", action="append", default=[], help="asset path relative to --root (repeatable)")
        cmd.add_argument("--all", action="store_true", help="every supported asset under --root")
        cmd.add_argument("--inventory", type=Path,
                         help="a #1394 inventory manifest (schema 2) of --root; its assets and statuses drive the run")
        cmd.add_argument("--out", type=Path, required=True)
        runtime = cmd.add_mutually_exclusive_group()
        runtime.add_argument("--blender", type=Path, help="blender executable")
        runtime.add_argument("--bpy-python", type=Path, help="Python interpreter with the pinned bpy module")
        cmd.add_argument("--conditioning", default="", help=f"comma list of {', '.join(CONDITIONING)}")
        cmd.add_argument("--resolution", type=int, default=512)
        cmd.add_argument("--view-yaw", type=float, default=0.0,
                         help="orbit the conditioning camera around the vertical axis (degrees; 0 front, 90 side, 180 back)")
        cmd.add_argument("--frames", default="", help="START:END[:STEP] (inclusive): one set of outputs per frame, "
                         "one fixed camera for the whole sequence")
        cmd.add_argument("--timeout", type=float, default=120.0, help="seconds per asset")
        cmd.add_argument("--memory-gb", type=float, default=8.0)
        cmd.add_argument("--threads", type=int, default=2)
        cmd.add_argument("--isolation", choices=("auto", "bwrap", "none"), default="auto")
        cmd.add_argument("--work-root", type=Path, help="where private staging copies are made (local disk)")
        if name == "inspect":
            cmd.add_argument("--cache", type=Path, required=True)
            cmd.add_argument("--jobs", type=int, default=1, help="parallel Blender workers")
            cmd.add_argument("--minimum-only", action="store_true", help="header metadata only, no Blender")
            cmd.add_argument("--rehash", action="store_true", help="ignore the size/mtime hash memo")
        else:
            cmd.add_argument("--runs", type=int, default=3)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        inventory = load_inventory(args.inventory) if args.inventory else None
        if inventory is not None and not args.asset and not args.all:
            assets = list(inventory)
            if not assets:
                raise SetupError("the inventory lists no assets")
        else:
            assets = _assets(root, args.asset, args.all)
        options = InspectOptions(
            conditioning=tuple(k.strip() for k in args.conditioning.split(",") if k.strip()),
            resolution=args.resolution, frames=parse_frames(args.frames), yaw_deg=args.view_yaw,
            wall_seconds=args.timeout,
            memory_bytes=int(args.memory_gb * GIB) if args.memory_gb > 0 else None, threads=args.threads,
            isolation=args.isolation, minimum_only=getattr(args, "minimum_only", False),
            use_hash_memo=not getattr(args, "rehash", False),
        ).validate()
        if args.command == "bench":
            if args.blender is None and args.bpy_python is None:
                raise SetupError("bench needs --blender or --bpy-python")
            runtime = detect_runtime(blender=args.blender, bpy_python=args.bpy_python)
            report = bench(root, assets, args.out, runtime=runtime, options=options, runs=max(1, args.runs),
                           work_root=args.work_root)
            print(json.dumps({"cold": report["cold"].get("all"), "warm": report["warm"].get("all")}, indent=2))
            return 0
        cache = SceneCache(args.cache)
        runtime = None
        if not options.minimum_only:
            if args.blender is None and args.bpy_python is None:
                raise SetupError("give --blender or --bpy-python, or use --minimum-only")
            runtime = detect_runtime(blender=args.blender, bpy_python=args.bpy_python, cache_root=args.cache)
        summary = inspect_batch(root, assets, args.out, runtime=runtime, cache=cache, options=options,
                                jobs=max(1, args.jobs), work_root=args.work_root, inventory=inventory)
    except (SetupError, OSError) as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("cancelled: running workers were stopped and their staging removed", file=sys.stderr)
        return 130
    for item in summary["assets"]:
        error = f"  {item['error']['code']}: {item['error']['message']}" if item["error"] else ""
        hit = " (cache)" if item["cache_hit"] else ""
        print(f"{item['state']:<15} {item['timings_ms'].get('total', 0):>7} ms{hit}  {item['path']}{error}")
    print(f"summary: {args.out / 'summary.json'}")
    return 1 if summary["states"].get("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
