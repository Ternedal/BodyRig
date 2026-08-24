from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_VOICE_PACKAGE_BYTES = 160 * 1024 * 1024
MAX_AUDIO_BYTES = 64 * 1024 * 1024


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

    def _request(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, limit: int = MAX_JSON_BYTES) -> tuple[bytes, dict[str, str]]:
        if not path.startswith("/"):
            raise VoiceRigClientError("VoiceRig request path must be absolute")
        data = None
        headers = {"Accept": "application/json, audio/wav, application/octet-stream", "User-Agent": "BodyRig/0.1 VoiceRigBridge"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
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

    def health(self) -> dict[str, Any]:
        raw, _ = self._request("/api/health")
        value = self._json(raw, "health")
        if value.get("ok") is not True or value.get("service") != "voicerig":
            raise VoiceRigClientError("VoiceRig health did not report the expected service")
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
