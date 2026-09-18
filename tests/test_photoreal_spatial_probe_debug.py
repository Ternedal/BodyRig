from __future__ import annotations

import io

from bodyrig.photoreal_spatial_probe_debug import _TracingStream, _os_error, debug_isobmff_file


def test_debug_probe_parses_minimal_isobmff(tmp_path) -> None:
    source = tmp_path / "minimal.mp4"
    source.write_bytes(
        (8).to_bytes(4, "big") + b"ftyp"
        + (8).to_bytes(4, "big") + b"moov"
    )

    result = debug_isobmff_file(source)

    assert result["status"] == "parsed-isobmff"
    assert result["stage"] == "complete"
    assert result["first_box_type"] == "ftyp"
    assert result["moov_present"] is True
    assert result["size_bytes"] == 16
    assert result["error"] is None
    assert result["last_io"]["operation"] == "read"


def test_tracing_stream_records_seek_target_before_failure() -> None:
    class BrokenSeek(io.BytesIO):
        def seek(self, offset: int, whence: int = 0) -> int:
            raise OSError(22, "Invalid argument")

    stream = _TracingStream(BrokenSeek(b"1234"))

    try:
        stream.seek(123456789)
    except OSError as exc:
        detail = _os_error(exc)
    else:
        raise AssertionError("expected OSError")

    assert stream.last_io == {
        "operation": "seek",
        "offset": 123456789,
        "whence": 0,
        "position_before": 0,
    }
    assert detail["type"] == "OSError"
    assert detail["errno"] == 22
    assert detail["strerror"] == "Invalid argument"
    assert "Invalid argument" in detail["message"]
