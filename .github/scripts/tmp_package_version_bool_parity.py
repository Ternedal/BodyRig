from pathlib import Path

package_path = Path("bodyrig/package.py")
source = package_path.read_text(encoding="utf-8")

replacements = [
    (
        '    if not isinstance(value, dict) or value.get("format") != "modelrig-bodyprint" or value.get("version") != 1:\n',
        '    if (\n'
        '        not isinstance(value, dict)\n'
        '        or value.get("format") != "modelrig-bodyprint"\n'
        '        or isinstance(value.get("version"), bool)\n'
        '        or value.get("version") != 1\n'
        '    ):\n',
    ),
    (
        '    if value["format"] != FORMAT or value["format_version"] != FORMAT_VERSION:\n',
        '    if value["format"] != FORMAT or isinstance(value["format_version"], bool) or value["format_version"] != FORMAT_VERSION:\n',
    ),
    (
        '    if value["format"] != "modelrig-body-provenance" or value["version"] != 1 or value["synthetic_avatar"] is not True:\n',
        '    if (\n'
        '        value["format"] != "modelrig-body-provenance"\n'
        '        or isinstance(value["version"], bool)\n'
        '        or value["version"] != 1\n'
        '        or value["synthetic_avatar"] is not True\n'
        '    ):\n',
    ),
]

for old, new in replacements:
    if source.count(old) != 1:
        raise SystemExit(f"package validator anchor mismatch: {old!r}")
    source = source.replace(old, new)

package_path.write_text(source, encoding="utf-8", newline="\n")

test_path = Path("tests/test_package.py")
test = test_path.read_text(encoding="utf-8")
marker = "test_portable_numeric_version_rejects_boolean_true"
if marker in test:
    raise SystemExit("version boolean regression already exists unexpectedly")

addition = r'''
def _bodyprint_version_payload(version):
    return {
        "format": "modelrig-bodyprint",
        "version": version,
        "motion": {"energy": 0.5},
    }


def _manifest_version_payload(version):
    return {
        "format": "modelrig-body",
        "format_version": version,
        "id": "version-contract",
        "name": "Version Contract",
        "avatar": {"format": "vrm", "version": "1.0", "path": "avatar.vrm"},
        "bodyprint": "bodyprint.json",
        "provenance": "provenance.json",
        "thumbnail": "thumbnail.png",
        "builder": {"name": "bodyrig", "version": "0.1.0"},
    }


def _provenance_version_payload(version):
    value = dict(PROVENANCE)
    value["version"] = version
    value["source"] = dict(PROVENANCE["source"])
    value["pipeline"] = [dict(item) for item in PROVENANCE["pipeline"]]
    return value


@pytest.mark.parametrize(
    ("validator", "payload"),
    [
        (package_module.validate_bodyprint, _bodyprint_version_payload(True)),
        (package_module.validate_manifest, _manifest_version_payload(True)),
        (package_module.validate_provenance, _provenance_version_payload(True)),
    ],
)
def test_portable_numeric_version_rejects_boolean_true(validator, payload):
    with pytest.raises(MRBodyError):
        validator(payload)


@pytest.mark.parametrize(
    ("validator", "payload"),
    [
        (package_module.validate_bodyprint, _bodyprint_version_payload(1.0)),
        (package_module.validate_manifest, _manifest_version_payload(1.0)),
        (package_module.validate_provenance, _provenance_version_payload(1.0)),
    ],
)
def test_portable_numeric_version_preserves_schema_numeric_equality(validator, payload):
    assert validator(payload) is payload


@pytest.mark.parametrize(
    ("filename", "field"),
    [
        ("manifest.json", "format_version"),
        ("bodyprint.json", "version"),
        ("provenance.json", "version"),
    ],
)
def test_package_read_rejects_boolean_version_constants(tmp_path: Path, filename: str, field: str):
    package = make_package(tmp_path / "source.mrbody")
    crafted = tmp_path / f"boolean-version-{filename.replace('.', '-')}.mrbody"

    with zipfile.ZipFile(package, "r") as source:
        entries = {info.filename: source.read(info.filename) for info in source.infolist()}

    document = json.loads(entries[filename].decode("utf-8"))
    document[field] = True
    document_bytes = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    entries[filename] = document_bytes

    if filename in {"bodyprint.json", "provenance.json"}:
        checksums = json.loads(entries["checksums.json"].decode("utf-8"))
        checksums[filename] = hashlib.sha256(document_bytes).hexdigest()
        entries["checksums.json"] = (json.dumps(checksums, indent=2, sort_keys=True) + "\n").encode("utf-8")

    with zipfile.ZipFile(crafted, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, data in entries.items():
            target.writestr(name, data)

    with pytest.raises(MRBodyError):
        validate_package(crafted)
'''

test_path.write_text(test.rstrip() + "\n\n\n" + addition.strip("\n") + "\n", encoding="utf-8", newline="\n")
