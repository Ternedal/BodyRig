from pathlib import Path

package_path = Path("bodyrig/package.py")
package_source = package_path.read_text(encoding="utf-8")
old = '''def _num(value: Any, lo: float, hi: float, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not lo <= float(value) <= hi:
        raise MRBodyError(f"bodyprint.{field}: invalid number")
'''
new = '''def _num(value: Any, lo: float, hi: float, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MRBodyError(f"bodyprint.{field}: invalid number")
    try:
        numeric = float(value)
    except OverflowError:
        raise MRBodyError(f"bodyprint.{field}: invalid number") from None
    if not math.isfinite(numeric) or not lo <= numeric <= hi:
        raise MRBodyError(f"bodyprint.{field}: invalid number")
'''
if package_source.count(old) != 1:
    raise SystemExit("expected exactly one canonical _num block")
package_path.write_text(package_source.replace(old, new), encoding="utf-8")

test_path = Path("tests/test_package.py")
test_source = test_path.read_text(encoding="utf-8")
addition = '''\n\ndef test_bodyprint_huge_integer_fails_with_mrbody_error():
    bodyprint = {
        "format": "modelrig-bodyprint",
        "version": 1,
        "motion": {"energy": 10**400},
    }

    with pytest.raises(MRBodyError, match=r"bodyprint\\.motion\\.energy: invalid number"):
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
    entries["checksums.json"] = (json.dumps(checksums, indent=2, sort_keys=True) + "\\n").encode("utf-8")

    with zipfile.ZipFile(crafted, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, data in entries.items():
            target.writestr(name, data)

    with pytest.raises(MRBodyError, match=r"bodyprint\\.motion\\.energy: invalid number"):
        validate_package(crafted)
'''
if "def test_bodyprint_huge_integer_fails_with_mrbody_error" in test_source:
    raise SystemExit("BodyPrint overflow regression already exists")
test_path.write_text(test_source.rstrip() + addition, encoding="utf-8")
