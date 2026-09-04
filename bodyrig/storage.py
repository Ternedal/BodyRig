from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    configured = os.environ.get("BODYRIG_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return (Path(local) / "BodyRig").resolve()
    return (Path.home() / ".local" / "share" / "BodyRig").resolve()


def body_library() -> Path:
    return data_dir() / "bodies"


def person_library() -> Path:
    return data_dir() / "people"


def ui_jobs_dir() -> Path:
    return data_dir() / "ui-jobs"
