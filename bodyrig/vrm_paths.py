"""Fail-closed path checks for texture relinking in the VRM worker (#1399 review).

Pure Python, no ``bpy``: staged next to ``blender_vrm_worker.py`` and imported
by the host tests directly.

The staging root is private and built by the host without links (zip links are
refused, folder copies skip them), so these checks are defence in depth. They
still hold if the staging layout is ever different from what the host built,
or is changed between indexing and reload:

- ``contained`` is true only when the resolved path is inside the resolved root
  **and** no component from the root down to the path is a link;
- ``image_index`` never descends into linked folders, never lists linked
  files, and only lists files that pass ``contained``;
- the worker calls ``contained`` again immediately before ``image.reload()``.
"""

from __future__ import annotations

import os

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tga", ".dds", ".bmp")


def _is_link(path: str) -> bool:
    try:
        if os.path.islink(path):
            return True
        is_junction = getattr(os.path, "isjunction", None)  # Windows junctions (Python 3.12+)
        return bool(is_junction and is_junction(path))
    except OSError:
        return True  # unreadable: treat as unsafe


def contained(path: str, root: str) -> bool:
    """True if ``path`` is a regular file or folder strictly under ``root`` with no link on the way."""
    try:
        root_abs = os.path.abspath(root)
        path_abs = os.path.abspath(path)
        root_real = os.path.normcase(os.path.realpath(root_abs))
        path_real = os.path.normcase(os.path.realpath(path_abs))
        if path_real == root_real or os.path.commonpath([path_real, root_real]) != root_real:
            return False
        rel = os.path.relpath(path_abs, root_abs)
    except (ValueError, OSError):  # different drives on Windows, unreadable
        return False
    if rel.startswith(os.pardir) or os.path.isabs(rel):
        return False
    current = root_abs
    for part in rel.split(os.sep):
        current = os.path.join(current, part)
        if _is_link(current):
            return False
    return os.path.exists(path_abs)


def image_index(root: str) -> dict[str, str]:
    """lower-case file name and stem -> path, for image files safely inside ``root``."""
    index: dict[str, str] = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not _is_link(os.path.join(folder, d)))
        for name in sorted(files):
            if not name.lower().endswith(IMAGE_SUFFIXES):
                continue
            full = os.path.join(folder, name)
            if _is_link(full) or not os.path.isfile(full) or not contained(full, root):
                continue
            index.setdefault(name.lower(), full)
            index.setdefault(os.path.splitext(name)[0].lower(), full)
    return index
