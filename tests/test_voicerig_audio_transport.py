from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bodyrig import voicerig_client
from bodyrig.voicerig_client import VoiceRigClient, VoiceRigClientError


def test_video_source_is_normalized_to_audio_only_before_upload(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "huge-vr-source.mp4"
    source.write_bytes(b"video-container-placeholder")
    calls: list[list[str]] = []

    monkeypatch.setattr(voicerig_client.shutil, "which", lambda name: "C:/ffmpeg/bin/ffmpeg.exe" if name == "ffmpeg" else None)

    def fake_run(command, *, capture_output: bool, text: bool, check: bool):
        calls.append(list(command))
        assert capture_output is True
        assert text is True
        assert check is False
        assert str(source.resolve()) in command
        assert "-vn" in command
        assert command[command.index("-ac") + 1] == "1"
        assert command[command.index("-ar") + 1] == "24000"
        assert command[command.index("-c:a") + 1] == "flac"
        target = Path(command[-1])
        target.write_bytes(b"fLaC" + b"\0" * 256)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(voicerig_client.subprocess, "run", fake_run)

    prepared = voicerig_client._prepare_voice_upload_paths([source.resolve()], tmp_path / "audio")

    assert len(calls) == 1
    assert len(prepared) == 1
    assert prepared[0].suffix == ".flac"
    assert prepared[0].name == "source-01.flac"
    assert prepared[0] != source.resolve()
    assert prepared[0].is_file()


def test_existing_audio_source_is_not_needlessly_transcoded(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "already-audio.flac"
    source.write_bytes(b"fLaC" + b"\0" * 256)

    def unexpected_run(*args, **kwargs):
        raise AssertionError("FFmpeg must not run for an existing audio-only source")

    monkeypatch.setattr(voicerig_client.subprocess, "run", unexpected_run)
    prepared = voicerig_client._prepare_voice_upload_paths([source.resolve()], tmp_path / "audio")

    assert prepared == [source.resolve()]


def test_video_source_fails_closed_when_ffmpeg_is_missing(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video-container-placeholder")
    monkeypatch.setattr(voicerig_client.shutil, "which", lambda _name: None)

    with pytest.raises(VoiceRigClientError, match="FFmpeg is required"):
        voicerig_client._prepare_voice_upload_paths([source.resolve()], tmp_path / "audio")


def test_start_voice_job_passes_only_prepared_audio_to_multipart(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video-container-placeholder")
    captured: dict[str, object] = {}

    def fake_prepare(paths: list[Path], root: Path) -> list[Path]:
        assert paths == [source.resolve()]
        target = root / "source-01.flac"
        target.write_bytes(b"fLaC" + b"\0" * 256)
        return [target]

    monkeypatch.setattr(voicerig_client, "_prepare_voice_upload_paths", fake_prepare)
    client = VoiceRigClient()

    def fake_upload(*, clean_name: str, clean_language: str, accent: str, paths: list[Path]):
        captured.update(
            clean_name=clean_name,
            clean_language=clean_language,
            accent=accent,
            suffixes=[path.suffix for path in paths],
            originals=[path == source.resolve() for path in paths],
        )
        return {"id": "f" * 32, "state": "queued"}

    monkeypatch.setattr(client, "_upload_voice_job", fake_upload)

    result = client.start_voice_job(name="Fixture", language="da", files=[source])

    assert result["id"] == "f" * 32
    assert captured == {
        "clean_name": "Fixture",
        "clean_language": "da",
        "accent": "",
        "suffixes": [".flac"],
        "originals": [False],
    }
