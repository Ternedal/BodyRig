from __future__ import annotations

import argparse
import codecs
import hashlib
import subprocess
import sys
from pathlib import Path
from bodyrig import hashing

if __package__:
    from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter
else:  # direct-file execution from the generic external-teacher runner
    _repo_root = Path(__file__).resolve().parents[1]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from bodyrig.wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter

REVISION_PREFIX = "sha256:"
REVISION_DOMAIN = b"bodyrig-photoreal-exavatar-teacher-transport-v1\0"


class PhotorealExAvatarTeacherWslError(ValueError):
    pass


def _text(value: str, *, label: str, maximum: int = 32768) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealExAvatarTeacherWslError(f"{label} is invalid")
    return result


def _write_child_output(value: str) -> None:
    if not value:
        return
    stream = sys.stdout
    binary = getattr(stream, "buffer", None)
    if binary is not None:
        binary.write(value.encode("utf-8", errors="replace"))
        binary.flush()
        return

    encoding = str(getattr(stream, "encoding", None) or "utf-8")
    safe = value.encode(encoding, errors="backslashreplace").decode(
        encoding,
        errors="strict",
    )
    stream.write(safe)
    stream.flush()


def _relay_child(invocation: list[str]) -> int:
    """Run the adapter and pass its output on as it arrives.

    The adapter prints a progress line with an ETA during a multi-day
    training run. Capturing all output until exit would keep those lines out
    of the Windows-side adapter.log until training is over.
    """
    process = subprocess.Popen(
        invocation,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
    )
    assert process.stdout is not None
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    try:
        while True:
            chunk = process.stdout.read1(65536)
            if not chunk:
                break
            _write_child_output(decoder.decode(chunk))
        _write_child_output(decoder.decode(b"", final=True))
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        process.stdout.close()
    return int(process.wait())


DENSIFY_END_FRACTION_MIN = 0.05


def canonical_densify_end_fraction(raw: object) -> str | None:
    """Anders' opt-in end of scene densification (option B) as the one canonical string, or None.

    None, "" and "0" mean the upstream schedule. Otherwise a number in 0.05..1.0, written with four
    decimals, so the config, the bridge and the adapter all see the same value."""
    if raw is None or (isinstance(raw, str) and raw.strip() in ("", "0")):
        return None
    if isinstance(raw, bool):
        raise PhotorealExAvatarTeacherWslError("densify end fraction must be a number")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise PhotorealExAvatarTeacherWslError("densify end fraction must be a number") from exc
    if value != value or not DENSIFY_END_FRACTION_MIN <= value <= 1.0:
        raise PhotorealExAvatarTeacherWslError(f"densify end fraction must be in {DENSIFY_END_FRACTION_MIN}..1.0")
    return f"{value:.4f}"


def _file_sha(path: Path) -> str:
    return hashing.sha256_file(path, chunk_size=8*1024*1024)


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
    parser.add_argument("--densify-end-fraction", default=None)
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
        if output.is_symlink():
            raise PhotorealExAvatarTeacherWslError(f"BodyRig teacher output path may not be a symlink: {output}")
        if output.exists():
            if not output.is_dir():
                raise PhotorealExAvatarTeacherWslError(f"BodyRig teacher output path is not a directory: {output}")
        elif not output.parent.is_dir():
            raise PhotorealExAvatarTeacherWslError(f"BodyRig teacher output parent directory not found: {output.parent}")
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
        if output.exists():
            linux_output = converter(str(output))
        else:
            linux_output_parent = converter(str(output.parent))
            linux_output = f"{linux_output_parent.rstrip('/')}/{output.name}"
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
        densify_end_fraction = canonical_densify_end_fraction(args.densify_end_fraction)
        if densify_end_fraction is not None:
            invocation += ["--bodyrig-densify-end-fraction", densify_end_fraction]
        return _relay_child(invocation)
    except (OSError, WslBridgeError, PhotorealExAvatarTeacherWslError) as exc:
        print(f"BodyRig ExAvatar teacher WSL bridge: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
