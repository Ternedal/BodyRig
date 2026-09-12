from pathlib import Path

package_path = Path("bodyrig/package.py")
source = package_path.read_text(encoding="utf-8")
old = '''def _num(value: Any, lo: float, hi: float, field: str) -> None:\n    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not lo <= float(value) <= hi:\n        raise MRBodyError(f"bodyprint.{field}: invalid number")\n'''
new = '''def _num(value: Any, lo: float, hi: float, field: str) -> None:\n    if isinstance(value, bool) or not isinstance(value, (int, float)):\n        raise MRBodyError(f"bodyprint.{field}: invalid number")\n    if isinstance(value, float) and not math.isfinite(value):\n        raise MRBodyError(f"bodyprint.{field}: invalid number")\n    if not lo <= value <= hi:\n        raise MRBodyError(f"bodyprint.{field}: invalid number")\n'''
if source.count(old) != 1:
    raise SystemExit("BodyPrint numeric validator anchor mismatch")
package_path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")

test_path = Path("tests/test_package.py")
test = test_path.read_text(encoding="utf-8")
marker = "def test_bodyprint_huge_integer_fails_with_mrbody_error"
if marker in test:
    raise SystemExit("overflow regression already exists unexpectedly")
addition = r'''


@pytest.mark.parametrize("value", [10**400, -(10**400)])
def test_bodyprint_huge_integer_fails_with_mrbody_error(value):
    bodyprint = {
        "format": "modelrig-bodyprint",
        "version": 1,
        "motion": {"energy": value},
    }

    with pytest.raises(MRBodyError, match=r"bodyprint\.motion\.energy: invalid number"):
        package_module.validate_bodyprint(bodyprint)


def test_package_huge_bodyprint_integer_fails_with_mrbody_error(tmp_path: Path):
    package = make_package(tmp_path / "source.mrbody")
    crafted = tmp_path / "huge-number.mrbody"

    with zipfile.ZipFile(package, "r") as source:
        entries = {info.filename: source.read(info.filename) for info in source.infolist()}

    bodyprint = {
        "format": "modelrig-bodyprint",
        "version": 1,
        "motion": {"energy": 10**400},
    }
    bodyprint_bytes = json.dumps(bodyprint, separators=(",", ":"), sort_keys=True).encode("utf-8")
    entries["bodyprint.json"] = bodyprint_bytes
    checksums = json.loads(entries["checksums.json"].decode("utf-8"))
    checksums["bodyprint.json"] = hashlib.sha256(bodyprint_bytes).hexdigest()
    entries["checksums.json"] = (json.dumps(checksums, indent=2, sort_keys=True) + "\n").encode("utf-8")

    with zipfile.ZipFile(crafted, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, data in entries.items():
            target.writestr(name, data)

    with pytest.raises(MRBodyError, match=r"bodyprint\.motion\.energy: invalid number"):
        validate_package(crafted)
'''
test_path.write_text(test.rstrip() + addition + "\n", encoding="utf-8", newline="\n")
