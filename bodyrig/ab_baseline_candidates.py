from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


FORMAT = "bodyrig-ab-baseline-candidate-contract"
VERSION = 1
CONTRACT_RELATIVE_PATH = Path("contracts/ab-baseline-candidates-v1.json")
EXPECTED_CANDIDATES = {"pbr_v2", "recovery_throughput_v3"}
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_REF_RE = re.compile(r"^candidate/[A-Za-z0-9._/-]+$")
_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class AbBaselineCandidateError(ValueError):
    pass


def _git(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AbBaselineCandidateError(f"Git authority check failed: {' '.join(args)}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        suffix = f": {detail}" if detail else ""
        raise AbBaselineCandidateError(f"Git authority check failed: {' '.join(args)}{suffix}")
    return completed.stdout.strip()


def _revision(value: object, label: str) -> str:
    text = str(value or "").strip().lower()
    if _SHA40_RE.fullmatch(text) is None:
        raise AbBaselineCandidateError(f"{label} is not an exact Git revision")
    return text


def _safe_ref(value: object, label: str) -> str:
    text = str(value or "").strip()
    if (
        _REF_RE.fullmatch(text) is None
        or ".." in text
        or "//" in text
        or text.endswith("/")
        or text.startswith("-")
        or "@{" in text
    ):
        raise AbBaselineCandidateError(f"{label} is not a safe candidate branch ref")
    return text


def _safe_path(value: object, label: str) -> str:
    text = str(value or "").strip()
    parts = text.split("/")
    if (
        _PATH_RE.fullmatch(text) is None
        or text.startswith("/")
        or text.startswith("-")
        or "\\" in text
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise AbBaselineCandidateError(f"{label} is not a canonical repository path")
    return text


def _load_contract(repo_root: Path) -> tuple[dict[str, Any], str]:
    path = repo_root / CONTRACT_RELATIVE_PATH
    if not path.is_file():
        raise AbBaselineCandidateError(f"A/B candidate contract is missing: {CONTRACT_RELATIVE_PATH.as_posix()}")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AbBaselineCandidateError("A/B candidate contract is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise AbBaselineCandidateError("A/B candidate contract must be a JSON object")
    return value, hashlib.sha256(raw).hexdigest()


def _validate_contract(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise AbBaselineCandidateError("A/B candidate contract format/version mismatch")
    if value.get("comparison_only") is not True:
        raise AbBaselineCandidateError("A/B candidate contract must remain comparison-only")
    if value.get("human_visual_authority_required") is not True:
        raise AbBaselineCandidateError("A/B candidate contract must require human visual authority")
    if value.get("physical_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise AbBaselineCandidateError("A/B candidate contract cannot grant physical or production authority")

    candidates = value.get("candidates")
    if not isinstance(candidates, dict) or set(candidates) != EXPECTED_CANDIDATES:
        raise AbBaselineCandidateError("A/B candidate contract must contain exactly the PBR v2 and throughput v3 candidates")

    normalized: dict[str, dict[str, Any]] = {}
    for name in sorted(EXPECTED_CANDIDATES):
        candidate = candidates.get(name)
        if not isinstance(candidate, dict) or set(candidate) != {"ref", "files"}:
            raise AbBaselineCandidateError(f"candidate {name} has unexpected fields")
        ref = _safe_ref(candidate.get("ref"), f"candidate {name} ref")
        files = candidate.get("files")
        if not isinstance(files, dict) or not files:
            raise AbBaselineCandidateError(f"candidate {name} must bind at least one file")
        file_map: dict[str, str] = {}
        for raw_path, raw_sha in files.items():
            path = _safe_path(raw_path, f"candidate {name} file")
            sha = _revision(raw_sha, f"candidate {name} blob for {path}")
            file_map[path] = sha
        normalized[name] = {"ref": ref, "files": file_map}
    return normalized


def _fetch_authority_refs(repo_root: Path, candidates: dict[str, dict[str, Any]]) -> None:
    refspecs = ["+refs/heads/main:refs/remotes/origin/main"]
    for candidate in candidates.values():
        ref = str(candidate["ref"])
        refspecs.append(f"+refs/heads/{ref}:refs/remotes/origin/{ref}")
    _git(repo_root, "fetch", "--no-tags", "origin", *refspecs)


def _tree_blob(repo_root: Path, revision: str, path: str) -> str:
    raw = _git(repo_root, "ls-tree", revision, "--", path)
    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) != 1 or "\t" not in lines[0]:
        raise AbBaselineCandidateError(f"candidate tree does not contain exactly one reviewed blob for {path}")
    metadata, actual_path = lines[0].split("\t", 1)
    parts = metadata.split()
    if len(parts) != 3 or parts[0] != "100644" or parts[1] != "blob" or actual_path != path:
        raise AbBaselineCandidateError(f"candidate tree entry is not the canonical regular-file blob for {path}")
    return _revision(parts[2], f"candidate blob for {path}")


def inspect_candidate_authority(
    *,
    repo_root: str | Path,
    expected_main_revision: str | None = None,
    expected_pbr_revision: str | None = None,
    expected_throughput_revision: str | None = None,
) -> dict[str, Any]:
    repo = Path(repo_root).expanduser().resolve()
    if not repo.is_dir():
        raise AbBaselineCandidateError("BodyRig repository root does not exist")

    contract, contract_sha256 = _load_contract(repo)
    candidates = _validate_contract(contract)

    branch = _git(repo, "branch", "--show-current").strip()
    if branch != "main":
        raise AbBaselineCandidateError("dual-candidate A/B baseline must be launched from branch main")
    if _git(repo, "status", "--porcelain"):
        raise AbBaselineCandidateError("BodyRig checkout is dirty; dual-candidate baseline requires exact clean main")

    _fetch_authority_refs(repo, candidates)

    main_revision = _revision(_git(repo, "rev-parse", "HEAD"), "BodyRig HEAD")
    origin_main = _revision(_git(repo, "rev-parse", "refs/remotes/origin/main"), "origin/main")
    if main_revision != origin_main:
        raise AbBaselineCandidateError(
            f"local main is not exact current origin/main: local={main_revision}, origin={origin_main}"
        )
    if expected_main_revision is not None and main_revision != _revision(expected_main_revision, "expected main revision"):
        raise AbBaselineCandidateError("main revision moved after the A/B baseline preflight")

    expected_revisions = {
        "pbr_v2": expected_pbr_revision,
        "recovery_throughput_v3": expected_throughput_revision,
    }
    resolved: dict[str, Any] = {}
    for name in sorted(EXPECTED_CANDIDATES):
        candidate = candidates[name]
        ref = str(candidate["ref"])
        remote_ref = f"refs/remotes/origin/{ref}"
        revision = _revision(_git(repo, "rev-parse", remote_ref), f"candidate {name} revision")
        expected = expected_revisions[name]
        if expected is not None and revision != _revision(expected, f"expected {name} revision"):
            raise AbBaselineCandidateError(f"candidate {name} ref moved after the A/B baseline preflight")

        ahead = int(_git(repo, "rev-list", "--count", f"{main_revision}..{revision}"))
        behind = int(_git(repo, "rev-list", "--count", f"{revision}..{main_revision}"))
        merge_base = _revision(_git(repo, "merge-base", main_revision, revision), f"candidate {name} merge base")
        if ahead != 1 or behind != 0 or merge_base != main_revision:
            raise AbBaselineCandidateError(
                f"candidate {name} must be exactly one commit ahead / zero behind current main"
            )

        changed = sorted(
            line.strip()
            for line in _git(repo, "diff", "--name-only", "--no-renames", main_revision, revision, "--").splitlines()
            if line.strip()
        )
        expected_files = sorted(candidate["files"])
        if changed != expected_files:
            raise AbBaselineCandidateError(f"candidate {name} changed-file set differs from the reviewed byte contract")

        verified_blobs: dict[str, str] = {}
        for path in expected_files:
            actual_blob = _tree_blob(repo, revision, path)
            expected_blob = str(candidate["files"][path])
            if actual_blob != expected_blob:
                raise AbBaselineCandidateError(f"candidate {name} blob drifted for {path}")
            verified_blobs[path] = actual_blob

        resolved[name] = {
            "ref": ref,
            "revision": revision,
            "ahead": ahead,
            "behind": behind,
            "files": verified_blobs,
        }

    return {
        "format": "bodyrig-ab-baseline-candidate-authority",
        "version": 1,
        "main_revision": main_revision,
        "contract_path": CONTRACT_RELATIVE_PATH.as_posix(),
        "contract_sha256": contract_sha256,
        "candidates": resolved,
        "comparison_only": True,
        "human_visual_authority_required": True,
        "physical_acceptance_authority": False,
        "production_activation": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate exact dual-candidate authority before a retained A/B baseline")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--expected-main-revision")
    parser.add_argument("--expected-pbr-revision")
    parser.add_argument("--expected-throughput-revision")
    args = parser.parse_args(argv)
    try:
        result = inspect_candidate_authority(
            repo_root=args.repo_root,
            expected_main_revision=args.expected_main_revision,
            expected_pbr_revision=args.expected_pbr_revision,
            expected_throughput_revision=args.expected_throughput_revision,
        )
    except AbBaselineCandidateError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
