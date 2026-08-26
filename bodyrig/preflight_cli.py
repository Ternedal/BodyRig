from __future__ import annotations

import argparse
import json
import os
import posixpath
import subprocess
import sys
from pathlib import Path

from .bridges.hmr2_config import (
    FOUR_D_HUMANS_REVISION,
    NMR_REMOTE,
    NMR_REVISION,
    PHALP_REVISION,
    PHALP_TRACKER_BLOB_SHA1,
)
from .recovery_authority import RecoveryAuthorityError, resolve_phalp_repo

SMPL_FILENAME = "basicModel_neutral_lbs_10_207_0_v1.0.0.pkl"
WSL_CUDA_DRIVER_LIB = "/usr/lib/wsl/lib"
WSL_CUDA_TOOLKIT_LIB = "/usr/local/cuda-11.7/lib64"


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _repo_head(repo: Path, label: str) -> str:
    completed = _run(["git", "rev-parse", "HEAD"], cwd=repo)
    if completed.returncode != 0:
        raise RuntimeError(f"could not read {label} Git HEAD")
    return completed.stdout.strip().lower()


def _repo_clean(repo: Path, label: str) -> bool:
    completed = _run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo)
    if completed.returncode != 0:
        raise RuntimeError(f"could not read {label} tracked-file status")
    return not completed.stdout.strip()


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _same_linux_path(left: str, right: str) -> bool:
    return posixpath.normpath(left) == posixpath.normpath(right)


def _normalize_git_url(value: str) -> str:
    normalized = value.strip().lower().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized


def _probe_script() -> str:
    return f'''\
import ctypes, hashlib, importlib.metadata, importlib.util, json, pathlib, sys
EXPECTED = {PHALP_TRACKER_BLOB_SHA1!r}
NMR_EXPECTED = {NMR_REVISION!r}
NMR_REMOTE_EXPECTED = {NMR_REMOTE!r}
def blob(data):
    return hashlib.sha1(("blob %d\\0" % len(data)).encode("ascii") + data).hexdigest()
def normalize_url(value):
    value = (value or "").strip().lower().rstrip("/")
    return value[:-4] if value.endswith(".git") else value
result = {{"python": sys.version.split()[0]}}
for name in ("torch", "cv2", "joblib", "hmr2", "phalp", "neural_renderer"):
    try:
        __import__(name)
        result["import_" + name] = True
    except Exception as exc:
        result["import_" + name] = False
        result["error_" + name] = type(exc).__name__ + ": " + str(exc)
try:
    import torch
    result["torch_version"] = str(torch.__version__)
    result["torch_cuda_version"] = str(torch.version.cuda)
    result["torch_lib"] = str(pathlib.Path(torch.__file__).resolve().parent / "lib")
    result["cuda_available"] = bool(torch.cuda.is_available())
    result["cuda_device"] = torch.cuda.get_device_name(0) if result["cuda_available"] else None
except Exception as exc:
    result["cuda_available"] = False
    result["cuda_device"] = None
    result["error_torch_runtime"] = type(exc).__name__ + ": " + str(exc)
for library, key in (("libcuda.so", "load_libcuda"), ("libcudnn_cnn_infer.so.8", "load_libcudnn_cnn_infer")):
    try:
        ctypes.CDLL(library)
        result[key] = True
    except Exception as exc:
        result[key] = False
        result["error_" + key] = type(exc).__name__ + ": " + str(exc)
try:
    dist = importlib.metadata.distribution("neural-renderer-pytorch")
    result["nmr_version"] = str(dist.version)
    direct_raw = dist.read_text("direct_url.json")
    direct = json.loads(direct_raw) if direct_raw else {{}}
    result["nmr_url"] = direct.get("url")
    vcs_info = direct.get("vcs_info") or {{}}
    result["nmr_commit"] = vcs_info.get("commit_id")
    result["nmr_authority_match"] = (
        result["nmr_commit"] == NMR_EXPECTED
        and normalize_url(result["nmr_url"]) == normalize_url(NMR_REMOTE_EXPECTED)
    )
except Exception as exc:
    result["nmr_authority_match"] = False
    result["error_nmr_authority"] = type(exc).__name__ + ": " + str(exc)
spec = importlib.util.find_spec("phalp")
if spec is not None and spec.submodule_search_locations:
    root = pathlib.Path(next(iter(spec.submodule_search_locations))).resolve()
    result["phalp_root"] = str(root)
    tracker = root / "trackers" / "PHALP.py"
    if tracker.is_file():
        data = tracker.read_bytes()
        hashes = [blob(data)]
        normalized = data.replace(b"\\r\\n", b"\\n")
        if normalized != data:
            hashes.append(blob(normalized))
        result["phalp_tracker_match"] = EXPECTED in hashes
        result["phalp_tracker_hashes"] = hashes
print(json.dumps(result, separators=(",", ":")))
'''


def _external_probe(python: Path) -> dict:
    completed = _run([str(python), "-c", _probe_script()])
    if completed.returncode != 0:
        raise RuntimeError(f"external Python probe failed: {completed.stderr.strip()[-2000:]}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("external Python probe returned invalid JSON") from exc


def _run_wsl(*, wsl_exe: str, distribution: str, command: list[str]) -> subprocess.CompletedProcess[str]:
    return _run([wsl_exe, "-d", distribution, "--", *command])


def _wsl_test(*, wsl_exe: str, distribution: str, flag: str, path: str) -> bool:
    completed = _run_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        command=["/usr/bin/test", flag, path],
    )
    return completed.returncode == 0


def _wsl_git_head(*, wsl_exe: str, distribution: str, repo: str, label: str) -> str:
    completed = _run_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        command=["git", "-C", repo, "rev-parse", "HEAD"],
    )
    if completed.returncode != 0:
        raise RuntimeError(f"could not read {label} Git HEAD in WSL")
    return completed.stdout.strip().lower()


def _wsl_repo_clean(*, wsl_exe: str, distribution: str, repo: str, label: str) -> bool:
    completed = _run_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        command=["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"],
    )
    if completed.returncode != 0:
        raise RuntimeError(f"could not read {label} tracked-file status in WSL")
    return not completed.stdout.strip()


def _wsl_torch_lib(*, wsl_exe: str, distribution: str, python: str) -> str:
    completed = _run_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        command=[python, "-c", "import pathlib,torch; print((pathlib.Path(torch.__file__).resolve().parent / 'lib').as_posix())"],
    )
    torch_lib = completed.stdout.strip()
    if completed.returncode != 0 or not torch_lib.startswith("/"):
        raise RuntimeError(f"could not determine external WSL torch library path: {completed.stderr.strip()[-2000:]}")
    return torch_lib


def _external_probe_wsl(*, wsl_exe: str, distribution: str, python: str) -> dict:
    torch_lib = _wsl_torch_lib(wsl_exe=wsl_exe, distribution=distribution, python=python)
    loader_path = ":".join((WSL_CUDA_DRIVER_LIB, torch_lib, WSL_CUDA_TOOLKIT_LIB))
    completed = _run_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        command=["/usr/bin/env", f"LD_LIBRARY_PATH={loader_path}", python, "-c", _probe_script()],
    )
    if completed.returncode != 0:
        raise RuntimeError(f"external WSL Python probe failed: {completed.stderr.strip()[-2000:]}")
    try:
        probe = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("external WSL Python probe returned invalid JSON") from exc
    probe["loader_ld_library_path"] = loader_path
    probe["torch_lib"] = torch_lib
    return probe


def _validate_probe(probe: dict, errors: list[str], *, phalp_repo: str | Path, linux: bool, allow_cpu: bool) -> None:
    for name in ("torch", "cv2", "joblib", "hmr2", "phalp", "neural_renderer"):
        if probe.get("import_" + name) is not True:
            errors.append(f"external import failed: {name}: {probe.get('error_' + name, 'unknown error')}")
    imported_root = probe.get("phalp_root")
    if not isinstance(imported_root, str) or not imported_root.strip():
        errors.append("external PHALP import did not expose a package root")
    elif linux:
        expected = posixpath.join(str(phalp_repo), "phalp")
        if not _same_linux_path(imported_root, expected):
            errors.append(f"external PHALP import is not sourced from the pinned checkout: {imported_root}")
    elif not _same_path(Path(imported_root), Path(phalp_repo) / "phalp"):
        errors.append(f"external PHALP import is not sourced from the pinned checkout: {imported_root}")
    if probe.get("phalp_tracker_match") is not True:
        errors.append("installed PHALP tracker source does not match pinned BodyRig blob")
    if probe.get("nmr_authority_match") is not True:
        errors.append(
            "installed neural-renderer does not match pinned BodyRig NMR authority: "
            f"{probe.get('nmr_url')!r}@{probe.get('nmr_commit')!r}"
        )
    if not allow_cpu and probe.get("cuda_available") is not True:
        errors.append("CUDA is not available in the external recovery Python")
    if linux and not allow_cpu:
        if probe.get("load_libcuda") is not True:
            errors.append(f"WSL CUDA loader cannot open libcuda.so: {probe.get('error_load_libcuda', 'unknown error')}")
        if probe.get("load_libcudnn_cnn_infer") is not True:
            errors.append(
                "WSL CUDA loader cannot open libcudnn_cnn_infer.so.8: "
                f"{probe.get('error_load_libcudnn_cnn_infer', 'unknown error')}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the external 4D-Humans recovery environment for BodyRig.")
    parser.add_argument("--python", required=True, dest="external_python")
    parser.add_argument("--repo", required=True, help="Pinned 4D-Humans checkout")
    parser.add_argument(
        "--phalp-repo",
        default="",
        help="Pinned PHALP checkout. WSL recovery requires this explicitly.",
    )
    parser.add_argument("--distribution", default="", help="WSL distribution containing the recovery runtime")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--allow-cpu", action="store_true", help="Do not fail when CUDA is unavailable")
    parser.add_argument("--out", help="Optional JSON report path")
    args = parser.parse_args(argv)

    errors: list[str] = []
    checks: dict[str, object] = {
        "format": "bodyrig-recovery-preflight",
        "version": 1,
        "four_d_humans_expected": FOUR_D_HUMANS_REVISION,
        "phalp_expected": PHALP_REVISION,
        "phalp_tracker_expected_blob": PHALP_TRACKER_BLOB_SHA1,
        "nmr_expected": NMR_REVISION,
        "nmr_remote_expected": NMR_REMOTE,
    }

    distribution = args.distribution.strip()
    if distribution:
        python = args.external_python.strip()
        repo = args.repo.strip().rstrip("/")
        phalp_repo = args.phalp_repo.strip().rstrip("/")
        checks["transport"] = "wsl"
        checks["distribution"] = distribution

        for label, value in (("external Python", python), ("4D-Humans repo", repo), ("PHALP repo", phalp_repo)):
            if not value.startswith("/"):
                errors.append(f"WSL {label} must be an absolute Linux path: {value}")
        if not phalp_repo:
            errors.append("WSL recovery requires --phalp-repo explicitly")

        if not errors:
            if not _wsl_test(wsl_exe=args.wsl_exe, distribution=distribution, flag="-f", path=python):
                errors.append(f"external WSL Python not found: {python}")
            if not _wsl_test(wsl_exe=args.wsl_exe, distribution=distribution, flag="-f", path=posixpath.join(repo, "track.py")):
                errors.append(f"not a 4D-Humans checkout in WSL: {repo}")
            if not _wsl_test(wsl_exe=args.wsl_exe, distribution=distribution, flag="-d", path=posixpath.join(phalp_repo, "phalp")):
                errors.append(f"not a PHALP checkout in WSL: {phalp_repo}")

        if not errors:
            try:
                head = _wsl_git_head(wsl_exe=args.wsl_exe, distribution=distribution, repo=repo, label="4D-Humans")
                checks["four_d_humans_head"] = head
                if head != FOUR_D_HUMANS_REVISION:
                    errors.append(f"4D-Humans HEAD mismatch: {head}")
                clean = _wsl_repo_clean(wsl_exe=args.wsl_exe, distribution=distribution, repo=repo, label="4D-Humans")
                checks["four_d_humans_tracked_clean"] = clean
                if not clean:
                    errors.append("4D-Humans has modified tracked files")
            except Exception as exc:
                errors.append(str(exc))

            try:
                phalp_head = _wsl_git_head(wsl_exe=args.wsl_exe, distribution=distribution, repo=phalp_repo, label="PHALP")
                checks["phalp_head"] = phalp_head
                if phalp_head != PHALP_REVISION:
                    errors.append(f"PHALP HEAD mismatch: {phalp_head}")
                phalp_clean = _wsl_repo_clean(wsl_exe=args.wsl_exe, distribution=distribution, repo=phalp_repo, label="PHALP")
                checks["phalp_tracked_clean"] = phalp_clean
                if not phalp_clean:
                    errors.append("PHALP has modified tracked files")
            except Exception as exc:
                errors.append(str(exc))

            smpl = posixpath.join(repo, "data", SMPL_FILENAME)
            smpl_present = _wsl_test(wsl_exe=args.wsl_exe, distribution=distribution, flag="-f", path=smpl)
            checks["smpl_present"] = smpl_present
            if not smpl_present:
                errors.append(f"required SMPL model missing: data/{SMPL_FILENAME}")

            try:
                probe = _external_probe_wsl(wsl_exe=args.wsl_exe, distribution=distribution, python=python)
                checks["external"] = probe
                _validate_probe(probe, errors, phalp_repo=phalp_repo, linux=True, allow_cpu=args.allow_cpu)
            except Exception as exc:
                errors.append(str(exc))
    else:
        python = Path(args.external_python).expanduser().resolve()
        repo = Path(args.repo).expanduser().resolve()
        checks["transport"] = "windows"
        try:
            phalp_repo = resolve_phalp_repo(repo, args.phalp_repo)
        except RecoveryAuthorityError as exc:
            phalp_repo = (repo.parent / "PHALP").resolve()
            errors.append(str(exc))

        if not python.is_file():
            errors.append(f"external Python not found: {python}")
        if not (repo / "track.py").is_file():
            errors.append(f"not a 4D-Humans checkout: {repo}")
        if not (phalp_repo / "phalp").is_dir():
            errors.append(f"not a PHALP checkout: {phalp_repo}")

        if not errors:
            try:
                head = _repo_head(repo, "4D-Humans")
                checks["four_d_humans_head"] = head
                if head != FOUR_D_HUMANS_REVISION:
                    errors.append(f"4D-Humans HEAD mismatch: {head}")
                clean = _repo_clean(repo, "4D-Humans")
                checks["four_d_humans_tracked_clean"] = clean
                if not clean:
                    errors.append("4D-Humans has modified tracked files")
            except Exception as exc:
                errors.append(str(exc))

            try:
                phalp_head = _repo_head(phalp_repo, "PHALP")
                checks["phalp_head"] = phalp_head
                if phalp_head != PHALP_REVISION:
                    errors.append(f"PHALP HEAD mismatch: {phalp_head}")
                phalp_clean = _repo_clean(phalp_repo, "PHALP")
                checks["phalp_tracked_clean"] = phalp_clean
                if not phalp_clean:
                    errors.append("PHALP has modified tracked files")
            except Exception as exc:
                errors.append(str(exc))

            smpl = repo / "data" / SMPL_FILENAME
            checks["smpl_present"] = smpl.is_file()
            if not smpl.is_file():
                errors.append(f"required SMPL model missing: data/{SMPL_FILENAME}")

            try:
                probe = _external_probe(python)
                checks["external"] = probe
                _validate_probe(probe, errors, phalp_repo=phalp_repo, linux=False, allow_cpu=args.allow_cpu)
            except Exception as exc:
                errors.append(str(exc))

    checks["ok"] = not errors
    checks["errors"] = errors
    if args.out:
        output = Path(args.out).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(checks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    external = checks.get("external", {})
    device = external.get("cuda_device") if isinstance(external, dict) else None
    transport = checks.get("transport", "external")
    print(f"BodyRig recovery preflight: OK | {transport}{f' | CUDA: {device}' if device else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())