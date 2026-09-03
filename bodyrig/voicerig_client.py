from __future__ import annotations

import http.client
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .execution_provenance import ExecutionProvenanceError, record_runtime

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_VOICE_PACKAGE_BYTES = 160 * 1024 * 1024
MAX_AUDIO_BYTES = 64 * 1024 * 1024
MAX_SOURCE_FILES = 20
VOICE_UPLOAD_SAMPLE_RATE = 24_000
_VIDEO_SOURCE_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class VoiceRigClientError(RuntimeError):
    pass


def _loopback_host(host: str | None) -> bool:
    if not host:
        return False
    return host.lower() == "localhost" or host in {"127.0.0.1", "::1"}


def _package_name(value: str) -> tuple[str, str]:
    package = str(value or "").strip()
    if not package or len(package) > 255 or "/" in package or "\\" in package or package in {".", ".."} or not package.lower().endswith(".mrvoice"):
        raise VoiceRigClientError("Invalid VoiceRig package name")
    return package, urllib.parse.quote(package, safe="")


def _job_id(value: str) -> str:
    clean = str(value or "").strip().lower()
    if not _JOB_ID_RE.fullmatch(clean):
        raise VoiceRigClientError("Invalid VoiceRig job id")
    return clean


def _prepare_voice_upload_paths(paths: list[Path], root: Path) -> list[Path]:
    """Normalize video sources to VoiceRig's canonical audio before transport.

    BodyRig has already verified the original source bytes before this function is
    called. The original Stash file SHA-256 values remain the source authority;
    this is only a transport optimization. VoiceRig itself normalizes arbitrary
    media to 24 kHz mono PCM before diarization, so doing that decode here and
    wrapping it as FLAC avoids sending video bytes without changing the audio
    representation VoiceRig analyzes.
    """
    if not any(path.suffix.lower() in _VIDEO_SOURCE_EXTENSIONS for path in paths):
        return list(paths)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VoiceRigClientError("FFmpeg is required to extract audio before VoiceRig upload")
    root.mkdir(parents=True, exist_ok=True)

    prepared: list[Path] = []
    for index, path in enumerate(paths, start=1):
        if path.suffix.lower() not in _VIDEO_SOURCE_EXTENSIONS:
            prepared.append(path)
            continue

        target = root / f"source-{index:02d}.flac"
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(VOICE_UPLOAD_SAMPLE_RATE),
            "-sample_fmt",
            "s16",
            "-c:a",
            "flac",
            str(target),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except OSError as exc:
            raise VoiceRigClientError(f"Could not extract VoiceRig audio from {path.name}: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or "unknown FFmpeg error").strip()
            raise VoiceRigClientError(f"Could not extract VoiceRig audio from {path.name}: {detail[:500]}")
        if not target.is_file() or target.stat().st_size < 128:
            raise VoiceRigClientError(f"VoiceRig source has no usable audio: {path.name}")
        prepared.append(target)
    return prepared


@dataclass(frozen=True)
class VoiceRigConfig:
    url: str = "http://127.0.0.1:8765"
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        parsed = urllib.parse.urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not _loopback_host(parsed.hostname):
            raise VoiceRigClientError("VoiceRig URL must use a loopback host")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise VoiceRigClientError("VoiceRig URL must not contain credentials, query or fragment")
        if isinstance(self.timeout_seconds, bool) or not 1 <= self.timeout_seconds <= 300:
            raise VoiceRigClientError("VoiceRig timeout_seconds must be in 1..300")

    @property
    def base_url(self) -> str:
        return self.url.rstrip("/")


class VoiceRigClient:
    def __init__(self, config: VoiceRigConfig | None = None) -> None:
        self.config = config or VoiceRigConfig()

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
        limit: int = MAX_JSON_BYTES,
    ) -> tuple[bytes, dict[str, str]]:
        if not path.startswith("/"):
            raise VoiceRigClientError("VoiceRig request path must be absolute")
        if payload is not None and form is not None:
            raise VoiceRigClientError("VoiceRig request cannot use JSON and form payload together")
        data = None
        headers = {"Accept": "application/json, audio/wav, application/octet-stream", "User-Agent": "BodyRig/0.1 VoiceRigBridge"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif form is not None:
            data = urllib.parse.urlencode(form).encode("ascii")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(self.config.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                length = response.headers.get("Content-Length")
                if length:
                    try:
                        if int(length) > limit:
                            raise VoiceRigClientError("VoiceRig response exceeds BodyRig size limit")
                    except ValueError:
                        pass
                raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise VoiceRigClientError("VoiceRig response exceeds BodyRig size limit")
                return raw, {str(k).lower(): str(v) for k, v in response.headers.items()}
        except VoiceRigClientError:
            raise
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(MAX_JSON_BYTES).decode("utf-8", errors="replace")[:1000]
            except Exception:
                detail = ""
            raise VoiceRigClientError(f"VoiceRig HTTP {exc.code}: {detail or exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise VoiceRigClientError(f"Could not reach VoiceRig: {exc}") from exc

    @staticmethod
    def _json(raw: bytes, label: str) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VoiceRigClientError(f"VoiceRig {label} returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise VoiceRigClientError(f"VoiceRig {label} returned a non-object")
        return value

    @staticmethod
    def _job_from_response(raw: bytes, label: str) -> dict[str, Any]:
        value = VoiceRigClient._json(raw, label)
        job = value.get("job")
        if value.get("ok") is not True or not isinstance(job, dict):
            raise VoiceRigClientError(f"VoiceRig {label} returned an invalid job response")
        _job_id(str(job.get("id") or job.get("job_id") or ""))
        return job

    def health(self) -> dict[str, Any]:
        raw, _ = self._request("/api/health")
        value = self._json(raw, "health")
        if value.get("ok") is not True or value.get("service") != "voicerig":
            raise VoiceRigClientError("VoiceRig health did not report the expected service")
        try:
            record_runtime("voicerig", value.get("version"))
        except ExecutionProvenanceError as exc:
            raise VoiceRigClientError("VoiceRig health did not report a valid version") from exc
        return value

    def voices(self) -> list[dict[str, Any]]:
        raw, _ = self._request("/api/voices")
        value = self._json(raw, "voice library")
        voices = value.get("voices")
        if not isinstance(voices, list):
            raise VoiceRigClientError("VoiceRig voice library has invalid shape")
        result: list[dict[str, Any]] = []
        for item in voices:
            if not isinstance(item, dict):
                continue
            package = str(item.get("package") or "")
            voice_id = str(item.get("id") or "")
            name = str(item.get("name") or "")
            try:
                package, _ = _package_name(package)
            except VoiceRigClientError:
                continue
            if not voice_id or not name:
                continue
            result.append({
                "id": voice_id,
                "name": name,
                "language": str(item.get("language") or ""),
                "accent": item.get("accent"),
                "package": package,
                "is_default": item.get("is_default") is True,
                "compatibility": item.get("compatibility") if isinstance(item.get("compatibility"), dict) else {},
            })
        return result

    def package_bytes(self, package: str) -> bytes:
        _, encoded = _package_name(package)
        raw, _ = self._request(f"/api/packages/{encoded}", limit=MAX_VOICE_PACKAGE_BYTES)
        return raw

    def preview(self, package: str) -> bytes:
        _, encoded = _package_name(package)
        raw, headers = self._request(f"/api/voices/{encoded}/preview", limit=MAX_AUDIO_BYTES)
        content_type = headers.get("content-type", "")
        if "audio/wav" not in content_type or not raw.startswith(b"RIFF"):
            raise VoiceRigClientError("VoiceRig preview did not return WAV audio")
        return raw

    def synthesize(self, package: str, text: str) -> bytes:
        if not text.strip() or len(text) > 4000:
            raise VoiceRigClientError("Voice preview text must be 1..4000 characters")
        self.health()
        package, _ = _package_name(package)
        raw, headers = self._request(
            "/api/tts/synthesize",
            method="POST",
            payload={"text": text, "voice_package": package},
            limit=MAX_AUDIO_BYTES,
        )
        content_type = headers.get("content-type", "")
        if "audio/wav" not in content_type or not raw.startswith(b"RIFF"):
            raise VoiceRigClientError("VoiceRig synthesis did not return WAV audio")
        return raw

    def _upload_voice_job(
        self,
        *,
        clean_name: str,
        clean_language: str,
        accent: str,
        paths: list[Path],
    ) -> dict[str, Any]:
        boundary = f"bodyrig-{uuid.uuid4().hex}"
        boundary_bytes = boundary.encode("ascii")

        def field_part(key: str, value: str) -> bytes:
            return (
                b"--" + boundary_bytes + b"\r\n"
                + f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("ascii")
                + value.encode("utf-8") + b"\r\n"
            )

        parts = [
            field_part("name", clean_name),
            field_part("language", clean_language),
            field_part("accent", str(accent or "").strip()),
            field_part("install_in_modelrig", "false"),
        ]
        file_headers: list[bytes] = []
        content_length = sum(len(part) for part in parts)
        for index, path in enumerate(paths, start=1):
            suffix = path.suffix.lower()
            upload_name = f"source-{index:02d}{suffix}"
            content_type = mimetypes.guess_type(upload_name)[0] or "application/octet-stream"
            header = (
                b"--" + boundary_bytes + b"\r\n"
                + f'Content-Disposition: form-data; name="files"; filename="{upload_name}"\r\n'.encode("ascii")
                + f"Content-Type: {content_type}\r\n\r\n".encode("ascii")
            )
            file_headers.append(header)
            content_length += len(header) + path.stat().st_size + 2
        closing = b"--" + boundary_bytes + b"--\r\n"
        content_length += len(closing)

        parsed = urllib.parse.urlsplit(self.config.base_url)
        base_path = parsed.path.rstrip("/")
        target = f"{base_path}/api/jobs/voices" or "/api/jobs/voices"
        connection_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        connection = connection_class(parsed.hostname, port, timeout=max(self.config.timeout_seconds, 300))
        try:
            connection.putrequest("POST", target)
            connection.putheader("Accept", "application/json")
            connection.putheader("User-Agent", "BodyRig/0.1 VoiceRigBridge")
            connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            connection.putheader("Content-Length", str(content_length))
            connection.endheaders()
            for part in parts:
                connection.send(part)
            for path, header in zip(paths, file_headers, strict=True):
                connection.send(header)
                with path.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        connection.send(chunk)
                connection.send(b"\r\n")
            connection.send(closing)
            response = connection.getresponse()
            raw = response.read(MAX_JSON_BYTES + 1)
            if len(raw) > MAX_JSON_BYTES:
                raise VoiceRigClientError("VoiceRig voice build response exceeds BodyRig size limit")
            if response.status < 200 or response.status >= 300:
                detail = raw.decode("utf-8", errors="replace")[:1000]
                raise VoiceRigClientError(f"VoiceRig HTTP {response.status}: {detail or response.reason}")
            return self._job_from_response(raw, "voice build")
        except VoiceRigClientError:
            raise
        except (http.client.HTTPException, TimeoutError, OSError) as exc:
            raise VoiceRigClientError(f"Could not upload source media to VoiceRig: {exc}") from exc
        finally:
            connection.close()

    def start_voice_job(
        self,
        *,
        name: str,
        language: str,
        files: list[str | os.PathLike[str]],
        accent: str = "",
    ) -> dict[str, Any]:
        clean_name = str(name or "").strip()
        clean_language = str(language or "").strip()
        if not clean_name or len(clean_name) > 160:
            raise VoiceRigClientError("VoiceRig build name is invalid")
        if not clean_language or len(clean_language) > 32:
            raise VoiceRigClientError("VoiceRig build language is invalid")
        paths = [Path(value).expanduser().resolve() for value in files]
        if not 1 <= len(paths) <= MAX_SOURCE_FILES:
            raise VoiceRigClientError(f"VoiceRig source build requires 1..{MAX_SOURCE_FILES} files")
        for path in paths:
            if not path.is_file():
                raise VoiceRigClientError(f"VoiceRig source file is not readable: {path.name}")

        with tempfile.TemporaryDirectory(prefix="bodyrig-voicerig-audio-") as temp:
            upload_paths = _prepare_voice_upload_paths(paths, Path(temp))
            return self._upload_voice_job(
                clean_name=clean_name,
                clean_language=clean_language,
                accent=accent,
                paths=upload_paths,
            )

    def voice_job(self, job_id: str) -> dict[str, Any]:
        clean = _job_id(job_id)
        raw, _ = self._request(f"/api/jobs/{clean}")
        return self._job_from_response(raw, "job status")

    def choose_voice_job_speaker(self, job_id: str, anchor: str) -> dict[str, Any]:
        clean = _job_id(job_id)
        value = str(anchor or "").strip()
        if not value or len(value) > 64 or ":" not in value:
            raise VoiceRigClientError("Invalid VoiceRig speaker anchor")
        raw, _ = self._request(f"/api/jobs/{clean}/speaker", method="POST", form={"anchor": value})
        return self._job_from_response(raw, "speaker selection")

    def choose_voice_job_reference(self, job_id: str, choice: int) -> dict[str, Any]:
        clean = _job_id(job_id)
        if isinstance(choice, bool) or not 1 <= int(choice) <= 4:
            raise VoiceRigClientError("Invalid VoiceRig reference choice")
        raw, _ = self._request(f"/api/jobs/{clean}/reference", method="POST", form={"choice": int(choice)})
        return self._job_from_response(raw, "reference selection")

    def cancel_voice_job(self, job_id: str) -> dict[str, Any]:
        clean = _job_id(job_id)
        raw, _ = self._request(f"/api/jobs/{clean}/cancel", method="POST", form={})
        return self._job_from_response(raw, "job cancel")