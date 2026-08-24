from __future__ import annotations

from contextvars import ContextVar

_ALLOWED_SERVICES = {"modelrig-server", "voicerig"}
_runtime_provenance: ContextVar[dict[str, str]] = ContextVar(
    "bodyrig_execution_runtime_provenance",
    default={},
)


class ExecutionProvenanceError(ValueError):
    pass


def _clean_version(value: str) -> str:
    if not isinstance(value, str):
        raise ExecutionProvenanceError("runtime version is invalid")
    text = value.strip()
    if not text or len(text) > 160 or any(ord(ch) < 32 for ch in text):
        raise ExecutionProvenanceError("runtime version is invalid")
    return text


def record_runtime(service: str, version: str) -> None:
    name = str(service or "").strip()
    if name not in _ALLOWED_SERVICES:
        raise ExecutionProvenanceError("runtime service is invalid")
    current = dict(_runtime_provenance.get())
    current[name] = _clean_version(version)
    _runtime_provenance.set(current)


def consume_runtime_provenance() -> dict[str, str]:
    current = dict(_runtime_provenance.get())
    _runtime_provenance.set({})
    return current


def clear_runtime_provenance() -> None:
    _runtime_provenance.set({})
