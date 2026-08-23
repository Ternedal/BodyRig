from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bridges.hmr2_config import ADAPTER_NAME, ADAPTER_REVISION, bridge_script_path
from .recovery import BodyprintExtractor, JsonCommandRecoveryAdapter, RecoveredTrack, RecoveryResult


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run pinned 4D-Humans recovery and emit a BodyRig bodyprint proof."
    )
    parser.add_argument("sources", nargs="+", help="1–10 local video clips")
    parser.add_argument("--python", required=True, dest="external_python", help="Python executable in the 4D-Humans environment")
    parser.add_argument("--repo", required=True, help="Pinned 4D-Humans checkout")
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

    adapter = JsonCommandRecoveryAdapter(
        [
            str(Path(args.external_python).expanduser().resolve()),
            str(bridge_script_path()),
            "--repo",
            str(Path(args.repo).expanduser().resolve()),
        ],
        name=ADAPTER_NAME,
        revision=ADAPTER_REVISION,
    )
    try:
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
