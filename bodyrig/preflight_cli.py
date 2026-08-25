from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .bridges.hmr2_config import (
    FOUR_D_HUMANS_REVISION,
    PHALP_REVISION,
    PHALP_TRACKER_BLOB_SHA1,
)
from .recovery_authority import RecoveryAuthorityError, resolve_phalp_repo

SMPL_FILENAME = "basicModel_neutral_lbs_10_207_0_v1.0.0.pkl"


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


def _external_probe(python: Path) -> dict:
    script = f'''\
import hashlib, importlib.util, json, pathlib, sys
EXPECTED = {PHALP_TRACKER_BLOB_SHA1!r}
def blob(data):
    return hashlib.sha1(("blob %d\\0" % len(data)).encode("ascii") + data).hexdigest()
result = {{"python": sys.version.split()[0]}}
for name in ("torch", "cv2", "joblib", "hmr2", "phalp"):
    try:
        __import__(name)
        result["import_" + name] = True
    except Exception as exc:
        result["import_" + name] = False
        result["error_" + name] = type(exc).__name__ + ": " + str(exc)
try:
    import torch
    result["cuda_available"] = bool(torch.cuda.is_available())
    result["cuda_device"] = torch.cuda.get_device_name(0) if result["cuda_available"] else None
except Exception:
    result["cuda_available"] = False
    result["cuda_device"] = None
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
    completed = _run([str(python), "-c", script])
    if completed.returncode != 0:
        raise RuntimeError(f"external Python probe failed: {completed.stderr.strip()[-2000:]}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("external Python probe returned invalid JSON") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the external 4D-Humans recovery environment for BodyRig.")
    parser.add_argument("--python", required=True, dest="external_python")
    parser.add_argument("--repo", required=True, help="Pinned 4D-Humans checkout")
    parser.add_argument(
        "--phalp-repo",
        default="",
        help="Pinned PHALP checkout. If omitted in a ready-rig run, resolve it from BODYRIG_RIG_SETUP_REPORT.",
    )
    parser.add_argument("--allow-cpu", action="store_true", help="Do not fail when CUDA is unavailable")
    parser.add_argument("--out", help="Optional JSON report path")
    args = parser.parse_args(argv)

    python = Path(args.external_python).expanduser().resolve()
    repo = Path(args.repo).expanduser().resolve()
    errors: list[str] = []
    try:
        phalp_repo = resolve_phalp_repo(repo, args.phalp_repo)
    except RecoveryAuthorityError as exc:
        phalp_repo = (repo.parent / "PHALP").resolve()
        errors.append(str(exc))

    checks: dict[str, object] = {
        "format": "bodyrig-recovery-preflight",
        "version": 1,
        "four_d_humans_expected": FOUR_D_HUMANS_REVISION,
        "phalp_expected": PHALP_REVISION,
        "phalp_tracker_expected_blob": PHALP_TRACKER_BLOB_SHA1,
    }

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
            for name in ("torch", "cv2", "joblib", "hmr2", "phalp"):
                if probe.get("import_" + name) is not True:
                    errors.append(f"external import failed: {name}: {probe.get('error_' + name, 'unknown error')}")
            imported_root = probe.get("phalp_root")
            if not isinstance(imported_root, str) or not imported_root.strip():
                errors.append("external PHALP import did not expose a package root")
            elif not _same_path(Path(imported_root), phalp_repo / "phalp"):
                errors.append(f"external PHALP import is not sourced from the pinned checkout: {imported_root}")
            if probe.get("phalp_tracker_match") is not True:
                errors.append("installed PHALP tracker source does not match pinned BodyRig blob")
            if not args.allow_cpu and probe.get("cuda_available") is not True:
                errors.append("CUDA is not available in the external recovery Python")
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
    print(f"BodyRig recovery preflight: OK{f' | CUDA: {device}' if device else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
