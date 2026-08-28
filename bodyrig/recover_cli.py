from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .bridges.hmr2_config import ADAPTER_NAME, ADAPTER_REVISION, bridge_script_path
from .recovery import (
    BodyprintExtractor,
    JsonCommandRecoveryAdapter,
    RecoveredTrack,
    RecoveryError,
    RecoveryResult,
    parse_recovery_result,
)
from .recovery_authority import RecoveryAuthorityError, resolve_phalp_repo
from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter


def _select_track(result: RecoveryResult, requested: str | None) -> RecoveredTrack:
    if requested is not None:
        for track in result.tracks:
            if track.track_id == requested:
                return track
        available = ", ".join(track.track_id for track in result.tracks)
        raise ValueError(f"track {requested!r} not found; available: {available}")
    if len(result.tracks) == 1:
        return result.tracks[0]
    candidates = ", ".join(
        f"{track.track_id} ({len(track.frames)} frames)" for track in result.tracks
    )
    raise ValueError(
        "multiple people/tracks detected; rerun with --track-id. "
        f"Candidates: {candidates}"
    )


def _recover_wsl(
    *,
    sources: list[Path],
    external_python: str,
    repo: str,
    phalp_repo: str,
    distribution: str,
    wsl_exe: str,
) -> RecoveryResult:
    for label, value in (
        ("external Python", external_python),
        ("4D-Humans repo", repo),
        ("PHALP repo", phalp_repo),
    ):
        if not value.startswith("/"):
            raise RecoveryError(f"WSL {label} must be an absolute Linux path: {value}")
    if not phalp_repo:
        raise RecoveryError("WSL recovery requires --phalp-repo explicitly")

    try:
        converter = make_wsl_path_converter(wsl_exe, distribution)
        bridge = converter(str(bridge_script_path()))
        translated_sources = [converter(str(path)) for path in sources]
    except (OSError, WslBridgeError) as exc:
        raise RecoveryError(f"could not translate recovery paths into WSL: {exc}") from exc

    request = {
        "format": "bodyrig-recovery-request",
        "version": 1,
        "sources": translated_sources,
    }
    command = [
        wsl_exe,
        "-d",
        distribution,
        "--",
        external_python,
        bridge,
        "--repo",
        repo,
        "--phalp-repo",
        phalp_repo,
    ]
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(request),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RecoveryError("WSL recovery adapter failed to execute") from exc
    if completed.returncode != 0:
        raise RecoveryError(
            f"WSL recovery adapter exited {completed.returncode}: {completed.stderr.strip()[-2000:]}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RecoveryError("WSL recovery adapter returned invalid JSON") from exc
    result = parse_recovery_result(payload, expected_adapter=ADAPTER_NAME)
    if result.revision != ADAPTER_REVISION:
        raise RecoveryError("recovery adapter revision mismatch")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run pinned 4D-Humans recovery and emit a BodyRig bodyprint proof."
    )
    parser.add_argument("sources", nargs="+", help="1–10 local video clips")
    parser.add_argument("--python", required=True, dest="external_python", help="Python executable in the 4D-Humans environment")
    parser.add_argument("--repo", required=True, help="Pinned 4D-Humans checkout")
    parser.add_argument(
        "--phalp-repo",
        default="",
        help="Pinned PHALP checkout. WSL recovery requires this explicitly.",
    )
    parser.add_argument("--distribution", default="", help="Optional WSL distribution containing the recovery runtime")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--track-id", help="PHALP track to use when multiple people are present")
    parser.add_argument("--out", required=True, help="Output JSON proof path")
    args = parser.parse_args(argv)

    if not 1 <= len(args.sources) <= 10:
        parser.error("BodyRig V1 accepts 1..10 source clips")
    sources = [Path(item).expanduser().resolve() for item in args.sources]
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        print(f"BodyRig recovery: missing source(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    distribution = args.distribution.strip()
    try:
        if distribution:
            recovery = _recover_wsl(
                sources=sources,
                external_python=args.external_python.strip(),
                repo=args.repo.strip().rstrip("/"),
                phalp_repo=args.phalp_repo.strip().rstrip("/"),
                distribution=distribution,
                wsl_exe=args.wsl_exe,
            )
        else:
            four_d_repo = Path(args.repo).expanduser().resolve()
            try:
                phalp_repo = resolve_phalp_repo(four_d_repo, args.phalp_repo)
            except RecoveryAuthorityError as exc:
                print(f"BodyRig recovery: {exc}", file=sys.stderr)
                return 1
            if not phalp_repo.is_dir():
                print(f"BodyRig recovery: PHALP checkout not found: {phalp_repo}", file=sys.stderr)
                return 2

            adapter = JsonCommandRecoveryAdapter(
                [
                    str(Path(args.external_python).expanduser().resolve()),
                    str(bridge_script_path()),
                    "--repo",
                    str(four_d_repo),
                    "--phalp-repo",
                    str(phalp_repo),
                ],
                name=ADAPTER_NAME,
                revision=ADAPTER_REVISION,
            )
            recovery = adapter.recover(sources)
        track = _select_track(recovery, args.track_id)
        bodyprint = BodyprintExtractor().extract(track)
    except Exception as exc:
        print(f"BodyRig recovery: {exc}", file=sys.stderr)
        return 1

    proof = {
        "format": "bodyrig-recovery-proof",
        "version": 1,
        "source_count": len(sources),
        "adapter": recovery.adapter,
        "revision": recovery.revision,
        "track_id": track.track_id,
        "observed_frames": len(track.frames),
        "bodyprint": bodyprint,
    }
    output = Path(args.out).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
