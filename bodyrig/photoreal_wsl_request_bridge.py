from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter


class PhotorealWslRequestBridgeError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealWslRequestBridgeError(f"BodyRig request is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealWslRequestBridgeError("BodyRig request must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealWslRequestBridgeError(f"{label} is invalid")
    return result


def _source_fingerprint(source: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _text(source.get("source_key"), label="source_key", maximum=4096),
        _text(source.get("source_sha256"), label="source_sha256", maximum=64),
        _text(source.get("kind"), label="source kind", maximum=16),
    )


def rewrite_request_transport_paths(
    request: Mapping[str, Any],
    converter: Callable[[str], str],
) -> dict[str, Any]:
    """Translate only nested resolved_path transport fields.

    The returned request is an ephemeral transport copy. Source keys, source
    SHA-256 values, labels, splits, samples and authority fields are preserved.
    """

    result = copy.deepcopy(dict(request))
    sources = result.get("sources")
    original_sources = request.get("sources")
    if not isinstance(sources, list) or not isinstance(original_sources, list) or not sources:
        raise PhotorealWslRequestBridgeError("BodyRig request contains no source list")
    if len(sources) != len(original_sources):
        raise PhotorealWslRequestBridgeError("BodyRig request source cardinality changed")

    for index, source in enumerate(sources):
        original = original_sources[index]
        if not isinstance(source, dict) or not isinstance(original, Mapping):
            raise PhotorealWslRequestBridgeError("BodyRig request contains an invalid source")
        if _source_fingerprint(source) != _source_fingerprint(original):
            raise PhotorealWslRequestBridgeError("BodyRig request source identity changed before translation")
        raw_path = _text(source.get("resolved_path"), label="resolved source path")
        translated = converter(raw_path)
        translated = _text(translated, label="translated source path")
        if not translated.startswith("/"):
            raise PhotorealWslRequestBridgeError("translated source path is not an absolute Linux path")
        source["resolved_path"] = translated

    for index, source in enumerate(sources):
        original = original_sources[index]
        if _source_fingerprint(source) != _source_fingerprint(original):
            raise PhotorealWslRequestBridgeError("transport translation changed source evidence identity")
        for key, value in original.items():
            if key == "resolved_path":
                continue
            if source.get(key) != value:
                raise PhotorealWslRequestBridgeError(f"transport translation changed source field: {key}")
    return result


def build_linux_invocation(
    *,
    linux_python: str,
    linux_adapter_path: str,
    linux_model_root: str,
    linux_request_path: str,
    linux_output_path: str,
    device: str,
    bodyrig_adapter: str,
    bodyrig_revision: str,
    bodyrig_model_set_sha256: str,
    bodyrig_identity_bank_sha256: str | None,
) -> list[str]:
    fields = {
        "linux python": linux_python,
        "linux adapter path": linux_adapter_path,
        "linux model root": linux_model_root,
        "linux request path": linux_request_path,
        "linux output path": linux_output_path,
        "device": device,
        "BodyRig adapter": bodyrig_adapter,
        "BodyRig revision": bodyrig_revision,
        "BodyRig model-set SHA-256": bodyrig_model_set_sha256,
    }
    normalized = {key: _text(value, label=key) for key, value in fields.items()}
    for key in ("linux adapter path", "linux model root", "linux request path", "linux output path"):
        if not normalized[key].startswith("/"):
            raise PhotorealWslRequestBridgeError(f"{key} must be an absolute Linux path")
    argv = [
        normalized["linux python"],
        normalized["linux adapter path"],
        "--model-root",
        normalized["linux model root"],
        "--device",
        normalized["device"],
        "--bodyrig-request",
        normalized["linux request path"],
        "--bodyrig-output",
        normalized["linux output path"],
        "--bodyrig-adapter",
        normalized["BodyRig adapter"],
        "--bodyrig-revision",
        normalized["BodyRig revision"],
        "--bodyrig-model-set-sha256",
        normalized["BodyRig model-set SHA-256"],
    ]
    if bodyrig_identity_bank_sha256:
        argv.extend(
            [
                "--bodyrig-identity-bank-sha256",
                _text(bodyrig_identity_bank_sha256, label="BodyRig identity bank SHA-256", maximum=64),
            ]
        )
    return argv


def _run_wsl(invocation: list[str]) -> int:
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Translate nested BodyRig Photoreal source paths and invoke the pinned Linux vision adapter through WSL."
    )
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--linux-python", required=True)
    parser.add_argument("--adapter-path", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--bodyrig-request", type=Path, required=True)
    parser.add_argument("--bodyrig-output", type=Path, required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--bodyrig-model-set-sha256", required=True)
    parser.add_argument("--bodyrig-identity-bank-sha256", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request_path = args.bodyrig_request.expanduser().resolve()
        output_path = args.bodyrig_output.expanduser().resolve()
        adapter_path = args.adapter_path.expanduser().resolve()
        model_root = args.model_root.expanduser().resolve()
        if not request_path.is_file():
            raise PhotorealWslRequestBridgeError(f"BodyRig request not found: {request_path}")
        if not output_path.is_dir():
            raise PhotorealWslRequestBridgeError(f"BodyRig output directory not found: {output_path}")
        if not adapter_path.is_file():
            raise PhotorealWslRequestBridgeError(f"reference vision adapter not found: {adapter_path}")
        if not model_root.is_dir():
            raise PhotorealWslRequestBridgeError(f"reference vision model root not found: {model_root}")

        converter = make_wsl_path_converter(args.wsl_exe, args.distribution)
        request = _read_json(request_path)
        translated_request = rewrite_request_transport_paths(request, converter)

        with tempfile.TemporaryDirectory(prefix="bodyrig-photoreal-wsl-") as temp_dir:
            translated_request_path = Path(temp_dir) / "request.json"
            translated_request_path.write_text(
                json.dumps(translated_request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            linux_request = converter(str(translated_request_path))
            linux_output = converter(str(output_path))
            linux_adapter = converter(str(adapter_path))
            linux_model_root = converter(str(model_root))
            linux_argv = build_linux_invocation(
                linux_python=args.linux_python,
                linux_adapter_path=linux_adapter,
                linux_model_root=linux_model_root,
                linux_request_path=linux_request,
                linux_output_path=linux_output,
                device=args.device,
                bodyrig_adapter=args.bodyrig_adapter,
                bodyrig_revision=args.bodyrig_revision,
                bodyrig_model_set_sha256=args.bodyrig_model_set_sha256,
                bodyrig_identity_bank_sha256=args.bodyrig_identity_bank_sha256 or None,
            )
            invocation = [args.wsl_exe, "-d", args.distribution, "--", *linux_argv]
            return _run_wsl(invocation)
    except (OSError, WslBridgeError, PhotorealWslRequestBridgeError) as exc:
        print(f"BodyRig Photoreal WSL request bridge: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
