"""Fail-closed path joins under a trusted root.

Job ids and other request-derived names are already canonicalised by strict
regexes before they reach the filesystem. This helper adds the second,
independent guard: the joined path is normalised and must stay strictly
inside its root, otherwise it fails closed. It is written in the one shape
that CodeQL's path-injection analysis recognises as a sanitizer
(``os.path.normpath`` followed by a ``startswith(root + os.sep)`` check), so
the guard is both real defence in depth and visible to the scanner.
"""

from __future__ import annotations

import os
from pathlib import Path


class PathEscapeError(ValueError):
    pass


def under_root(root: str | Path, *parts: str) -> Path:
    """Return ``root/parts...`` normalised, or raise if the result escapes ``root``."""
    base = os.path.normpath(str(root))
    candidate = os.path.normpath(os.path.join(base, *parts))
    if not candidate.startswith(base + os.sep):
        raise PathEscapeError("path escapes its root")
    return Path(candidate)
