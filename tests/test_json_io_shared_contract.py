"""The canonical JSON-object read lives in bodyrig.json_io; modules do not re-grow their own.

Slice 3 of #1386 recommendation B migrated 131 `_read_json`/`_load_json`
helpers. This contract keeps the class closed: a module that imports bodyrig
may still define `_read_json` for pre-checks (is_file, symlink) or for a
shape the shared reader does not cover (listed in KEPT with the reason), but
the `json.loads(<path>.read_text(...))` core must not reappear.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXEMPT = {
    # owned by open PR #1377
    "bodyrig/stash_source.py",
    "bodyrig/stash_fidelity_reference.py",
    # streaming body pinned by a source-text test
    "bodyrig/personality_authoring.py",
    "bodyrig/json_io.py",
}
# Helpers whose shape the shared reader deliberately does not cover (extra
# validation inside the try, list documents, non-object returns, ...). Each
# entry is a conscious exception, re-reviewed when the module changes.
KEPT = {
    "bodyrig/bridges/hmr2_checkpoint_bridge.py",
    "bodyrig/photoreal_control_plane_ui.py",
    "bodyrig/photoreal_p2_exavatar_heldout_evaluation_runner.py",
    "bodyrig/photoreal_source_verify.py",
    "bodyrig/recovery_rescue_probe.py",
    "bodyrig/rig_window_plan.py",
    "bodyrig/sith_prepare.py",
    "bodyrig/sith_reconstruct.py",
    "bodyrig/wardrobe_source_capture_cli.py",
}
RE_CORE = re.compile(r"json\.loads\(\s*\w+\.read_text\(encoding=\"utf-8(?:-sig)?\"\)", re.S)


def _imports_bodyrig(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and ((node.module or "").split(".")[0] == "bodyrig" or (node.level or 0) > 0):
            return True
        if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "bodyrig" for alias in node.names):
            return True
    return False


def test_read_json_helpers_delegate_to_the_shared_reader() -> None:
    offenders: list[str] = []
    delegates = 0
    for path in sorted((ROOT / "bodyrig").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in EXEMPT or rel in KEPT:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        if not _imports_bodyrig(tree):
            continue
        for node in tree.body:
            if not (isinstance(node, ast.FunctionDef) and node.name in {"_read_json", "_load_json"}):
                continue
            body = ast.get_source_segment(source, node)
            if RE_CORE.search(body):
                offenders.append(f"{rel}:{node.lineno} {node.name}")
            elif "json_io.read_json_object(" in body:
                delegates += 1
    assert offenders == [], "_read_json helpers must use bodyrig.json_io.read_json_object:\n" + "\n".join(offenders)
    assert delegates >= 131, f"expected the slice-3 delegates to remain in place, found {delegates}"


def test_kept_and_exempt_entries_still_exist() -> None:
    for rel in EXEMPT | KEPT:
        assert (ROOT / rel).is_file(), f"entry no longer exists; drop it: {rel}"


def test_kept_helpers_really_differ_from_the_canonical_shape() -> None:
    # A KEPT module must still contain something the shared reader does not do;
    # if it has become canonical, migrate it and remove it from KEPT.
    for rel in sorted(KEPT):
        source = (ROOT / rel).read_text(encoding="utf-8")
        assert "json_io.read_json_object(" not in source, f"{rel} already delegates; remove it from KEPT"
