"""under_root: request-derived names stay inside their root, fail closed otherwise.

Job ids are regex-canonicalised before they become paths; this is the second,
independent guard, written in the one shape CodeQL recognises as a
path-injection sanitizer (normpath + startswith(root + sep)). Measured on
main@9e0605d3 with CodeQL 2.27.4: 107 of 108 py/path-injection alerts are
sanitized by routing the fifteen job-id joins through it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bodyrig import safe_paths
from bodyrig.safe_paths import PathEscapeError, under_root


def test_plain_join_is_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    assert under_root(root, "job-" + "a" * 32) == root / ("job-" + "a" * 32)
    assert under_root(root, "job-" + "a" * 32, "job.json") == root / ("job-" + "a" * 32) / "job.json"
    assert under_root(str(root), "x.y.json") == root / "x.y.json"
    # A trailing separator on the root does not change the result.
    assert under_root(str(root) + os.sep, "child") == root / "child"


@pytest.mark.parametrize(
    "parts",
    [
        ("..",),
        ("..", "other"),
        ("job", "..", ".."),
        (os.pardir + os.sep + "sibling",),
        ("",),  # the root itself is not *under* the root
        (".",),
    ],
)
def test_escapes_and_the_root_itself_fail_closed(tmp_path: Path, parts: tuple[str, ...]) -> None:
    with pytest.raises(PathEscapeError):
        under_root(tmp_path / "jobs", *parts)


def test_absolute_part_fails_closed(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere" / "job.json"
    with pytest.raises(PathEscapeError):
        under_root(tmp_path / "jobs", str(other))


def test_error_is_a_value_error_for_existing_fail_closed_wrappers() -> None:
    assert issubclass(PathEscapeError, ValueError)


def test_inner_dot_segments_that_stay_inside_are_normalised(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    assert under_root(root, "a", "..", "b") == root / "b"
    assert under_root(root, "./c") == root / "c"


def test_module_is_standard_library_only() -> None:
    import ast

    source = Path(safe_paths.__file__).read_text(encoding="utf-8")
    modules = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    assert modules == {"__future__", "os", "pathlib"}
