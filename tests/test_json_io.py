"""bodyrig.json_io.read_json_object implements docs/JSON_EVIDENCE_READ_POLICY.md.

The historical 131 `_read_json` copies were compositions of four knobs; the
oracle here is the strictest historical shape (utf-8-sig, NaN rejected, dict
required, the module error raised with the module message), which every
migrated module now shares.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig import json_io
from bodyrig.json_io import read_json_object


class ModuleError(ValueError):
    pass


def _historical_strict(path: Path) -> dict:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ModuleError("unreadable") from exc
    if not isinstance(value, dict):
        raise ModuleError("not object")
    return value


def _read(path: Path) -> dict:
    return read_json_object(path, error=ModuleError, unreadable="unreadable", not_object="not object")


def test_reads_objects_with_and_without_bom(tmp_path: Path) -> None:
    plain = tmp_path / "plain.json"
    plain.write_text('{"a": 1, "b": [1, 2.5, "ø"], "c": {"d": null}}', encoding="utf-8")
    bom = tmp_path / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf" + plain.read_bytes())
    expected = {"a": 1, "b": [1, 2.5, "ø"], "c": {"d": None}}
    assert _read(plain) == expected
    assert _read(bom) == expected
    assert _read(str(plain)) == expected
    assert _historical_strict(bom) == expected


@pytest.mark.parametrize("text", ["NaN", "Infinity", "-Infinity", '{"x": NaN}', '{"x": [Infinity]}'])
def test_non_finite_tokens_are_unreadable(tmp_path: Path, text: str) -> None:
    path = tmp_path / "nan.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ModuleError, match="^unreadable$") as info:
        _read(path)
    assert isinstance(info.value.__cause__, ValueError)
    with pytest.raises(ModuleError, match="^unreadable$"):
        _historical_strict(path)


@pytest.mark.parametrize("text", ["[1, 2]", "1", '"text"', "null", "true"])
def test_non_object_documents_fail_with_the_not_object_message(tmp_path: Path, text: str) -> None:
    path = tmp_path / "scalar.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ModuleError, match="^not object$"):
        _read(path)
    with pytest.raises(ModuleError, match="^not object$"):
        _historical_strict(path)


def test_read_decode_and_parse_failures_are_unreadable_and_chained(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ModuleError, match="^unreadable$") as info:
        _read(missing)
    assert isinstance(info.value.__cause__, FileNotFoundError)
    with pytest.raises(ModuleError, match="^unreadable$") as info:
        _read(tmp_path)  # a directory
    assert isinstance(info.value.__cause__, OSError)
    broken = tmp_path / "broken.json"
    broken.write_bytes(b'{"a": "\xff\xfe"}')
    with pytest.raises(ModuleError, match="^unreadable$") as info:
        _read(broken)
    assert isinstance(info.value.__cause__, UnicodeDecodeError)
    truncated = tmp_path / "truncated.json"
    truncated.write_text('{"a": ', encoding="utf-8")
    with pytest.raises(ModuleError, match="^unreadable$") as info:
        _read(truncated)
    assert isinstance(info.value.__cause__, json.JSONDecodeError)


def test_messages_and_error_class_are_the_callers(tmp_path: Path) -> None:
    class OtherError(RuntimeError):
        pass

    path = tmp_path / "list.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(OtherError, match="^evidence X must be a JSON object$"):
        read_json_object(path, error=OtherError, unreadable="evidence X is unreadable", not_object="evidence X must be a JSON object")
    with pytest.raises(OtherError, match="^evidence X is unreadable$"):
        read_json_object(tmp_path / "nope.json", error=OtherError, unreadable="evidence X is unreadable", not_object="evidence X must be a JSON object")


def test_huge_integers_still_parse_so_metric_checks_keep_their_own_messages(tmp_path: Path) -> None:
    # 10**400 is a valid JSON number and a Python int; it is the caller's
    # numeric validation that rejects it, not the reader.
    path = tmp_path / "big.json"
    path.write_text('{"metric": ' + str(10**400) + "}", encoding="utf-8")
    assert _read(path)["metric"] == 10**400


def test_module_is_standard_library_only() -> None:
    import ast

    source = Path(json_io.__file__).read_text(encoding="utf-8")
    modules = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    assert modules == {"__future__", "json", "pathlib", "typing"}
