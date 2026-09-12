from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    with path.open("r", encoding="utf-8", newline="") as stream:
        text = stream.read()
    newline = "\r\n" if "\r\n" in text else "\n"
    old_native = old.replace("\n", newline)
    new_native = new.replace("\n", newline)
    count = text.count(old_native)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one anchor, found {count}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(text.replace(old_native, new_native, 1))


package = Path("bodyrig/package.py")
replace_once(
    package,
    '''def _num(value: Any, lo: float, hi: float, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not lo <= float(value) <= hi:
        raise MRBodyError(f"bodyprint.{field}: invalid number")
''',
    '''def _num(value: Any, lo: float, hi: float, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MRBodyError(f"bodyprint.{field}: invalid number")
    try:
        numeric = float(value)
    except OverflowError:
        raise MRBodyError(f"bodyprint.{field}: invalid number") from None
    if not math.isfinite(numeric) or not lo <= numeric <= hi:
        raise MRBodyError(f"bodyprint.{field}: invalid number")
''',
)

# Prove the post-#401 integration retained the exclusive height_scale boundary.
package_text = package.read_text(encoding="utf-8")
for marker in (
    '"height_scale": (0.0, 4.0)',
    'key == "height_scale" and float(item) <= 0.0',
    'pipeline_text_limits = {"stage": 80, "adapter": 120, "revision": 160}',
):
    if marker not in package_text:
        raise SystemExit(f"post-#401 package marker missing after overflow patch: {marker}")

test = Path("tests/test_package.py")
with test.open("r", encoding="utf-8", newline="") as stream:
    text = stream.read()
newline = "\r\n" if "\r\n" in text else "\n"
block = '''

def test_bodyprint_huge_integer_fails_with_mrbody_error():
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
'''.replace("\n", newline)
if "def test_bodyprint_huge_integer_fails_with_mrbody_error" in text:
    raise SystemExit("overflow tests already present unexpectedly")
with test.open("w", encoding="utf-8", newline="") as stream:
    stream.write(text.rstrip("\r\n") + block + newline)
