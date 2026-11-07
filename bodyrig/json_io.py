"""Shared fail-closed reader for JSON evidence/receipt objects.

Every module used to carry its own ``_read_json`` (140 copies in 48 textual
variants, #1386 recommendation B). They differed in four independent knobs,
not in intent: BOM tolerance (utf-8-sig vs utf-8), NaN/Infinity handling,
which exception types were turned into the module error, and whether the
top-level value had to be an object. docs/JSON_EVIDENCE_READ_POLICY.md
records the canonical behaviour implemented here:

- the file is decoded as UTF-8 with an optional BOM (Windows tooling emits
  BOMs; the bytes after it are the same document);
- ``NaN``/``Infinity`` tokens are rejected (no BodyRig writer emits them --
  every canonical dump uses ``allow_nan=False`` -- so they only ever mean a
  malformed or foreign file);
- the top-level value must be a JSON object;
- any read, decode or parse failure (``OSError``, ``UnicodeError``,
  ``ValueError`` -- which covers ``json.JSONDecodeError``) is raised as the
  caller's own error class with the caller's own message, chained to the
  cause, so no module's fail-closed wording changes.

Pre-checks that carry their own messages (``is_file()``, ``is_symlink()``)
and path resolution (``expanduser().resolve()``) stay in the calling module,
exactly where they were. Standard library only; safe to import anywhere
``bodyrig`` itself is importable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _reject_constant(token: str) -> Any:
    raise ValueError(f"non-finite JSON constant is not allowed: {token}")


def read_json_object(
    path: str | Path,
    *,
    error: type[Exception],
    unreadable: str,
    not_object: str,
) -> dict[str, Any]:
    """Read ``path`` as a JSON object, failing closed with the caller's error.

    ``unreadable`` is raised (chained to the cause) when the file cannot be
    read, decoded or parsed; ``not_object`` when the document parses but is
    not a JSON object.
    """
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=_reject_constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise error(unreadable) from exc
    if not isinstance(value, dict):
        raise error(not_object)
    return value
