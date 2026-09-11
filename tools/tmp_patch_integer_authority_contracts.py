from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "integer": ROOT / "tests" / "test_reference_renderer_integer_schema_parity.py",
    "guard": ROOT / "tests" / "test_reference_renderer_json_utility_guard.py",
    "ranges": ROOT / "tests" / "test_reference_renderer_raw_numeric_ranges.py",
    "speech": ROOT / "tests" / "test_reference_renderer_speech_state_guard.py",
}


def replace_all_exact(path: Path, replacements: list[tuple[str, str, int]]) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new, expected in replacements:
        count = text.count(old)
        if count != expected:
            raise SystemExit(f"{path.name}: expected {expected} matches for {old!r}, got {count}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


replace_all_exact(
    FILES["integer"],
    [
        ("private static void RequireIntegerRangeToken", "private static int RequireIntegerRangeToken", 2),
        ("private static void ValidateDuration", "private static int? ValidateDuration", 1),
        ("private static void ValidateSpeech", "private static int? ValidateSpeech", 1),
    ],
)

replace_all_exact(
    FILES["guard"],
    [
        ("private static void ValidateDuration", "private static int? ValidateDuration", 1),
        ("private static void ValidateSpeech", "private static int? ValidateSpeech", 1),
        ("assert 'ValidateDuration(root);' in validate", "assert 'validatedDurationMs = ValidateDuration(root);' in validate", 1),
    ],
)

replace_all_exact(
    FILES["ranges"],
    [
        ("private static void ValidateSpeech", "private static int? ValidateSpeech", 1),
        ("private static void RequireIntegerRangeToken", "private static int RequireIntegerRangeToken", 1),
    ],
)

replace_all_exact(
    FILES["speech"],
    [("private static void ValidateSpeech", "private static int? ValidateSpeech", 1)],
)
