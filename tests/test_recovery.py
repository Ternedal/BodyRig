import json
import subprocess
import sys
from pathlib import Path

import pytest
from bodyrig.recovery import (
    BodyprintExtractor,
    JsonCommandRecoveryAdapter,
    RecoveryError,
    parse_recovery_result,
)


def frame(ts, shift=0.0):
    return {"timestamp_ms":ts,"confidence":0.9,"joints":{"head":[0.0+shift,1.8,0.0],"left_shoulder":[-0.22+shift,1.45,0.0],"right_shoulder":[0.22+shift,1.45,0.0],"left_hip":[-0.16+shift,1.0,0.0],"right_hip":[0.16+shift,1.0,0.0],"left_wrist":[-0.55-shift,1.15,0.0],"right_wrist":[0.55+shift,1.15,0.0],"left_ankle":[-0.12+shift,0.0,0.0],"right_ankle":[0.12+shift,0.0,0.0]}}


def payload(frames): return {"format":"bodyrig-recovery","version":1,"adapter":"fixture","revision":"fixture-v1","tracks":[{"track_id":"person-1","frames":frames}]}


def test_parse_and_extract_observed_bodyprint():
    result=parse_recovery_result(payload([frame(0),frame(500,0.08),frame(1000,0.16)])); bodyprint=BodyprintExtractor().extract(result.tracks[0])
    assert 0.20 < bodyprint["shape"]["shoulder_to_height"] < 0.30
    assert 0.0 <= bodyprint["motion"]["energy"] <= 1.0
    assert "height_scale" not in bodyprint["shape"]


def test_non_finite_joint_rejected():
    bad=payload([frame(0),frame(100)]); bad["tracks"][0]["frames"][1]["joints"]["head"][0]=float("nan")
    with pytest.raises(RecoveryError,match="finite"): parse_recovery_result(bad)


def test_out_of_order_time_rejected():
    with pytest.raises(RecoveryError,match="strictly increasing"): parse_recovery_result(payload([frame(100),frame(100)]))


def test_adapter_identity_pinned():
    with pytest.raises(RecoveryError,match="identity mismatch"): parse_recovery_result(payload([frame(0),frame(100)]),expected_adapter="hmr2")


def test_json_command_adapter_pins_utf8_decoding(monkeypatch):
    captured = {}
    expected = payload([frame(0), frame(100)])

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(expected),
            stderr="",
        )

    monkeypatch.setattr("bodyrig.recovery.subprocess.run", fake_run)
    adapter = JsonCommandRecoveryAdapter(
        ["fixture-command"],
        name="fixture",
        revision="fixture-v1",
    )
    adapter.recover([Path("source.mp4")])

    assert captured["text"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_json_command_adapter_handles_cp1252_undefined_utf8_byte_sequence():
    # U+0081 encodes to UTF-8 bytes C2 81. Byte 0x81 is undefined in Windows
    # cp1252, matching the class of failure seen in the physical WSL recovery.
    revision = "fixture-\u0081"
    expected = payload([frame(0), frame(100)])
    expected["revision"] = revision
    raw = json.dumps(expected, ensure_ascii=False).encode("utf-8")
    script = "import sys; sys.stdout.buffer.write(" + repr(raw) + ")"

    adapter = JsonCommandRecoveryAdapter(
        [sys.executable, "-c", script],
        name="fixture",
        revision=revision,
        timeout_seconds=10,
    )
    result = adapter.recover([Path("source.mp4")])

    assert result.revision == revision
