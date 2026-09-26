from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


EXPECTED_COMMIT = "03f0b7d00383d6e96c22b37325ac9e5450947bf5"
EXPECTED_TREE = "74064838bc2383b187fc68693bc95f5df68309a6"
FORMAT = "bodyrig-exavatar-rasterizer-conic-offdiag-ab"
VERSION = 3
UPSTREAM_REFERENCE = "graphdeco-inria/diff-gaussian-rasterization#94"
UPSTREAM_REFERENCE_TITLE = "Bug: Incorrect Gradient for Off-Diagonal Conic Term in Backward Pass"
ORIGINAL = (
    "atomicAdd(&dL_dconic2D[global_id].y, "
    "-0.5f * gdx * d.y * dL_dG);"
)
PATCHED = (
    "atomicAdd(&dL_dconic2D[global_id].y, "
    "-1.0f * gdx * d.y * dL_dG);"
)


class RasterizerABError(ValueError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare an isolated Gaussian rasterizer with the documented off-diagonal conic gradient correction."
    )
    parser.add_argument("--workspace-root", required=True)
    return parser


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_tree(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RasterizerABError(
            "could not verify source Gaussian rasterizer git tree"
        )
    return completed.stdout.strip().lower()


def _git_head(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RasterizerABError(
            "could not verify source Gaussian rasterizer git HEAD"
        )
    return completed.stdout.strip().lower()


def _require_clean_tracked_tree(repo: Path) -> None:
    checks = (
        ["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--"],
        ["git", "-C", str(repo), "diff", "--cached", "--quiet", "--"],
    )
    for argv in checks:
        completed = subprocess.run(
            argv,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode not in (0, 1):
            raise RasterizerABError(
                "could not verify source Gaussian rasterizer tracked working tree"
            )
        if completed.returncode == 1:
            raise RasterizerABError(
                "source Gaussian rasterizer has tracked modifications; refusing A/B copy"
            )


def _copy_tracked_tree(source: Path, staging: Path) -> int:
    completed = subprocess.run(
        ["git", "-C", str(source), "ls-files", "-z"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise RasterizerABError(
            "could not enumerate tracked Gaussian rasterizer files"
        )
    raw_paths = [
        item for item in completed.stdout.split(b"\0") if item
    ]
    if not raw_paths:
        raise RasterizerABError(
            "source Gaussian rasterizer has no tracked files"
        )
    staging.mkdir(parents=True, exist_ok=False)
    copied = 0
    source_root = source.resolve()
    staging_root = staging.resolve()
    for raw in raw_paths:
        try:
            relative_text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RasterizerABError(
                "source Gaussian rasterizer has non-UTF-8 tracked path"
            ) from exc
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise RasterizerABError(
                f"unsafe tracked rasterizer path: {relative_text}"
            )
        src = (source_root / relative).resolve()
        dst = staging_root / relative
        try:
            src.relative_to(source_root)
        except ValueError as exc:
            raise RasterizerABError(
                f"tracked rasterizer path escapes source root: {relative_text}"
            ) from exc
        if not src.is_file() or src.is_symlink():
            raise RasterizerABError(
                f"tracked rasterizer file is missing or unsafe: {relative_text}"
            )
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    return copied


def _reject_symlinks(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise RasterizerABError(f"source rasterizer is missing or unsafe: {root}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RasterizerABError(
                f"source rasterizer contains symlink and cannot be isolated safely: {path}"
            )


def _patch_backward_source(raw: str) -> str:
    if raw.count(ORIGINAL) != 1 or raw.count(PATCHED) != 0:
        raise RasterizerABError(
            "pinned rasterizer conic-gradient marker changed or is ambiguous"
        )
    return raw.replace(ORIGINAL, PATCHED, 1)


def _clear_staged_build_artifacts(staging: Path) -> None:
    build_dir = staging / "build"
    if build_dir.is_symlink():
        raise RasterizerABError("staged rasterizer build directory may not be a symlink")
    if build_dir.exists():
        if not build_dir.is_dir():
            raise RasterizerABError("staged rasterizer build path is not a directory")
        shutil.rmtree(build_dir)

    package = staging / "diff_gaussian_rasterization_depth"
    if not package.is_dir() or package.is_symlink():
        raise RasterizerABError("staged rasterizer package is missing or unsafe")
    for candidate in package.glob("_C*.so"):
        if candidate.is_symlink() or not candidate.is_file():
            raise RasterizerABError(
                f"staged rasterizer extension candidate is unsafe: {candidate}"
            )
        candidate.unlink()


def _read_receipt(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RasterizerABError("existing rasterizer A/B receipt is unreadable") from exc
    if not isinstance(value, dict):
        raise RasterizerABError("existing rasterizer A/B receipt is invalid")
    return value


def _import_smoke(repo: Path, env: dict[str, str]) -> str:
    smoke_env = dict(env)
    smoke_env["PYTHONPATH"] = str(repo)
    code = (
        "import json, pathlib\n"
        "import diff_gaussian_rasterization_depth._C as ext\n"
        "print(json.dumps({'origin': pathlib.Path(ext.__file__).resolve().as_posix()}))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo),
        env=smoke_env,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RasterizerABError(
            "isolated rasterizer A/B CUDA extension import smoke failed: "
            + completed.stderr.replace("\n", " ")[:1000]
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise RasterizerABError(
            "isolated rasterizer A/B import smoke did not emit exactly one record"
        )
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise RasterizerABError(
            "isolated rasterizer A/B import smoke emitted invalid JSON"
        ) from exc
    origin_raw = payload.get("origin") if isinstance(payload, dict) else None
    if not isinstance(origin_raw, str) or not origin_raw:
        raise RasterizerABError(
            "isolated rasterizer A/B import smoke omitted module origin"
        )
    origin = Path(origin_raw).resolve()
    try:
        origin.relative_to(repo.resolve())
    except ValueError as exc:
        raise RasterizerABError(
            f"isolated rasterizer A/B imported extension outside staged repo: {origin}"
        ) from exc
    return origin.relative_to(repo.resolve()).as_posix()


def _validate_existing(
    destination: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    receipt_path = destination / "bodyrig-rasterizer-ab-receipt.json"
    receipt = _read_receipt(receipt_path)
    if (
        receipt.get("format") != FORMAT
        or receipt.get("version") != VERSION
        or receipt.get("source_commit") != EXPECTED_COMMIT
        or receipt.get("source_tree") != EXPECTED_TREE
        or receipt.get("patch") != "off-diagonal-conic-gradient--0.5-to--1.0"
        or receipt.get("upstream_reference") != UPSTREAM_REFERENCE
        or receipt.get("fresh_build_artifacts") is not True
        or not isinstance(receipt.get("tracked_file_count"), int)
        or isinstance(receipt.get("tracked_file_count"), bool)
        or receipt.get("tracked_file_count") < 1
    ):
        raise RasterizerABError("existing rasterizer A/B receipt does not match expected experiment")
    backward = destination / "cuda_rasterizer" / "backward.cu"
    if not backward.is_file() or backward.is_symlink():
        raise RasterizerABError("existing rasterizer A/B backward.cu is missing or unsafe")
    if _file_sha(backward) != receipt.get("patched_backward_sha256"):
        raise RasterizerABError("existing rasterizer A/B backward.cu digest mismatch")
    package = destination / "diff_gaussian_rasterization_depth"
    built = sorted(package.glob("_C*.so"))
    if len(built) != 1 or built[0].is_symlink() or not built[0].is_file():
        raise RasterizerABError("existing rasterizer A/B CUDA extension is missing or ambiguous")
    if _file_sha(built[0]) != receipt.get("extension_sha256"):
        raise RasterizerABError("existing rasterizer A/B CUDA extension digest mismatch")
    recorded_origin = receipt.get("extension_import_relative_path")
    recorded_extension = receipt.get("extension_relative_path")
    if not isinstance(recorded_origin, str) or not recorded_origin:
        raise RasterizerABError("existing rasterizer A/B receipt lacks import origin")
    if recorded_origin != recorded_extension:
        raise RasterizerABError(
            "existing rasterizer A/B receipt extension paths disagree"
        )
    actual_origin = _import_smoke(destination, env)
    if actual_origin != recorded_origin:
        raise RasterizerABError(
            "existing rasterizer A/B import origin does not match receipt"
        )
    return receipt


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.workspace_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise RasterizerABError(f"workspace root is missing or unsafe: {root}")

    source = root / "repos" / "diff-gaussian-rasterization-depth"
    destination = root / "diagnostics" / "rasterizer-conic-offdiag-fix"
    staging = root / "diagnostics" / "rasterizer-conic-offdiag-fix.staging"
    log_path = root / "logs" / "teacher" / "rasterizer-conic-offdiag-build.log"
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env.setdefault("FORCE_CUDA", "1")

    if destination.exists() or destination.is_symlink():
        receipt = _validate_existing(destination, env)
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 0
    if staging.exists() or staging.is_symlink():
        raise RasterizerABError(
            f"stale rasterizer A/B staging path exists: {staging}"
        )

    _reject_symlinks(source)
    _require_clean_tracked_tree(source)
    source_head = _git_head(source)
    if source_head != EXPECTED_COMMIT:
        raise RasterizerABError(
            f"source Gaussian rasterizer HEAD mismatch: {source_head}"
        )
    source_tree = _git_tree(source)
    if source_tree != EXPECTED_TREE:
        raise RasterizerABError(
            f"source Gaussian rasterizer tree mismatch: {source_tree}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    tracked_file_count = _copy_tracked_tree(source, staging)
    _clear_staged_build_artifacts(staging)

    backward = staging / "cuda_rasterizer" / "backward.cu"
    if not backward.is_file() or backward.is_symlink():
        raise RasterizerABError("staged rasterizer backward.cu is missing or unsafe")
    raw = backward.read_text(encoding="utf-8")
    source_backward_sha = _file_sha(backward)
    backward.write_text(_patch_backward_source(raw), encoding="utf-8")
    patched_backward_sha = _file_sha(backward)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            [sys.executable, "setup.py", "build_ext", "--inplace"],
            cwd=str(staging),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if completed.returncode != 0:
        raise RasterizerABError(
            f"isolated rasterizer A/B build failed with code {completed.returncode}; log: {log_path}"
        )

    package = staging / "diff_gaussian_rasterization_depth"
    built = sorted(package.glob("_C*.so"))
    if len(built) != 1 or built[0].is_symlink() or not built[0].is_file():
        raise RasterizerABError(
            "isolated rasterizer A/B build did not produce exactly one CUDA extension"
        )
    extension_origin = _import_smoke(staging, env)
    extension_relative_path = built[0].relative_to(staging).as_posix()
    if extension_origin != extension_relative_path:
        raise RasterizerABError(
            "isolated rasterizer A/B imported extension does not match built extension"
        )

    receipt: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "source_commit": EXPECTED_COMMIT,
        "source_tree": EXPECTED_TREE,
        "patch": "off-diagonal-conic-gradient--0.5-to--1.0",
        "upstream_reference": UPSTREAM_REFERENCE,
        "upstream_reference_title": UPSTREAM_REFERENCE_TITLE,
        "source_backward_sha256": source_backward_sha,
        "patched_backward_sha256": patched_backward_sha,
        "extension_relative_path": extension_relative_path,
        "extension_sha256": _file_sha(built[0]),
        "extension_import_relative_path": extension_origin,
        "fresh_build_artifacts": True,
        "tracked_file_count": tracked_file_count,
        "build_log_sha256": _file_sha(log_path),
        "production_activation": False,
    }
    (staging / "bodyrig-rasterizer-ab-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    staging.replace(destination)
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RasterizerABError as exc:
        print(f"BodyRig rasterizer A/B: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
