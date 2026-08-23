from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .avatar import AvatarError, AvatarFitResult, ProceduralAvatarFitter


@dataclass(frozen=True)
class FitterCapabilities:
    visual_identity: bool
    textures: bool
    hair: bool
    clothing: bool


class RegisteredAvatarFitter(Protocol):
    name: str
    revision: str
    capabilities: FitterCapabilities

    def fit(
        self,
        bodyprint: Mapping[str, Any],
        *,
        name: str,
        identity: Mapping[str, Any] | None = None,
    ) -> AvatarFitResult: ...


class ProceduralFitterAdapter:
    name = ProceduralAvatarFitter.name
    revision = ProceduralAvatarFitter.revision
    capabilities = FitterCapabilities(
        visual_identity=False,
        textures=False,
        hair=False,
        clothing=False,
    )

    def __init__(self) -> None:
        self._inner = ProceduralAvatarFitter()

    def fit(
        self,
        bodyprint: Mapping[str, Any],
        *,
        name: str,
        identity: Mapping[str, Any] | None = None,
    ) -> AvatarFitResult:
        if identity is not None:
            raise AvatarError(
                "fitter procedural-vrm1 does not support visual identity input; "
                "refusing to present a placeholder as an identity clone"
            )
        return self._inner.fit(bodyprint, name=name)


_FACTORIES = {
    ProceduralFitterAdapter.name: ProceduralFitterAdapter,
}


def fitter_names() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))


def get_fitter(name: str) -> RegisteredAvatarFitter:
    factory = _FACTORIES.get(name)
    if factory is None:
        available = ", ".join(fitter_names())
        raise AvatarError(f"unknown avatar fitter {name!r}; available: {available}")
    return factory()
