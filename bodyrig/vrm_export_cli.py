"""Command line for ``bodyrig.vrm_export`` (#1393).

Examples (Windows)::

    bodyrig-vrm-export export C:\\packs\\model.zip C:\\packs\\other.fbx --out C:\\BodyRig\\vrm-out ^
        --addons C:\\BodyRig\\vrm-addons --cache C:\\BodyRig\\vrm-cache ^
        --bpy-python C:\\BodyRig\\bpy-venv\\Scripts\\python.exe

    bodyrig-vrm-export watch --inbox C:\\BodyRig\\vrm-inbox --out C:\\BodyRig\\vrm-out ^
        --addons C:\\BodyRig\\vrm-addons --cache C:\\BodyRig\\vrm-cache ^
        --bpy-python C:\\BodyRig\\bpy-venv\\Scripts\\python.exe

Exit codes: 0 every asset READY, 1 at least one asset FAILED (the others were
still converted), 2 setup error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bodyrig.scene_inspector import GIB, SetupError, detect_runtime
from bodyrig.vrm_export import ExportOptions, batch_summary, dumps, export_asset, watch


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bodyrig-vrm-export", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("export", "watch"):
        cmd = sub.add_parser(name)
        if name == "export":
            cmd.add_argument("assets", nargs="+", type=Path, help="model files, folders or .zip packs")
        else:
            cmd.add_argument("--inbox", type=Path, required=True)
            cmd.add_argument("--poll", type=float, default=0.5, help="seconds between inbox scans")
        cmd.add_argument("--out", type=Path, required=True)
        cmd.add_argument("--addons", type=Path, required=True, help="folder from scripts/vrm_export_setup.py")
        cmd.add_argument("--cache", type=Path, help="content-addressed cache; repeats only copy the .vrm")
        runtime = cmd.add_mutually_exclusive_group(required=True)
        runtime.add_argument("--blender", type=Path, help="blender executable")
        runtime.add_argument("--bpy-python", type=Path, help="Python interpreter with the pinned bpy module")
        cmd.add_argument("--timeout", type=float, default=300.0, help="seconds per asset")
        cmd.add_argument("--memory-gb", type=float, default=8.0)
        cmd.add_argument("--threads", type=int, default=4)
        cmd.add_argument("--max-texture", type=int, default=2048, help="0 keeps the original size")
        cmd.add_argument("--isolation", choices=("auto", "bwrap", "none"), default="auto")
        cmd.add_argument("--work-root", type=Path, help="where private staging copies are made (local disk)")
        cmd.add_argument("--weight-reference", type=Path,
                         help="model with a good rig; its hip/groin weights are transferred (#1401)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not (args.addons / "io_scene_vrm" / "__init__.py").is_file():
            raise SetupError(f"no VRM add-on in {args.addons}; run scripts/vrm_export_setup.py first")
        runtime = detect_runtime(blender=args.blender, bpy_python=args.bpy_python,
                                 cache_root=args.cache)
        options = ExportOptions(wall_seconds=args.timeout,
                                memory_bytes=int(args.memory_gb * GIB) if args.memory_gb > 0 else None,
                                threads=args.threads, isolation=args.isolation,
                                max_texture=args.max_texture).validate()
        common = dict(runtime=runtime, addons_dir=args.addons, options=options, cache_root=args.cache,
                      work_root=args.work_root, weight_reference=args.weight_reference)
        if args.command == "export":
            results = [export_asset(asset, args.out, **common) for asset in args.assets]
            summary = batch_summary(results)
            print(dumps({"summary": summary, "results": [
                {k: r.get(k) for k in ("source", "state", "output", "timings_ms", "cache", "error")}
                for r in results]}))
            return 0 if not summary["failed"] else 1
        try:
            watch(args.inbox, args.out, poll_seconds=args.poll, log=lambda s: print(s, flush=True), **common)
        except KeyboardInterrupt:
            return 0
        return 0
    except SetupError as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
