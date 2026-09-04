from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .execution_provenance import ExecutionProvenanceError, record_runtime

MAX_JSON_BYTES = 4 * 1024 * 1024


class ModelRigClientError(RuntimeError):
    pass


def _loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


@dataclass(frozen=True)
class ModelRigConfig:
    url: str = "http://127.0.0.1:8080"
    token: str = ""
    timeout_seconds: int = 120

    def __post_init__(self) -> None:
        parsed = urllib.parse.urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not _loopback_host(parsed.hostname):
            raise ModelRigClientError("ModelRig URL must use a loopback host")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ModelRigClientError("ModelRig URL must not contain credentials, query or fragment")
        if isinstance(self.timeout_seconds, bool) or not 1 <= self.timeout_seconds <= 300:
            raise ModelRigClientError("ModelRig timeout_seconds must be in 1..300")
        if not isinstance(self.token, str) or len(self.token) > 4096 or any(ord(ch) < 33 or ord(ch) > 126 for ch in self.token):
            raise ModelRigClientError("ModelRig token is invalid")

    @property
    def base_url(self) -> str:
        return self.url.rstrip("/")


class ModelRigClient:
    def __init__(self, config: ModelRigConfig | None = None) -> None:
        self.config = config or ModelRigConfig()
        self._opener = urllib.request.build_opener(_NoRedirect())

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        require_auth: bool = True,
    ) -> bytes:
        if not path.startswith("/"):
            raise ModelRigClientError("ModelRig request path must be absolute")
        if require_auth and not self.config.token:
            raise ModelRigClientError("MODELRIG_TOKEN is required for ModelRig personality audition")
        data = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "BodyRig/0.1 ModelRigBridge",
        }
        if require_auth:
            headers["Authorization"] = f"Bearer {self.config.token}"
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.config.base_url + path, data=data, method=method, headers=headers)
        try:
            with self._opener.open(request, timeout=self.config.timeout_seconds) as response:
                length = response.headers.get("Content-Length")
                if length:
                    try:
                        if int(length) > MAX_JSON_BYTES:
                            raise ModelRigClientError("ModelRig response exceeds BodyRig size limit")
                    except ValueError:
                        pass
                raw = response.read(MAX_JSON_BYTES + 1)
                if len(raw) > MAX_JSON_BYTES:
                    raise ModelRigClientError("ModelRig response exceeds BodyRig size limit")
                return raw
        except ModelRigClientError:
            raise
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(MAX_JSON_BYTES).decode("utf-8", errors="replace")[:1000]
            except Exception:
                detail = ""
            raise ModelRigClientError(f"ModelRig HTTP {exc.code}: {detail or exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelRigClientError(f"Could not reach ModelRig: {exc}") from exc

    @staticmethod
    def _json(raw: bytes, label: str) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelRigClientError(f"ModelRig {label} returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise ModelRigClientError(f"ModelRig {label} returned a non-object")
        return value

    def health(self) -> dict[str, Any]:
        value = self._json(self._request("/healthz", require_auth=False), "health")
        if value.get("status") != "ok" or value.get("service") != "modelrig-server":
            raise ModelRigClientError("ModelRig health did not report the expected service")
        version = value.get("version")
        try:
            record_runtime("modelrig-server", version)
        except ExecutionProvenanceError as exc:
            raise ModelRigClientError("ModelRig health did not report a valid version") from exc
        return value

    def models(self) -> list[dict[str, Any]]:
        value = self._json(self._request("/api/v1/models"), "model list")
        models = value.get("models")
        if not isinstance(models, list):
            raise ModelRigClientError("ModelRig model list has invalid shape")
        result: list[dict[str, Any]] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("model") or "").strip()
            if not name or len(name) > 256 or any(ord(ch) < 32 for ch in name):
                continue
            result.append({"name": name, "size": item.get("size") if isinstance(item.get("size"), int) else None})
        return result

    def chat(self, *, model: str, system: str, prompt: str) -> str:
        model = str(model or "").strip()
        system = str(system or "").strip()
        prompt = str(prompt or "").strip()
        if not model or len(model) > 256:
            raise ModelRigClientError("ModelRig audition model is invalid")
        if not system or len(system) > 80_000:
            raise ModelRigClientError("ModelRig audition system prompt is invalid")
        if not prompt or len(prompt) > 16_000:
            raise ModelRigClientError("ModelRig audition prompt is invalid")
        value = self._json(
            self._request(
                "/api/v1/chat",
                method="POST",
                payload={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                },
            ),
            "chat",
        )
        message = value.get("message")
        if not isinstance(message, dict):
            raise ModelRigClientError("ModelRig chat response is missing message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > 64_000:
            raise ModelRigClientError("ModelRig chat response content is invalid")
        return content.strip()
