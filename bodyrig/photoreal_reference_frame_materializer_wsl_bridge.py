from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .photoreal_wsl_request_bridge import (
    PhotorealWslRequestBridgeError,
    rewrite_request_transport_paths,
)
from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter


class PhotorealReferenceFrameMaterializerWslError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealReferenceFrameMaterializerWslError(f"request is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealReferenceFrameMaterializerWslError("request must be a JSON object")
    return value


def _text(value: str, *, label: str) -> str:
    result = str(value or "").strip()
    if not result or "\n" in result or "\r" in result:
        raise PhotorealReferenceFrameMaterializerWslError(f"{label} is invalid")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Translate build-private held-out source paths and invoke the pinned reference-frame materializer in WSL."
    )
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--linux-python", required=True)
    parser.add_argument("--adapter-path", type=Path, required=True)
    parser.add_argument("--bodyrig-request", type=Path, required=True)
    parser.add_argument("--bodyrig-output", type=Path, required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request_path = args.bodyrig_request.expanduser().resolve()
        output_path = args.bodyrig_output.expanduser().resolve()
        adapter_path = args.adapter_path.expanduser().resolve()
        if not request_path.is_file():
            raise PhotorealReferenceFrameMaterializerWslError(f"request not found: {request_path}")
        if not output_path.is_dir():
            raise PhotorealReferenceFrameMaterializerWslError(f"output directory not found: {output_path}")
        if not adapter_path.is_file():
            raise PhotorealReferenceFrameMaterializerWslError(f"materializer adapter not found: {adapter_path}")

        converter = make_wsl_path_converter(args.wsl_exe, args.distribution)
        request = _read_json(request_path)
        translated = rewrite_request_transport_paths(request, converter)
        with tempfile.TemporaryDirectory(prefix="bodyrig-photoreal-reference-materializer-") as temp_dir:
            translated_request = Path(temp_dir) / "request.json"
            translated_request.write_text(
                json.dumps(translated, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            linux_request = _text(converter(str(translated_request)), label="Linux request path")
            linux_output = _text(converter(str(output_path)), label="Linux output path")
            linux_adapter = _text(converter(str(adapter_path)), label="Linux adapter path")
            linux_python = _text(args.linux_python, label="Linux Python")
            if not linux_python.startswith("/") or not linux_request.startswith("/") or not linux_output.startswith("/") or not linux_adapter.startswith("/"):
                raise PhotorealReferenceFrameMaterializerWslError("translated Linux paths must be absolute")
            invocation = [
                args.wsl_exe,
                "-d",
                args.distribution,
                "--",
                linux_python,
                linux_adapter,
                "--bodyrig-request",
                linux_request,
                "--bodyrig-output",
                linux_output,
                "--bodyrig-adapter",
                args.bodyrig_adapter,
                "--bodyrig-revision",
                args.bodyrig_revision,
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
    except (OSError, WslBridgeError, PhotorealWslRequestBridgeError, PhotorealReferenceFrameMaterializerWslError) as exc:
        print(f"BodyRig reference frame materializer WSL bridge: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
