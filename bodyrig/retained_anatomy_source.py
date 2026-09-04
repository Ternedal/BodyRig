from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from .sith_reconstruct import SithReconstructError, validate_fit_params
from .sith_reconstruction_authority import (
    AUTHORITY_FILENAME,
    AUTHORITY_FORMAT,
    AUTHORITY_VERSION,
    SMPLX_FIT_PROFILE,
    SMPLX_GENDERS,
)

FORMAT = "bodyrig-retained-anatomy-source"
VERSION = 1
RECON_FORMAT = "bodyrig-sith-reconstruction"
RECON_VERSION = 1
RECEIPT_FILENAME = "retained-anatomy-source.json"
SHA256_LENGTH = 64
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class RetainedAnatomySourceError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RetainedAnatomySourceError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise RetainedAnatomySourceError(f"{label} must be an object")
    return value


def _expected_sha256(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != SHA256_LENGTH
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise RetainedAnatomySourceError(f"retained anatomy reconstruction {field} is invalid")
    return value


def _safe_leaf(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise RetainedAnatomySourceError(f"{label} is invalid")
    name = value.strip()
    if (
        not name
        or name in {".", ".."}
        or Path(name).name != name
        or "/" in name
        or "\\" in name
    ):
        raise RetainedAnatomySourceError(f"{label} must be a safe leaf filename")
    return name


def _read_text(path: Path, *, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise RetainedAnatomySourceError(f"{label} is not valid UTF-8 text") from exc


def _copy_exact(source: Path, destination: Path, *, expected_sha256: str) -> None:
    if not source.is_file():
        raise RetainedAnatomySourceError(f"retained anatomy source artifact is missing: {source.name}")
    if _sha256(source) != expected_sha256:
        raise RetainedAnatomySourceError(f"retained anatomy source hash mismatch: {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if _sha256(destination) != expected_sha256:
        raise RetainedAnatomySourceError(f"retained anatomy copy hash mismatch: {source.name}")


def _write_json_create_only(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise RetainedAnatomySourceError(f"retained anatomy receipt already exists: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _model_family_authority(stage: Path, *, reconstruction_sha256: str) -> tuple[dict[str, Any], Path]:
    path = stage / AUTHORITY_FILENAME
    if not path.is_file():
        raise RetainedAnatomySourceError("SiTH reconstruction model-family authority is missing")
    value = _load_json(path, label="SiTH reconstruction model-family authority")
    required = {
        "format",
        "version",
        "body_model_gender",
        "smplx_fit_profile",
        "reconstruction_sha256",
    }
    if set(value) != required:
        raise RetainedAnatomySourceError("SiTH reconstruction model-family authority fields do not match v1")
    if value.get("format") != AUTHORITY_FORMAT or value.get("version") != AUTHORITY_VERSION:
        raise RetainedAnatomySourceError("SiTH reconstruction model-family authority format/version mismatch")
    gender = str(value.get("body_model_gender") or "").strip().lower()
    if gender not in SMPLX_GENDERS:
        raise RetainedAnatomySourceError("SiTH reconstruction body-model gender is invalid")
    if value.get("smplx_fit_profile") != SMPLX_FIT_PROFILE:
        raise RetainedAnatomySourceError("SiTH reconstruction SMPL-X fit profile mismatch")
    if value.get("reconstruction_sha256") != reconstruction_sha256:
        raise RetainedAnatomySourceError("SiTH reconstruction model-family authority does not bind current reconstruction")
    return value, path


def publish_retained_anatomy_source(
    source_workspace: str | Path,
    output_workspace: str | Path,
) -> dict[str, Any]:
    """Publish the minimal SiTH/SMPL-X subset needed by later component gates.

    The successful clone may delete the full private identity workspace after this
    returns. Raw observations, prepared-input frames/keypoints and the hallucinated
    back view are intentionally not copied. The tiny model-family receipt is kept
    because exact female/male/neutral SMPL-X authority is required to reproduce
    later inverse-LBS component review geometry without guessing.
    """

    source_workspace = Path(source_workspace).expanduser().resolve()
    output_workspace = Path(output_workspace).expanduser().resolve()
    if not source_workspace.is_dir():
        raise RetainedAnatomySourceError("private identity workspace is missing")
    if output_workspace.exists():
        raise RetainedAnatomySourceError(
            f"retained anatomy workspace already exists; refusing overwrite: {output_workspace}"
        )
    if output_workspace == source_workspace or source_workspace in output_workspace.parents:
        raise RetainedAnatomySourceError(
            "retained anatomy workspace must live outside the private identity workspace"
        )

    stage = source_workspace / "sith-input-v1"
    reconstruction_path = stage / "reconstruction.json"
    if not reconstruction_path.is_file():
        raise RetainedAnatomySourceError("SiTH reconstruction evidence is missing")
    reconstruction = _load_json(reconstruction_path, label="SiTH reconstruction evidence")
    required = {
        "format",
        "version",
        "prepared_input_sha256",
        "subject_track_id",
        "sith_revision",
        "diffusion_model_sha256",
        "diffusion_model_file_count",
        "diffusion_model_byte_count",
        "seed",
        "hallucination",
        "reconstruction",
    }
    if set(reconstruction) != required:
        raise RetainedAnatomySourceError("SiTH reconstruction evidence fields do not match v1")
    if reconstruction["format"] != RECON_FORMAT or reconstruction["version"] != RECON_VERSION:
        raise RetainedAnatomySourceError("SiTH reconstruction evidence format/version mismatch")

    reconstruction_sha = _sha256(reconstruction_path)
    model_authority, model_authority_path = _model_family_authority(
        stage,
        reconstruction_sha256=reconstruction_sha,
    )
    details = reconstruction["reconstruction"]
    if not isinstance(details, dict):
        raise RetainedAnatomySourceError("SiTH reconstruction detail block is missing")
    if details.get("grid_size") != 300 or details.get("save_uv") is not True:
        raise RetainedAnatomySourceError("SiTH reconstruction is not the pinned UV profile")

    texture_name = _safe_leaf(details.get("mesh_texture_name"), label="SiTH reconstruction texture reference")
    relative_sources = {
        "sith-input-v1/reconstruction.json": reconstruction_path,
        f"sith-input-v1/{AUTHORITY_FILENAME}": model_authority_path,
        "sith-input-v1/smplx/000_smplx.obj": stage / "smplx" / "000_smplx.obj",
        "sith-input-v1/smplx/000_fit.json": stage / "smplx" / "000_fit.json",
        "sith-input-v1/meshes/000_reco.obj": stage / "meshes" / "000_reco.obj",
        "sith-input-v1/meshes/000.mtl": stage / "meshes" / "000.mtl",
        f"sith-input-v1/meshes/{texture_name}": stage / "meshes" / texture_name,
    }
    expected_hashes = {
        "sith-input-v1/reconstruction.json": reconstruction_sha,
        f"sith-input-v1/{AUTHORITY_FILENAME}": _sha256(model_authority_path),
        "sith-input-v1/smplx/000_smplx.obj": _expected_sha256(
            details.get("smplx_obj_sha256"), field="smplx_obj_sha256"
        ),
        "sith-input-v1/smplx/000_fit.json": _expected_sha256(
            details.get("fit_params_sha256"), field="fit_params_sha256"
        ),
        "sith-input-v1/meshes/000_reco.obj": _expected_sha256(
            details.get("mesh_obj_sha256"), field="mesh_obj_sha256"
        ),
        "sith-input-v1/meshes/000.mtl": _expected_sha256(
            details.get("mesh_mtl_sha256"), field="mesh_mtl_sha256"
        ),
        f"sith-input-v1/meshes/{texture_name}": _expected_sha256(
            details.get("mesh_texture_sha256"), field="mesh_texture_sha256"
        ),
    }

    for relative, source in relative_sources.items():
        if not source.is_file():
            raise RetainedAnatomySourceError(f"retained anatomy source artifact is missing: {relative}")
        if _sha256(source) != expected_hashes[relative]:
            raise RetainedAnatomySourceError(f"retained anatomy source hash mismatch: {relative}")

    smplx_obj = relative_sources["sith-input-v1/smplx/000_smplx.obj"]
    if smplx_obj.stat().st_size < 64:
        raise RetainedAnatomySourceError("retained fitted SMPL-X OBJ is implausibly small")
    try:
        validate_fit_params(relative_sources["sith-input-v1/smplx/000_fit.json"])
    except SithReconstructError as exc:
        raise RetainedAnatomySourceError(f"retained SMPL-X fit params are invalid: {exc}") from exc

    mesh_text = _read_text(
        relative_sources["sith-input-v1/meshes/000_reco.obj"],
        label="retained reconstruction OBJ",
    )
    mtllib = [line.split(maxsplit=1)[1].strip() for line in mesh_text.splitlines() if line.startswith("mtllib ")]
    if mtllib != ["000.mtl"]:
        raise RetainedAnatomySourceError("retained reconstruction OBJ must reference exactly 000.mtl")
    material_text = _read_text(
        relative_sources["sith-input-v1/meshes/000.mtl"],
        label="retained reconstruction MTL",
    )
    texture_refs = [line.split(maxsplit=1)[1].strip() for line in material_text.splitlines() if line.startswith("map_Kd ")]
    if texture_refs != [texture_name]:
        raise RetainedAnatomySourceError("retained reconstruction MTL texture reference mismatch")
    texture = relative_sources[f"sith-input-v1/meshes/{texture_name}"]
    if texture.read_bytes()[:8] != PNG_SIGNATURE:
        raise RetainedAnatomySourceError("retained reconstruction texture is not a PNG")

    source_hashes_before = {relative: _sha256(path) for relative, path in relative_sources.items()}
    created = False
    try:
        output_workspace.mkdir(parents=True, exist_ok=False)
        created = True
        for relative, source in relative_sources.items():
            _copy_exact(
                source,
                output_workspace / Path(relative),
                expected_sha256=expected_hashes[relative],
            )

        source_hashes_after = {relative: _sha256(path) for relative, path in relative_sources.items()}
        if source_hashes_after != source_hashes_before:
            raise RetainedAnatomySourceError(
                "private reconstruction bytes changed while publishing retained anatomy source"
            )

        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "source_reconstruction_sha256": expected_hashes["sith-input-v1/reconstruction.json"],
            "reconstruction_authority_sha256": expected_hashes[f"sith-input-v1/{AUTHORITY_FILENAME}"],
            "body_model_gender": model_authority["body_model_gender"],
            "smplx_fit_profile": model_authority["smplx_fit_profile"],
            "files": dict(sorted(expected_hashes.items())),
            "raw_observation_media_retained": False,
            "prepared_input_retained": False,
            "back_view_retained": False,
            "reconstruction_rerun": False,
            "comparison_only": True,
            "human_review_required": True,
            "production_activation": False,
        }
        receipt_path = output_workspace / RECEIPT_FILENAME
        _write_json_create_only(receipt_path, receipt)

        expected_files = set(expected_hashes) | {RECEIPT_FILENAME}
        actual_files = {
            path.relative_to(output_workspace).as_posix()
            for path in output_workspace.rglob("*")
            if path.is_file()
        }
        if actual_files != expected_files:
            raise RetainedAnatomySourceError(
                "retained anatomy workspace contains files outside the privacy-minimized contract"
            )
        for relative, expected in expected_hashes.items():
            if _sha256(output_workspace / Path(relative)) != expected:
                raise RetainedAnatomySourceError(
                    f"retained anatomy workspace post-publication hash mismatch: {relative}"
                )
        if _sha256(reconstruction_path) != expected_hashes["sith-input-v1/reconstruction.json"]:
            raise RetainedAnatomySourceError(
                "private reconstruction evidence changed after retained anatomy publication"
            )
        if _sha256(model_authority_path) != expected_hashes[f"sith-input-v1/{AUTHORITY_FILENAME}"]:
            raise RetainedAnatomySourceError(
                "private reconstruction model-family authority changed after retained anatomy publication"
            )
        return receipt
    except Exception:
        if created:
            shutil.rmtree(output_workspace, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish only the reconstruction bytes required by later BodyRig component gates."
    )
    parser.add_argument("--source-workspace", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = publish_retained_anatomy_source(args.source_workspace, args.out)
    except (OSError, ValueError, RetainedAnatomySourceError) as exc:
        print(f"BodyRig retained anatomy source: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "workspace": str(Path(args.out).expanduser().resolve()),
                "receipt": str(Path(args.out).expanduser().resolve() / RECEIPT_FILENAME),
                "reconstruction_sha256": receipt["source_reconstruction_sha256"],
                "body_model_gender": receipt["body_model_gender"],
                "production_activation": False,
            },
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
