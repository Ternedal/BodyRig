from __future__ import annotations

from .skin_qa import (
    ANATOMY_APPEARANCE,
    CANONICAL_APPEARANCE,
    SkinQaError,
    _validate_transfer_authority,
    analyze_package,
    analyze_vrm_skin,
    main,
    write_report,
)

# Compatibility alias for the short-lived PR #63 implementation. Gate A now
# uses bodyrig.skin_qa as the single validator authority.
GateAppearanceError = SkinQaError

__all__ = [
    "ANATOMY_APPEARANCE",
    "CANONICAL_APPEARANCE",
    "GateAppearanceError",
    "SkinQaError",
    "_validate_transfer_authority",
    "analyze_package",
    "analyze_vrm_skin",
    "main",
    "write_report",
]
