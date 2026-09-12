from pathlib import Path

blueprint = Path("bodyrig/personality_blueprint.py")
text = blueprint.read_text(encoding="utf-8")
old = '''def _ratio(value: Any, *, field: str) -> float:\n    if (\n        isinstance(value, bool)\n        or not isinstance(value, (int, float))\n        or not math.isfinite(float(value))\n        or not 0.0 <= float(value) <= 1.0\n    ):\n        raise PersonalityBlueprintError(f"{field} must be a finite number in 0..1")\n    return float(value)\n'''
new = '''def _ratio(value: Any, *, field: str) -> float:\n    if isinstance(value, bool) or not isinstance(value, (int, float)):\n        raise PersonalityBlueprintError(f"{field} must be a finite number in 0..1")\n    try:\n        numeric = float(value)\n    except OverflowError:\n        raise PersonalityBlueprintError(f"{field} must be a finite number in 0..1") from None\n    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:\n        raise PersonalityBlueprintError(f"{field} must be a finite number in 0..1")\n    return numeric\n'''
if text.count(old) != 1:
    raise SystemExit("personality _ratio source needle did not match exactly once")
blueprint.write_text(text.replace(old, new), encoding="utf-8")

bp_tests = Path("tests/test_personality_blueprint.py")
text = bp_tests.read_text(encoding="utf-8")
append = '''\n\ndef test_blueprint_rejects_huge_integer_ratio_with_domain_error() -> None:\n    value = build_blueprint(\n        default_language="da",\n        communication=communication(),\n    )\n    value["communication"]["warmth"] = 10**400\n\n    with pytest.raises(\n        PersonalityBlueprintError,\n        match=r"communication\\.warmth must be a finite number in 0\\.\\.1",\n    ):\n        validate_blueprint(value)\n\n\ndef test_blueprint_ratio_boundaries_remain_inclusive() -> None:\n    value = build_blueprint(\n        default_language="da",\n        communication=communication(directness=0.0, warmth=1.0),\n    )\n\n    assert value["communication"]["directness"] == 0.0\n    assert value["communication"]["warmth"] == 1.0\n'''
if "test_blueprint_rejects_huge_integer_ratio_with_domain_error" not in text:
    bp_tests.write_text(text.rstrip() + append + "\n", encoding="utf-8")

binding_tests = Path("tests/test_personality_embodiment_binding.py")
text = binding_tests.read_text(encoding="utf-8")
append = '''\n\ndef test_persisted_blueprint_huge_ratio_is_normalized_to_binding_error(tmp_path: Path) -> None:\n    person_id = "person-" + "a" * 32\n    blueprint = _blueprint()\n    digest = blueprint_sha256(blueprint)\n    blueprint["communication"]["warmth"] = 10**400\n    path = tmp_path / "personality-blueprints" / person_id / f"{digest}.json"\n    path.parent.mkdir(parents=True)\n    path.write_text(json.dumps(blueprint), encoding="utf-8")\n\n    with pytest.raises(\n        PersonalityEmbodimentBindingError,\n        match="bound personality blueprint evidence is invalid",\n    ):\n        read_blueprint_evidence(tmp_path, person_id=person_id, digest=digest)\n'''
if "test_persisted_blueprint_huge_ratio_is_normalized_to_binding_error" not in text:
    binding_tests.write_text(text.rstrip() + append + "\n", encoding="utf-8")
