from __future__ import annotations

import hashlib
import importlib.metadata
import sys
from pathlib import Path

import pytest

from bodyrig.runtime_lock import RuntimeLockError, load_lock, validate_runtime


REQUIRED = {
    "fastapi": "1.0",
    "uvicorn": "1.0",
    "pydantic": "1.0",
    "pillow": "1.0",
    "pytest": "1.0",
    "httpx": "1.0",
    "httpx2": "1.0",
}


def _write_lock(path: Path, values: dict[str, str] | None = None) -> dict[str, str]:
    packages = dict(REQUIRED)
    if values:
        packages.update(values)
    path.write_text(
        "# fixture\n" + "".join(f"{name}=={version}\n" for name, version in sorted(packages.items())),
        encoding="utf-8",
    )
    return packages


def test_lock_requires_exact_pins_and_required_distributions(tmp_path: Path) -> None:
    lock = tmp_path / "lock.txt"
    expected = _write_lock(lock)
    assert load_lock(lock) == expected

    lock.write_text("fastapi>=1.0\n", encoding="utf-8")
    with pytest.raises(RuntimeLockError, match="exact name==version"):
        load_lock(lock)

    lock.write_text("fastapi==1.0\n", encoding="utf-8")
    with pytest.raises(RuntimeLockError, match="missing required"):
        load_lock(lock)


def test_lock_rejects_normalized_duplicate_names(tmp_path: Path) -> None:
    lock = tmp_path / "lock.txt"
    _write_lock(lock, {"typing-extensions": "4.0"})
    with lock.open("a", encoding="utf-8") as handle:
        handle.write("typing_extensions==4.0\n")
    with pytest.raises(RuntimeLockError, match="duplicate package"):
        load_lock(lock)


def test_runtime_validation_binds_python_lock_hash_and_exact_versions(tmp_path: Path) -> None:
    lock = tmp_path / "lock.txt"
    expected = _write_lock(lock, {"typing-extensions": "4.16.0"})

    def version_reader(name: str) -> str:
        return expected[name]

    result = validate_runtime(
        lock,
        expected_python=sys.version_info[:2],
        version_reader=version_reader,
    )
    assert result["ok"] is True
    assert result["format"] == "bodyrig-windows-python-runtime-lock"
    assert result["version"] == 1
    assert result["lock"]["sha256"] == hashlib.sha256(lock.read_bytes()).hexdigest()
    assert result["lock"]["package_count"] == len(expected)
    assert result["packages"] == dict(sorted(expected.items()))


def test_runtime_validation_fails_closed_on_python_or_package_drift(tmp_path: Path) -> None:
    lock = tmp_path / "lock.txt"
    expected = _write_lock(lock)

    wrong_python = (99, 99)
    with pytest.raises(RuntimeLockError, match="requires Python"):
        validate_runtime(lock, expected_python=wrong_python, version_reader=lambda name: expected[name])

    def wrong_version(name: str) -> str:
        return "9.9" if name == "fastapi" else expected[name]

    with pytest.raises(RuntimeLockError, match=r"fastapi: 9\.9 != 1\.0"):
        validate_runtime(
            lock,
            expected_python=sys.version_info[:2],
            version_reader=wrong_version,
        )


def test_runtime_validation_reports_missing_distribution(tmp_path: Path) -> None:
    lock = tmp_path / "lock.txt"
    expected = _write_lock(lock)

    def missing(name: str) -> str:
        if name == "httpx2":
            raise importlib.metadata.PackageNotFoundError(name)
        return expected[name]

    with pytest.raises(RuntimeLockError, match=r"httpx2: missing"):
        validate_runtime(
            lock,
            expected_python=sys.version_info[:2],
            version_reader=missing,
        )
