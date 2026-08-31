from pathlib import Path


def test_guided_body_grounding_hashes_large_packages_streaming() -> None:
    source = Path("bodyrig/personality_authoring.py").read_text(encoding="utf-8")

    assert 'handle.read(1024 * 1024)' in source
    assert "package.read_bytes()" not in source
    assert "_sha256_file(package)" in source
