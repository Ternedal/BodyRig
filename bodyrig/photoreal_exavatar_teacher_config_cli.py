from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from .photoreal_exavatar_teacher_config import (
    ADAPTER,
    FORMAT,
    MAX_TIMEOUT_SECONDS,
    UPSTREAM_COMMIT,
    UPSTREAM_REPOSITORY,
    VERSION,
    PhotorealExAvatarTeacherConfigError,
    build_exavatar_teacher_config_file,
    validate_exavatar_teacher_config_file,
)


def _is_replaceable_stale_config(path: Path) -> bool:
    if path.is_symlink():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(value, dict):
        return False
    if set(value) != {
        "format",
        "version",
        "adapter",
        "revision",
        "upstream_repository",
        "upstream_commit",
        "command",
        "timeout_seconds",
    }:
        return False
    if (
        value.get("format") != FORMAT
        or type(value.get("version")) is not int
        or value.get("version") != VERSION
        or value.get("adapter") != ADAPTER
        or value.get("upstream_repository") != UPSTREAM_REPOSITORY
        or value.get("upstream_commit") != UPSTREAM_COMMIT
    ):
        return False
    revision = value.get("revision")
    if not isinstance(revision, str) or not revision.startswith("sha256:"):
        return False
    digest = revision[len("sha256:") :]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
        return False
    command = value.get("command")
    expected_flags = (
        "--distribution",
        "--wsl-exe",
        "--linux-python",
        "--workspace-root",
        "--runtime-preflight",
        "--adapter-script",
    )
    if (
        not isinstance(command, list)
        or len(command) not in (14, 16)
        or not all(isinstance(item, str) and item for item in command)
        or tuple(command[index] for index in (2, 4, 6, 8, 10, 12)) != expected_flags
        # The opt-in densification end is the only extra pair a stale config may carry.
        or (len(command) == 16 and command[14] != "--densify-end-fraction")
    ):
        return False
    timeout = value.get("timeout_seconds")
    return isinstance(timeout, int) and not isinstance(timeout, bool) and 1 <= timeout <= MAX_TIMEOUT_SECONDS


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a hash-bound BodyRig ExAvatar teacher config for WSL execution.")
    parser.add_argument("--windows-python", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--linux-workspace-root", required=True)
    parser.add_argument("--linux-runtime-preflight", required=True)
    parser.add_argument("--linux-python", default="/opt/bodyrig-exavatar/bin/python")
    parser.add_argument("--distribution", default="Ubuntu-22.04")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--timeout-seconds", type=int, default=MAX_TIMEOUT_SECONDS)
    # Opt-in (Anders, option B): end scene-Gaussian densification at this fraction of the run.
    parser.add_argument("--densify-end-fraction", default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        kwargs = dict(
            windows_python=args.windows_python,
            bridge_path=args.bridge,
            adapter_path=args.adapter,
            linux_workspace_root=args.linux_workspace_root,
            linux_runtime_preflight=args.linux_runtime_preflight,
            linux_python=args.linux_python,
            distribution=args.distribution,
            wsl_exe=args.wsl_exe,
            timeout_seconds=args.timeout_seconds,
            densify_end_fraction=args.densify_end_fraction,
        )
        output = args.out.expanduser().resolve()
        if args.reuse_existing and output.is_file():
            try:
                result = validate_exavatar_teacher_config_file(
                    config_path=output,
                    **kwargs,
                )
            except PhotorealExAvatarTeacherConfigError:
                if not _is_replaceable_stale_config(output):
                    raise
                replacement = output.with_name(f".{output.name}.rebuild-{uuid4().hex}")
                try:
                    result = build_exavatar_teacher_config_file(
                        output_path=replacement,
                        **kwargs,
                    )
                    replacement.replace(output)
                finally:
                    if replacement.exists():
                        replacement.unlink()
        else:
            result = build_exavatar_teacher_config_file(
                output_path=output,
                **kwargs,
            )
    except PhotorealExAvatarTeacherConfigError as exc:
        print(f"BodyRig Photoreal ExAvatar teacher config: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "adapter": result["adapter"],
                "revision": result["revision"],
                "upstream_commit": result["upstream_commit"],
                "timeout_seconds": result["timeout_seconds"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
