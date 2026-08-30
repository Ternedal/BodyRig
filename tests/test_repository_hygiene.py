from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_python_bytecode_is_git_ignored_for_physical_postflight_cleanliness():
    rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "__pycache__/" in rules
    assert "*.py[cod]" in rules
