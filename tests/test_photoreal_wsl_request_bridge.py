from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_wsl_request_bridge import (
    PhotorealWslRequestBridgeError,
    build_linux_invocation,
    rewrite_request_transport_paths,
)


def _request() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-frame-analyzer-request",
        "version": 1,
        "performer_id": "42",
        "sources": [
            {
                "source_key": "scene:s1:E:/one.mp4",
                "source_sha256": "a" * 64,
                "kind": "video",
                "resolved_path": r"\\192.168.1.21\VR_E\one.mp4",
                "split": "train",
                "group_id": "scene:s1",
                "samples": [{"timestamp_seconds": 1.0, "eye": "mono"}],
            },
            {
                "source_key": "image:i1:F:/two.jpg",
                "source_sha256": "b" * 64,
                "kind": "image",
                "resolved_path": r"F:\VR\two.jpg",
                "split": "evaluation",
                "group_id": "image:i1",
                "samples": [{"timestamp_seconds": None, "eye": "mono"}],
            },
        ],
        "measurement_only": True,
        "production_activation": False,
    }


def test_transport_translation_changes_only_nested_resolved_paths() -> None:
    original = _request()
    before = copy.deepcopy(original)

    translated = rewrite_request_transport_paths(original, lambda path: "/transport/" + path.replace("\\", "/").lstrip("/"))

    assert original == before
    assert translated["sources"][0]["resolved_path"].startswith("/transport/")
    assert translated["sources"][1]["resolved_path"].startswith("/transport/")
    for index, source in enumerate(translated["sources"]):
        for key, value in before["sources"][index].items():
            if key != "resolved_path":
                assert source[key] == value
    assert translated["measurement_only"] is True
    assert translated["production_activation"] is False


def test_transport_translation_rejects_non_absolute_linux_path() -> None:
    with pytest.raises(PhotorealWslRequestBridgeError, match="absolute Linux path"):
        rewrite_request_transport_paths(_request(), lambda _path: "relative/path")


def test_linux_invocation_is_direct_argv_without_shell() -> None:
    argv = build_linux_invocation(
        linux_python="/opt/bodyrig-vision/bin/python",
        linux_adapter_path="/mnt/c/repo/tools/photoreal_reference_vision_adapter.py",
        linux_model_root="/mnt/c/models",
        linux_request_path="/mnt/c/tmp/request.json",
        linux_output_path="/mnt/c/tmp/output",
        device="cuda:0",
        bodyrig_adapter="bodyrig-reference-vision-v1",
        bodyrig_revision="a" * 64,
        bodyrig_model_set_sha256="b" * 64,
        bodyrig_identity_bank_sha256="c" * 64,
    )

    assert argv[0] == "/opt/bodyrig-vision/bin/python"
    assert argv[1].endswith("photoreal_reference_vision_adapter.py")
    assert "--bodyrig-request" in argv
    assert "--bodyrig-output" in argv
    assert "--bodyrig-identity-bank-sha256" in argv
    assert not any(item in {"sh", "bash", "cmd", "cmd.exe", "powershell", "pwsh"} for item in argv)


def test_linux_invocation_rejects_relative_transport_paths() -> None:
    with pytest.raises(PhotorealWslRequestBridgeError, match="absolute Linux path"):
        build_linux_invocation(
            linux_python="python3",
            linux_adapter_path="adapter.py",
            linux_model_root="/models",
            linux_request_path="/request.json",
            linux_output_path="/output",
            device="cpu",
            bodyrig_adapter="bodyrig-reference-vision-v1",
            bodyrig_revision="a" * 64,
            bodyrig_model_set_sha256="b" * 64,
            bodyrig_identity_bank_sha256=None,
        )
