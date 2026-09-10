#!/usr/bin/env python
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(_PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_PARENT))

from bodyrig.bridges import hmr2_4dhumans_bridge as base  # noqa: E402
from bodyrig.bridges.hmr2_config import ADAPTER_NAME, ADAPTER_REVISION  # noqa: E402
from bodyrig.bridges.phalp_target_isolation import canonicalize_target_isolation  # noqa: E402

FORMAT = "bodyrig-phalp-target-isolation-result"
VERSION = 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_isolation(repo: Path, source: Path, selected_track_id: str, loader_env: dict[str, str]) -> dict:
    try:
        import joblib
    except ImportError as exc:
        raise RuntimeError("joblib is required in the 4D-Humans environment") from exc

    with tempfile.TemporaryDirectory(prefix="bodyrig-phalp-isolation-") as temp_dir_raw:
        output_dir = Path(temp_dir_raw) / "output"
        command = base._track_command(repo, source, output_dir)  # noqa: SLF001
        completed = subprocess.run(
            command,
            cwd=repo,
            env=loader_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.stdout:
            print(completed.stdout[-12000:], file=sys.stderr)
        if completed.returncode != 0:
            raise RuntimeError(f"4D-Humans target isolation tracking failed with exit code {completed.returncode}")
        pkls = sorted((output_dir / "results").glob("*.pkl"))
        if len(pkls) != 1:
            raise RuntimeError(f"expected exactly one PHALP result pickle, found {len(pkls)}")
        frame_results = joblib.load(pkls[0])
        if not isinstance(frame_results, dict):
            raise RuntimeError("unexpected PHALP target isolation result shape")
        return canonicalize_target_isolation(
            frame_results,
            fps=base._video_fps(source),  # noqa: SLF001
            source_index=0,
            selected_track_id=selected_track_id,
        )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Reproduce a human-attested PHALP track and emit review-only target-isolation trajectory evidence."
    )
    parser.add_argument("--repo", required=True, help="Pinned shubham-goel/4D-Humans checkout")
    parser.add_argument("--phalp-repo", required=True, help="Exact pinned PHALP checkout authority")
    parser.add_argument("--track-id", required=True, help="Exact source-local PHALP track selected by human attestation")
    args = parser.parse_args()
    try:
        repo = Path(args.repo).expanduser().resolve()
        phalp_repo = Path(args.phalp_repo).expanduser().resolve()
        base._verify_repo(repo)  # noqa: SLF001
        base._verify_phalp_install(phalp_repo)  # noqa: SLF001
        base._verify_nmr_install()  # noqa: SLF001
        loader_env = base._recovery_loader_env()  # noqa: SLF001
        base._verify_cuda_loader_env(loader_env)  # noqa: SLF001
        base._ensure_phalp_smpl_cache(repo)  # noqa: SLF001
        sources = base._read_request()  # noqa: SLF001
        if len(sources) != 1:
            raise RuntimeError("target isolation requires exactly one human-attested source")
        source = sources[0]
        isolation = _run_isolation(repo, source, str(args.track_id), loader_env)
        payload = {
            "format": FORMAT,
            "version": VERSION,
            "adapter": ADAPTER_NAME,
            "revision": ADAPTER_REVISION,
            "source_media_sha256": _sha256_file(source),
            "isolation": isolation,
            "source_paths_exported": False,
            "appearance_embeddings_exported": False,
            "machine_identity_selection": False,
            "biometric_identity_inference_used": False,
            "generic_guessing_permitted": False,
            "target_isolated_source_authority": False,
            "photoidentity_source_evidence_authority": False,
            "reconstruction_permitted": False,
            "production_activation": False,
        }
        json.dump(payload, sys.stdout, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        print(f"BodyRig PHALP target isolation bridge: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
