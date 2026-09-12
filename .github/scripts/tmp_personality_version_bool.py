from pathlib import Path

source_path = Path("bodyrig/personality_blueprint.py")
source = source_path.read_text(encoding="utf-8")
old = '    if value.get("format") != FORMAT or value.get("version") != VERSION:\n'
new = '    if value.get("format") != FORMAT or isinstance(value.get("version"), bool) or value.get("version") != VERSION:\n'
if source.count(old) != 1:
    raise SystemExit("personality version anchor mismatch")
source_path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")

unit_path = Path("tests/test_personality_blueprint.py")
unit = unit_path.read_text(encoding="utf-8")
marker = "test_blueprint_rejects_boolean_version_constant"
if marker in unit:
    raise SystemExit("version boolean unit regressions already exist")
unit_addition = r'''
def test_blueprint_rejects_boolean_version_constant() -> None:
    value = build_blueprint(default_language="da", communication=communication())
    value["version"] = True
    with pytest.raises(PersonalityBlueprintError, match="format/version"):
        validate_blueprint(value)


def test_blueprint_preserves_schema_numeric_version_equality() -> None:
    value = build_blueprint(default_language="da", communication=communication())
    value["version"] = 1.0
    assert validate_blueprint(value)["version"] == 1
'''
unit_path.write_text(unit.rstrip() + "\n\n\n" + unit_addition.strip() + "\n", encoding="utf-8", newline="\n")

binding_path = Path("tests/test_personality_embodiment_binding.py")
binding = binding_path.read_text(encoding="utf-8")
marker = "test_persisted_blueprint_boolean_version_fails_closed"
if marker in binding:
    raise SystemExit("persisted version boolean regression already exists")
binding_addition = r'''
def test_persisted_blueprint_boolean_version_fails_closed(tmp_path: Path) -> None:
    person_id = "person-" + "a" * 32
    blueprint = _blueprint()
    digest = blueprint_sha256(blueprint)
    blueprint["version"] = True
    path = tmp_path / "personality-blueprints" / person_id / f"{digest}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(blueprint), encoding="utf-8")

    with pytest.raises(PersonalityEmbodimentBindingError, match="blueprint evidence is invalid"):
        read_blueprint_evidence(tmp_path, person_id=person_id, digest=digest)
'''
binding_path.write_text(binding.rstrip() + "\n\n\n" + binding_addition.strip() + "\n", encoding="utf-8", newline="\n")
