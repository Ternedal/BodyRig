from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from statistics import median

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

_SOURCE_TRACK_RE = re.compile(r"^s(\d{2})-t")


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


def _track_rank(track: RecoveredTrack) -> tuple[float, int, float, str]:
    confidence_mass = sum(frame.confidence for frame in track.frames)
    average_confidence = confidence_mass / len(track.frames)
    # sort() uses ascending order below; negatives make stronger evidence win.
    return (-confidence_mass, -len(track.frames), -average_confidence, track.track_id)


def _select_tracks(
    result: RecoveryResult,
    requested: str | None,
    *,
    source_count: int,
) -> tuple[RecoveredTrack, ...]:
    """Select recovery evidence without pretending track ids span source clips.

    PHALP ids are source-local (`s00-t...`, `s01-t...`). A production recovery
    over several independently selected observation segments therefore cannot
    be represented by one global PHALP track id. When the operator has not
    requested a diagnostic track explicitly, select the strongest observed
    person track independently for each source and let bodyprint aggregation
    happen across those source-local tracks.
    """

    if requested is not None:
        return (_select_track(result, requested),)
    if len(result.tracks) == 1:
        return (result.tracks[0],)
    if not 1 <= source_count <= 10:
        raise ValueError("source_count must be 1..10")

    grouped: dict[int, list[RecoveredTrack]] = {}
    for track in result.tracks:
        match = _SOURCE_TRACK_RE.match(track.track_id)
        if match is None:
            continue
        source_index = int(match.group(1))
        if 0 <= source_index < source_count:
            grouped.setdefault(source_index, []).append(track)

    if not grouped:
        # Preserve the legacy fail-closed behavior for adapters that do not
        # expose BodyRig's source-local PHALP id contract.
        return (_select_track(result, None),)

    selected: list[RecoveredTrack] = []
    for source_index in range(source_count):
        candidates = grouped.get(source_index)
        if not candidates:
            continue
        selected.append(sorted(candidates, key=_track_rank)[0])

    required_sources = 1 if source_count == 1 else min(3, source_count)
    if len(selected) < required_sources:
        raise ValueError(
            "recovery produced usable person tracks for too few source segments: "
            f"{len(selected)}/{source_count}; need at least {required_sources}"
        )
    return tuple(selected)


def _aggregate_bodyprints(tracks: tuple[RecoveredTrack, ...]) -> dict:
    if not tracks:
        raise RecoveryError("bodyprint aggregation requires at least one track")
    extractor = BodyprintExtractor()
    if len(tracks) == 1:
        return extractor.extract(tracks[0])

    bodyprints = [extractor.extract(track) for track in tracks]
    result: dict = {"format": "modelrig-bodyprint", "version": 1}
    for section in ("shape", "motion"):
        keys = sorted(
            {
                key
                for bodyprint in bodyprints
                for key in bodyprint.get(section, {})
            }
        )
        aggregate: dict[str, float] = {}
        for key in keys:
            values = [
                float(bodyprint[section][key])
                for bodyprint in bodyprints
                if key in bodyprint.get(section, {})
            ]
            if values:
                aggregate[key] = float(median(values))
        if aggregate:
            result[section] = aggregate
    if len(result) == 2:
        raise RecoveryError("selected tracks contain insufficient joints for a bodyprint")
    return result


def _proof_track_id(tracks: tuple[RecoveredTrack, ...]) -> str:
    if len(tracks) == 1:
        return tracks[0].track_id
    authority = ",".join(track.track_id for track in tracks).encode("utf-8")
    return "aggregate-" + hashlib.sha256(authority).hexdigest()[:24]


def _run_wsl_file_capture(command: list[str], request: dict) -> tuple[int, str, str]:
    """Run WSL without Python-managed stdio pipes.

    WSL descendants can inherit pipe handles beyond the lifetime of wsl.exe.
    `subprocess.run(..., PIPE)` then waits for EOF even after the process handle
    has signalled. Seekable temporary files keep process completion tied to the
    wsl.exe handle while preserving full stdout/stderr capture for proof/error
    handling.
    """

    request_bytes = json.dumps(request).encode("utf-8")
    with (
        tempfile.TemporaryFile(mode="w+b") as stdin_file,
        tempfile.TemporaryFile(mode="w+b") as stdout_file,
        tempfile.TemporaryFile(mode="w+b") as stderr_file,
    ):
        stdin_file.write(request_bytes)
        stdin_file.flush()
        stdin_file.seek(0)

        completed = subprocess.run(
            command,
            stdin=stdin_file,
            stdout=stdout_file,
            stderr=stderr_file,
            check=False,
        )

        stdout_file.flush()
        stderr_file.flush()
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode("utf-8", errors="replace")
        stderr = stderr_file.read().decode("utf-8", errors="replace")
        return completed.returncode, stdout, stderr


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
        # Recovery processes up to ten selected segments sequentially. Runtime is
        # hardware- and source-dependent, so do not impose an arbitrary wall-clock
        # deadline here. The operator/caller remains the cancellation authority.
        returncode, stdout, stderr = _run_wsl_file_capture(command, request)
    except OSError as exc:
        raise RecoveryError("WSL recovery adapter failed to execute") from exc
    if returncode != 0:
        raise RecoveryError(
            f"WSL recovery adapter exited {returncode}: {stderr.strip()[-2000:]}"
        )
    try:
        payload = json.loads(stdout)
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
        tracks = _select_tracks(recovery, args.track_id, source_count=len(sources))
        bodyprint = _aggregate_bodyprints(tracks)
        print(
            "BodyRig recovery track selection: "
            + ", ".join(f"{track.track_id} ({len(track.frames)} frames)" for track in tracks),
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"BodyRig recovery: {exc}", file=sys.stderr)
        return 1

    proof = {
        "format": "bodyrig-recovery-proof",
        "version": 1,
        "source_count": len(sources),
        "adapter": recovery.adapter,
        "revision": recovery.revision,
        "track_id": _proof_track_id(tracks),
        "observed_frames": sum(len(track.frames) for track in tracks),
        "bodyprint": bodyprint,
    }
    output = Path(args.out).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
