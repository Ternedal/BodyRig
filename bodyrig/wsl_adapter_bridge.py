from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import PurePath
from typing import Callable, Sequence

PATH_FLAGS = {
    "--bodyrig-request",
    "--bodyrig-workspace",
    "--bodyrig-output",
    "--bodyrig-source",
}
FORBIDDEN_SHELLS = {
    "sh",
    "bash",
    "dash",
    "zsh",
    "fish",
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
}


class WslBridgeError(ValueError):
    pass


def translate_bodyrig_paths(
    arguments: Sequence[str],
    converter: Callable[[str], str],
) -> list[str]:
    """Translate only BodyRig-owned path arguments.

    Adapter/revision flags and Linux engine arguments remain untouched. This is
    shared by identity-capture and high-fidelity fitter transports.
    """

    result: list[str] = []
    index = 0
    while index < len(arguments):
        item = arguments[index]
        result.append(item)
        if item in PATH_FLAGS:
            if index + 1 >= len(arguments):
                raise WslBridgeError(f"missing value after {item}")
            value = arguments[index + 1]
            converted = converter(value)
            if not isinstance(converted, str) or not converted or "\n" in converted or "\r" in converted:
                raise WslBridgeError(f"invalid WSL path returned for {item}")
            result.append(converted)
            index += 2
            continue
        index += 1
    return result


def _command_name(value: str) -> str:
    normalized = value.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1].lower()


def validate_linux_command(command: Sequence[str]) -> list[str]:
    argv = list(command)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv or any(not isinstance(item, str) or not item for item in argv):
        raise WslBridgeError("WSL adapter command must contain non-empty argv entries")
    if _command_name(argv[0]) in FORBIDDEN_SHELLS:
        raise WslBridgeError(
            "WSL adapter command may not invoke a command shell; call the engine executable/script directly"
        )
    return argv


def build_wsl_invocation(
    *,
    wsl_exe: str,
    distribution: str,
    linux_command: Sequence[str],
    converter: Callable[[str], str],
) -> list[str]:
    if not isinstance(wsl_exe, str) or not wsl_exe:
        raise WslBridgeError("wsl executable is required")
    if not isinstance(distribution, str) or not distribution.strip() or len(distribution) > 160:
        raise WslBridgeError("WSL distribution is invalid")
    command = validate_linux_command(linux_command)
    translated = translate_bodyrig_paths(command, converter)
    return [wsl_exe, "-d", distribution.strip(), "--", *translated]


def _wsl_path_converter(wsl_exe: str, distribution: str) -> Callable[[str], str]:
    def convert(path: str) -> str:
        completed = subprocess.run(
            [wsl_exe, "-d", distribution, "--", "wslpath", "-a", path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip()[-1000:]
            raise WslBridgeError(f"wslpath failed for BodyRig path: {detail}")
        value = completed.stdout.strip()
        if not value or "\n" in value or "\r" in value:
            raise WslBridgeError("wslpath returned an invalid path")
        return value

    return convert


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Translate BodyRig adapter paths and invoke a Linux adapter through WSL without a command shell."
    )
    parser.add_argument("--distribution", required=True, help="WSL distribution name")
    parser.add_argument("--wsl-exe", default="wsl.exe", help="WSL executable; defaults to wsl.exe")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Linux adapter argv after --; BodyRig transport flags are appended by the caller",
    )
    args = parser.parse_args(argv)

    try:
        distribution = args.distribution.strip()
        converter = _wsl_path_converter(args.wsl_exe, distribution)
        invocation = build_wsl_invocation(
            wsl_exe=args.wsl_exe,
            distribution=distribution,
            linux_command=args.command,
            converter=converter,
        )
        completed = subprocess.run(
            invocation,
            stdin=subprocess.DEVNULL,
            stdout=sys.stdout,
            stderr=sys.stderr,
            shell=False,
            check=False,
        )
    except (OSError, WslBridgeError) as exc:
        print(f"BodyRig WSL adapter bridge: {exc}", file=sys.stderr)
        return 1
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
