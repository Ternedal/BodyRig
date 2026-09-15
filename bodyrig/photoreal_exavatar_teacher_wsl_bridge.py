from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter

REVISION_PREFIX = "sha256:"
REVISION_DOMAIN = b"bodyrig-photoreal-exavatar-teacher-transport-v1\0"


class PhotorealExAvatarTeacherWslError(ValueError):
    pass


def _text(value: str, *, label: str, maximum: int = 32768) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealExAvatarTeacherWslError(f"{label} is invalid")
    return result


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_teacher_transport_revision(*, bridge_path: str | Path, adapter_path: str | Path) -> str:
    bridge = Path(bridge_path).expanduser().resolve()
    adapter = Path(adapter_path).expanduser().resolve()
    if not bridge.is_file():
        raise PhotorealExAvatarTeacherWslError(f"teacher WSL bridge not found: {bridge}")
    if not adapter.is_file():
        raise PhotorealExAvatarTeacherWslError(f"ExAvatar teacher adapter not found: {adapter}")
    digest = hashlib.sha256()
    digest.update(REVISION_DOMAIN)
    digest.update(bytes.fromhex(_file_sha(bridge)))
    digest.update(bytes.fromhex(_file_sha(adapter)))
    return REVISION_PREFIX + digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the pinned BodyRig ExAvatar teacher adapter through WSL.")
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--linux-python", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--runtime-preflight", required=True)
    parser.add_argument("--adapter-script", type=Path, required=True)
    parser.add_argument("--bodyrig-request", type=Path, required=True)
    parser.add_argument("--bodyrig-output", type=Path, required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--bodyrig-upstream-commit", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        distribution = _text(args.distribution, label="WSL distribution", maximum=160)
        linux_python = _text(args.linux_python, label="Linux Python")
        workspace_root = _text(args.workspace_root, label="Linux workspace root")
        runtime_preflight = _text(args.runtime_preflight, label="Linux runtime preflight")
        if not linux_python.startswith("/") or not workspace_root.startswith("/") or not runtime_preflight.startswith("/"):
            raise PhotorealExAvatarTeacherWslError("Linux Python/workspace/runtime-preflight paths must be absolute")

        request = args.bodyrig_request.expanduser().resolve()
        output = args.bodyrig_output.expanduser().resolve()
        adapter = args.adapter_script.expanduser().resolve()
        bridge = Path(__file__).resolve()
        if not request.is_file():
            raise PhotorealExAvatarTeacherWslError(f"BodyRig teacher request not found: {request}")
        if not output.is_dir():
            raise PhotorealExAvatarTeacherWslError(f"BodyRig teacher output directory not found: {output}")
        if not adapter.is_file():
            raise PhotorealExAvatarTeacherWslError(f"ExAvatar teacher adapter not found: {adapter}")

        revision = _text(args.bodyrig_revision, label="BodyRig revision", maximum=160)
        expected_revision = build_teacher_transport_revision(bridge_path=bridge, adapter_path=adapter)
        if revision != expected_revision:
            raise PhotorealExAvatarTeacherWslError(
                "teacher transport revision does not match exact bridge + adapter bytes"
            )

        converter = make_wsl_path_converter(args.wsl_exe, distribution)
        linux_request = converter(str(request))
        linux_output = converter(str(output))
        linux_adapter = converter(str(adapter))
        invocation = [
            args.wsl_exe,
            "-d",
            distribution,
            "--",
            "/usr/bin/env",
            "PYTHONNOUSERSITE=1",
            linux_python,
            linux_adapter,
            "--workspace-root",
            workspace_root,
            "--runtime-preflight",
            runtime_preflight,
            "--bodyrig-request",
            linux_request,
            "--bodyrig-output",
            linux_output,
            "--bodyrig-adapter",
            _text(args.bodyrig_adapter, label="BodyRig adapter", maximum=80),
            "--bodyrig-revision",
            revision,
            "--bodyrig-upstream-commit",
            _text(args.bodyrig_upstream_commit, label="BodyRig upstream commit", maximum=40),
        ]
        completed = subprocess.run(
            invocation,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )
        if completed.stdout:
            sys.stdout.write(completed.stdout)
            sys.stdout.flush()
        return int(completed.returncode)
    except (OSError, WslBridgeError, PhotorealExAvatarTeacherWslError) as exc:
        print(f"BodyRig ExAvatar teacher WSL bridge: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
