from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, BinaryIO

from .photoreal_spatial_metadata_probe import (
    PhotorealSpatialMetadataProbeError,
    _header,
    _walk,
)

FORMAT = "bodyrig-photoreal-spatial-probe-debug"
VERSION = 1


class _TracingStream:
    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self.last_io: dict[str, Any] | None = None

    def _position(self) -> int | None:
        try:
            return int(self._stream.tell())
        except (OSError, ValueError):
            return None

    def seek(self, offset: int, whence: int = 0) -> int:
        self.last_io = {
            "operation": "seek",
            "offset": int(offset),
            "whence": int(whence),
            "position_before": self._position(),
        }
        value = self._stream.seek(offset, whence)
        self.last_io["position_after"] = self._position()
        return int(value)

    def read(self, size: int = -1) -> bytes:
        self.last_io = {
            "operation": "read",
            "size": int(size),
            "position_before": self._position(),
        }
        value = self._stream.read(size)
        self.last_io["bytes_returned"] = len(value)
        self.last_io["position_after"] = self._position()
        return value

    def tell(self) -> int:
        return int(self._stream.tell())


def _probe_state() -> dict[str, Any]:
    return {
        "moov_present": False,
        "sample_entry_types": set(),
        "st3d_present": False,
        "st3d_version": None,
        "st3d_flags": None,
        "stereo_mode_code": None,
        "stereo_mode": None,
        "sv3d_present": False,
        "svhd_present": False,
        "svhd_metadata_source_present": False,
        "svhd_metadata_source_sha256": None,
        "proj_present": False,
        "prhd_present": False,
        "prhd_version": None,
        "prhd_flags": None,
        "projection_pose_yaw_degrees": None,
        "projection_pose_pitch_degrees": None,
        "projection_pose_roll_degrees": None,
        "projection_type": None,
        "projection_data_version": None,
        "projection_data_flags": None,
        "equirectangular_bounds_raw": None,
        "equirectangular_bounds_fraction": None,
        "equirectangular_bounds_valid": None,
        "cubemap_layout": None,
        "cubemap_layout_known": None,
        "cubemap_padding_pixels": None,
        "mesh_projection_crc32": None,
        "mesh_projection_crc32_computed": None,
        "mesh_projection_crc32_matches": None,
        "mesh_projection_encoding": None,
        "mesh_projection_encoding_supported": None,
        "mesh_projection_payload_bytes": None,
        "camm_sample_entry_present": False,
        "spherical_v1_present": False,
        "spherical_v1_xml_size_bytes": None,
        "spherical_v1_xml_sha256": None,
        "spherical_v1_xml_valid": False,
        "spherical_v1_spherical": None,
        "spherical_v1_stitched": None,
        "spherical_v1_projection_type": None,
        "spherical_v1_stereo_mode": None,
        "spherical_v1_parse_status": None,
    }


def _os_error(exc: OSError) -> dict[str, Any]:
    winerror = getattr(exc, "winerror", None)
    return {
        "type": type(exc).__name__,
        "errno": exc.errno,
        "winerror": winerror if isinstance(winerror, int) else None,
        "strerror": str(exc.strerror)[:512] if exc.strerror else None,
        "message": str(exc)[:512],
    }


def debug_isobmff_file(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "source": str(source),
        "status": "error",
        "stage": "stat",
        "size_bytes": None,
        "first_box_type": None,
        "moov_present": False,
        "last_io": None,
        "error": None,
    }

    try:
        size = source.stat().st_size
        result["size_bytes"] = int(size)
    except OSError as exc:
        result["error"] = _os_error(exc)
        return result

    if size < 8:
        result.update(status="not-isobmff", stage="header")
        return result

    try:
        result["stage"] = "open"
        with source.open("rb") as raw:
            stream = _TracingStream(raw)
            result["stage"] = "header"
            first_type, _, _, _ = _header(stream, 0, size)
            result["first_box_type"] = first_type
            result["stage"] = "walk"
            state = _probe_state()
            _walk(stream, 0, size, state)
            result["last_io"] = stream.last_io
            result["moov_present"] = state["moov_present"] is True
            if result["moov_present"] is not True:
                raise PhotorealSpatialMetadataProbeError("ISO BMFF file has no moov box")
            result.update(status="parsed-isobmff", stage="complete")
            return result
    except OSError as exc:
        if "stream" in locals():
            result["last_io"] = stream.last_io
        result["error"] = _os_error(exc)
        return result
    except PhotorealSpatialMetadataProbeError as exc:
        if "stream" in locals():
            result["last_io"] = stream.last_io
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc)[:512],
        }
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only traced ISO BMFF diagnostic for a single Photoreal source."
    )
    parser.add_argument("path", help="Path to the exact source file to inspect")
    args = parser.parse_args(argv)
    result = debug_isobmff_file(args.path)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "parsed-isobmff" else 1


if __name__ == "__main__":
    raise SystemExit(main())
