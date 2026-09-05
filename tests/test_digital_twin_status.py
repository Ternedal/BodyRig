from bodyrig.digital_twin_status import DigitalTwinStatusError, inspect_digital_twin_status


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def _assembly() -> dict:
    return {
        "format": "bodyrig-person-assembly-receipt",
        "version": 2,
        "person_id": "person-0123456789abcdef0123456789abcdef",
        "person_revision": "person-r0001",
        "assembly_fingerprint": SHA_A,
        "body": {
            "revision_id": "body-r0001",
            "body_id": "body-0123456789abcdef0123456789abcdef",
            "package_sha256": SHA_B,
        },
        "voice": {
            "revision_id": "voice-r0001",
            "voice_id": "voice-0123456789abcdef0123456789abcdef",
            "voice_package": "voice-a.voice",
            "package_sha256": SHA_C,
        },
        "personality": {
            "revision_id": "personality-r0001",
            "instructions_sha256": SHA_D,
            "default_language": "da-DK",
            "style_notes_sha256": SHA_E,
        },
        "audition": {
            "audition_id": "audition-0123456789abcdef0123456789abcdef",
            "receipt_sha256": SHA_F,
        },
    }


def _body_release() -> dict:
    return {"production_ready": True, "production_activation": True}


def _hands_nails() -> dict:
    return {
        "state": "complete",
        "source_grounded": True,
        "hand_geometry_review_passed": True,
        "foot_geometry_review_passed": True,
        "skin_detail_review_passed": True,
        "fingernails_review_passed": True,
        "toenails_review_passed": True,
        "production_activation": False,
    }


def _wardrobe() -> dict:
    return {
        "state": "complete",
        "source_grounded": True,
        "garment_geometry_review_passed": True,
        "material_review_passed": True,
        "layering_review_passed": True,
        "attachment_review_passed": True,
        "deformation_review_passed": True,
        "production_activation": False,
    }


def _embodiment() -> dict:
    return {
        "state": "complete",
        "motion_authority": True,
        "expression_authority": True,
        "voice_timing_authority": True,
        "production_activation": False,
    }


def test_body_release_alone_is_not_a_full_digital_twin() -> None:
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
    )

    assert status["avatar_ready"] is True
    assert status["digital_twin_release_eligible"] is False
    assert status["digital_twin_ready"] is False
    assert status["production_activation"] is False
    assert status["next_gate"] == "hands_feet_nails"
    assert status["gates"]["hands_feet_nails"]["state"] == "missing"
    assert status["gates"]["wardrobe"]["state"] == "missing"
    assert status["gates"]["embodiment"]["state"] == "missing"


def test_all_subsystem_authorities_only_make_twin_release_eligible() -> None:
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        hands_nails_authority=_hands_nails(),
        wardrobe_authority=_wardrobe(),
        embodiment_authority=_embodiment(),
    )

    assert status["avatar_ready"] is True
    assert status["digital_twin_release_eligible"] is True
    assert status["digital_twin_ready"] is False
    assert status["production_activation"] is False
    assert status["final_release_implemented"] is False
    assert status["next_gate"] == "digital_twin_final_release"


def test_nails_cannot_be_incidental_texture_only() -> None:
    hands = _hands_nails()
    hands["fingernails_review_passed"] = False

    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        hands_nails_authority=hands,
        wardrobe_authority=_wardrobe(),
        embodiment_authority=_embodiment(),
    )

    assert status["digital_twin_release_eligible"] is False
    assert status["next_gate"] == "hands_feet_nails"
    assert "hands/feet/nails did not pass fingernails_review_passed" in status["blockers"]


def test_wardrobe_requires_real_deformation_review() -> None:
    wardrobe = _wardrobe()
    wardrobe["deformation_review_passed"] = False

    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        hands_nails_authority=_hands_nails(),
        wardrobe_authority=wardrobe,
        embodiment_authority=_embodiment(),
    )

    assert status["digital_twin_release_eligible"] is False
    assert status["next_gate"] == "wardrobe"
    assert "wardrobe/clothing did not pass deformation_review_passed" in status["blockers"]


def test_component_authority_cannot_activate_production_independently() -> None:
    wardrobe = _wardrobe()
    wardrobe["production_activation"] = True

    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        hands_nails_authority=_hands_nails(),
        wardrobe_authority=wardrobe,
        embodiment_authority=_embodiment(),
    )

    assert status["digital_twin_release_eligible"] is False
    assert "wardrobe/clothing component authority must remain non-activating before final digital-twin release" in status["blockers"]


def test_legacy_person_assembly_receipt_is_not_twin_authority() -> None:
    assembly = _assembly()
    assembly["version"] = 1

    try:
        inspect_digital_twin_status(
            assembly_receipt=assembly,
            body_release_status=_body_release(),
        )
    except DigitalTwinStatusError as exc:
        assert "audition-bound Person assembly receipt" in str(exc)
    else:
        raise AssertionError("legacy assembly receipt unexpectedly became digital-twin authority")
