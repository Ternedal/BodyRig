"""Pure private SHA-256 helpers delegate to bodyrig.hashing instead of re-growing.

Slice 1 of #1386 recommendation B replaced every pure, output-identical copy
of the three helpers in modules that already import bodyrig. This contract
keeps the class closed: a new module may still define `_sha256_file` for a
module-specific fail-closed wrapper (checks, error class, message), but a
body that is just the historical streaming loop, the whole-buffer hash or
the canonical JSON digest must call bodyrig.hashing.

Standalone modules (no bodyrig import, because they run inside external
environments) and the modules listed in EXEMPT keep their own copies on
purpose.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_NAMES = {"_sha256", "_sha256_file", "_sha", "_digest", "_file_sha", "_sha256_bytes", "_file_sha256", "_sha256_path", "_hash_file"}
EXEMPT = {
    # streaming body pinned by tests/test_personality_authoring_source_contract.py
    "bodyrig/personality_authoring.py",
    # owned by open PRs (#1372, #1377); migrate once those land
    "bodyrig/photoreal_exavatar_fit_diagnostic.py",
    "bodyrig/stash_source.py",
    "bodyrig/stash_fidelity_reference.py",
    "bodyrig/hashing.py",
}
# Streaming loops that legitimately do more than hash (progress reporting).
STREAMING_LOOP_EXEMPT = EXEMPT | {
    "bodyrig/photoreal_source_verify.py",
}
RE_STREAMING_LOOP_ANYWHERE = re.compile(
    r"hashlib\.sha256\(\)[\s\S]{0,400}?\.open\(\"rb\"\)[\s\S]{0,300}?\.read\([^)]*\)[\s\S]{0,200}?\.update\("
)

RE_BYTES = re.compile(r"^return hashlib\.sha256\(\w+\)\.hexdigest\(\)$")
RE_READBYTES = re.compile(r"^return hashlib\.sha256\(\w+\.read_bytes\(\)\)\.hexdigest\(\)$")
RE_STREAM = re.compile(
    r"^(?P<d>\w+) = hashlib\.sha256\(\)\nwith \w+\.open\(\"rb\"\) as (?P<h>\w+):\n"
    r"for (?P<c>\w+) in iter\(lambda: (?P=h)\.read\([0-9 *]+\), b\"\"\):\n(?P=d)\.update\((?P=c)\)\nreturn (?P=d)\.hexdigest\(\)$"
)
RE_JSON = re.compile(
    r"^(?:payload=\{key:itemforkey,itemin\w+\.items\(\)ifkey!=omit\})?"
    r"(?P<e>\w+)=json\.dumps\(\w+,[^)]*allow_nan=False[^)]*\)\.encode\(\"utf-8\"\)returnhashlib\.sha256\((?P=e)\)\.hexdigest\(\)$"
)


def _imports_bodyrig(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and ((node.module or "").split(".")[0] == "bodyrig" or (node.level or 0) > 0):
            return True
        if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "bodyrig" for alias in node.names):
            return True
    return False


def _normalised_body(source: str, node: ast.FunctionDef) -> str:
    lines = ast.get_source_segment(source, node).splitlines()[1:]
    return "\n".join(line.strip() for line in lines if line.strip())


def _is_pure_copy(body: str) -> bool:
    if RE_BYTES.match(body) or RE_READBYTES.match(body) or RE_STREAM.match(body):
        return True
    return RE_JSON.match(re.sub(r"\s+", "", body)) is not None


def test_pure_private_sha_helpers_delegate_to_shared_module() -> None:
    offenders: list[str] = []
    delegates = 0
    for path in sorted((ROOT / "bodyrig").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in EXEMPT:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        if not _imports_bodyrig(tree):
            continue  # standalone by design; bodyrig is not importable where it runs
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name not in PRIVATE_NAMES:
                continue
            body = _normalised_body(source, node)
            if _is_pure_copy(body):
                offenders.append(f"{rel}:{node.lineno} {node.name}")
            elif body.startswith("return hashing."):
                delegates += 1
    assert offenders == [], "pure SHA-256 helpers must delegate to bodyrig.hashing:\n" + "\n".join(offenders)
    assert delegates >= 99, f"expected the slice-1 delegates to remain in place, found {delegates}"


def test_no_streaming_sha256_loop_outside_the_shared_module() -> None:
    """Slice 2: helpers that keep checks/error wrapping still delegate the streaming part."""
    offenders: list[str] = []
    for path in sorted((ROOT / "bodyrig").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in STREAMING_LOOP_EXEMPT:
            continue
        source = path.read_text(encoding="utf-8")
        if not _imports_bodyrig(ast.parse(source)):
            continue
        for match in RE_STREAMING_LOOP_ANYWHERE.finditer(source):
            offenders.append(f"{rel}:{source[: match.start()].count(chr(10)) + 1}")
    assert offenders == [], "streaming SHA-256 loops must use bodyrig.hashing.sha256_file:\n" + "\n".join(offenders)


def test_exempt_modules_still_exist_or_are_removed_from_the_list() -> None:
    for rel in STREAMING_LOOP_EXEMPT:
        assert (ROOT / rel).is_file(), f"EXEMPT entry no longer exists; drop it: {rel}"
