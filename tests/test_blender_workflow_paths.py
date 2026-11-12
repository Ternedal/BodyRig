"""The Blender workflows must run when a module their tests import is changed.

``scene-inspector.yml`` and ``vrm-export.yml`` only start for the paths they
list. A ``bodyrig`` module that one of their test files imports, but that is
missing from the list, can change without the real-Blender tests running.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ("scene-inspector.yml", "vrm-export.yml")


def _path_lists(text: str) -> dict[str, set[str]]:
    """Return the ``paths:`` entries of each trigger in the ``on:`` block."""
    lists: dict[str, set[str]] = {}
    trigger: str | None = None
    in_paths = False
    for line in text.splitlines():
        if line and not line.startswith(" "):
            # A new top-level key ends the ``on:`` block.
            trigger, in_paths = None, False
            continue
        header = re.fullmatch(r"  (\w+):.*", line)
        if header:
            trigger, in_paths = header.group(1), False
        elif trigger and line == "    paths:":
            in_paths = True
            lists[trigger] = set()
        elif in_paths and (item := re.fullmatch(r'      - "(.+)"', line)):
            lists[trigger].add(item.group(1))
        elif line.strip():
            in_paths = False
    return lists


def _test_files(text: str) -> list[Path]:
    """The test files the workflow passes to pytest."""
    return [ROOT / name for name in sorted(set(re.findall(r"tests/test_\w+\.py", text)))]


def _imported_modules(test_file: Path) -> set[str]:
    """``bodyrig`` modules a test file imports, at module level or inside a test."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(test_file.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "bodyrig":
                modules.update(alias.name for alias in node.names)
            elif node.module.startswith("bodyrig."):
                modules.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            modules.update(
                alias.name.split(".")[1] for alias in node.names if alias.name.startswith("bodyrig.")
            )
    return {name for name in modules if (ROOT / "bodyrig" / f"{name}.py").is_file()}


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_modules_imported_by_the_workflow_tests_trigger_the_workflow(workflow: str) -> None:
    text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    lists = _path_lists(text)
    assert set(lists) == {"pull_request", "push"}, sorted(lists)
    tests = _test_files(text)
    assert tests, f"{workflow} passes no test files to pytest"
    needed = {f"bodyrig/{module}.py" for test in tests for module in _imported_modules(test)}
    assert needed, f"{workflow}: found no bodyrig imports in {[test.name for test in tests]}"
    for trigger, paths in lists.items():
        missing = sorted(needed - paths)
        assert not missing, f"{workflow} ({trigger}) does not run for: {missing}"


def test_scene_inspector_workflow_runs_for_twin_pose() -> None:
    # tests/test_scene_inspector_blender.py imports BVH files through
    # bodyrig.twin_pose in real Blender; ci.yml runs those tests without bpy.
    text = (ROOT / ".github" / "workflows" / "scene-inspector.yml").read_text(encoding="utf-8")
    lists = _path_lists(text)
    assert lists
    for trigger, paths in lists.items():
        assert "bodyrig/twin_pose.py" in paths, trigger
