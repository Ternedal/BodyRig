from pathlib import Path

source_path = Path("bodyrig/personality_blueprint.py")
source = source_path.read_text(encoding="utf-8")
old_ratio = '''def _ratio(value: Any, *, field: str) -> float:\n    if (\n        isinstance(value, bool)\n        or not isinstance(value, (int, float))\n        or not math.isfinite(float(value))\n        or not 0.0 <= float(value) <= 1.0\n    ):\n        raise PersonalityBlueprintError(f"{field} must be a finite number in 0..1")\n    return float(value)\n'''
new_ratio = '''def _ratio(value: Any, *, field: str) -> float:\n    if isinstance(value, bool) or not isinstance(value, (int, float)):\n        raise PersonalityBlueprintError(f"{field} must be a finite number in 0..1")\n    try:\n        numeric = float(value)\n    except OverflowError:\n        raise PersonalityBlueprintError(f"{field} must be a finite number in 0..1") from None\n    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:\n        raise PersonalityBlueprintError(f"{field} must be a finite number in 0..1")\n    return numeric\n'''
if source.count(old_ratio) != 1:
    raise SystemExit("personality ratio anchor mismatch")
source = source.replace(old_ratio, new_ratio)
old_version = '    if value.get("format") != FORMAT or value.get("version") != VERSION:\n'
new_version = '    if value.get("format") != FORMAT or isinstance(value.get("version"), bool) or value.get("version") != VERSION:\n'
if source.count(old_version) != 1:
    raise SystemExit("personality version anchor mismatch")
source = source.replace(old_version, new_version)
source_path.write_text(source, encoding="utf-8", newline="\n")

unit_path = Path("tests/test_personality_blueprint.py")
unit = unit_path.read_text(encoding="utf-8")
marker = "test_blueprint_rejects_boolean_version_constant"
if marker in unit:
    raise SystemExit("personality boundary unit regressions already exist")
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


@pytest.mark.parametrize(
    ("section", "field"),
    [("communication", "warmth"), ("embodiment", "movement_energy")],
)
def test_blueprint_huge_ratio_fails_with_domain_error(section: str, field: str) -> None:
    value = build_blueprint(default_language="da", communication=communication())
    value[section][field] = 10**400
    with pytest.raises(PersonalityBlueprintError, match=rf"{section}\.{field} must be a finite number in 0\.\.1"):
        validate_blueprint(value)


def test_blueprint_ratio_boundaries_remain_inclusive() -> None:
    value = build_blueprint(default_language="da", communication=communication())
    value["communication"]["directness"] = 0
    value["embodiment"]["gaze_strength"] = 1
    validated = validate_blueprint(value)
    assert validated["communication"]["directness"] == 0.0
    assert validated["embodiment"]["gaze_strength"] == 1.0
'''
unit_path.write_text(unit.rstrip() + unit_addition + "\n", encoding="utf-8", newline="\n")

binding_path = Path("tests/test_personality_embodiment_binding.py")
binding = binding_path.read_text(encoding="utf-8")
binding_marker = "test_persisted_blueprint_huge_ratio_fails_closed"
if binding_marker in binding:
    raise SystemExit("persisted personality boundary regression already exists")
binding_addition = r'''


def test_persisted_blueprint_huge_ratio_fails_closed(tmp_path: Path) -> None:
    person_id = "person-" + "a" * 32
    digest = "f" * 64
    blueprint = _blueprint()
    blueprint["communication"]["warmth"] = 10**400
    path = tmp_path / "personality-blueprints" / person_id / f"{digest}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(blueprint), encoding="utf-8")

    with pytest.raises(PersonalityEmbodimentBindingError, match="blueprint evidence is invalid"):
        read_blueprint_evidence(tmp_path, person_id=person_id, digest=digest)
'''
binding_path.write_text(binding.rstrip() + binding_addition + "\n", encoding="utf-8", newline="\n")
