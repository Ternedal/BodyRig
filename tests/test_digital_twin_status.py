from bodyrig.digital_twin_status import DigitalTwinStatusError, inspect_digital_twin_status
from bodyrig.hands_feet_nails_authority import (
    CHECKLIST_FIELDS,
    FORMAT as REVIEW_FORMAT,
    POLICY_REVISION as REVIEW_POLICY,
    _review_id,
)
from bodyrig.hands_feet_nails_release_authority import (
    FORMAT as HFN_FORMAT,
    POLICY_REVISION as HFN_POLICY,
    _release_id,
)
from bodyrig.wardrobe_authority import CHECKLIST_FIELDS as WARDROBE_CHECKLIST_FIELDS
from bodyrig.wardrobe_release_authority import (
    FORMAT as WARDROBE_FORMAT,
    POLICY_REVISION as WARDROBE_POLICY,
    _release_id as _wardrobe_release_id,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
SHA_G = "1" * 64
BODYRIG_REVISION = "1" * 40
PERSON_ID = "person-0123456789abcdef0123456789abcdef"
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
BODY_ID = "body-0123456789abcdef0123456789abcdef"


def _assembly() -> dict:
    return {
        "format": "bodyrig-person-assembly-receipt",
        "version": 2,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": SHA_A,
        "body": {"revision_id": BODY_REVISION, "body_id": BODY_ID, "package_sha256": SHA_B},
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
        "audition": {"audition_id": "audition-0123456789abcdef0123456789abcdef", "receipt_sha256": SHA_F},
    }


def _body_release() -> dict:
    return {
        "format": "bodyrig-person-release-status",
        "version": 1,
        "person_id": PERSON_ID,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "package_sha256": SHA_G,
        "production_ready": True,
        "production_activation": True,
    }


def _review_identity() -> tuple[str, str, str]:
    source_capture_sha = "2" * 64
    render_manifest_sha = "3" * 64
    review_id = _review_id(
        person_id=PERSON_ID,
        person_revision=PERSON_REVISION,
        assembly_fingerprint=SHA_A,
        body_package_sha256=SHA_G,
        bodyrig_revision=BODYRIG_REVISION,
        source_capture_sha256=source_capture_sha,
        render_manifest_sha256=render_manifest_sha,
    )
    return review_id, source_capture_sha, render_manifest_sha


def _hands_nails() -> dict:
    review_id, source_capture_sha, render_manifest_sha = _review_identity()
    review_authority_sha = "d" * 64
    render_authority_sha = "e" * 64
    comparison_authority_sha = "f" * 64
    release_id = _release_id(
        review_id=review_id,
        review_authority_sha256=review_authority_sha,
        render_authority_sha256=render_authority_sha,
        comparison_authority_sha256=comparison_authority_sha,
        body_package_sha256=SHA_G,
        bodyrig_revision=BODYRIG_REVISION,
    )
    checklist = {field: True for field in CHECKLIST_FIELDS}
    return {
        "format": HFN_FORMAT,
        "version": 1,
        "policy_revision": HFN_POLICY,
        "release_id": release_id,
        "review_id": review_id,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": SHA_A,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": SHA_G,
        "bodyrig_revision": BODYRIG_REVISION,
        "review_authority_sha256": review_authority_sha,
        "source_capture_id": "hfncap-0123456789abcdef0123456789abcdef",
        "source_capture_sha256": source_capture_sha,
        "source_manifest_sha256": "4" * 64,
        "source_region_sha256": {"left_hand": "5" * 64, "right_hand": "6" * 64, "left_foot": "7" * 64, "right_foot": "8" * 64},
        "render_authority_sha256": render_authority_sha,
        "comparison_authority_sha256": comparison_authority_sha,
        "runtime_manifest_sha256": "9" * 64,
        "render_manifest_sha256": render_manifest_sha,
        "render_region_sha256": {"left_hand": "a" * 64, "right_hand": "b" * 64, "left_foot": "c" * 64, "right_foot": "0" * 64},
        "finalized_utc": "2026-09-05T18:00:00Z",
        "state": "complete",
        "source_grounded": True,
        "operator_supplied": True,
        **checklist,
        "production_activation": False,
    }


def _raw_review() -> dict:
    review_id, source_capture_sha, render_manifest_sha = _review_identity()
    checklist = {field: True for field in CHECKLIST_FIELDS}
    return {
        "format": REVIEW_FORMAT,
        "version": 1,
        "policy_revision": REVIEW_POLICY,
        "review_id": review_id,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": SHA_A,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": SHA_G,
        "bodyrig_revision": BODYRIG_REVISION,
        "source_capture_id": "hfncap-0123456789abcdef0123456789abcdef",
        "source_capture_sha256": source_capture_sha,
        "source_manifest_sha256": "4" * 64,
        "source_region_sha256": {"left_hand": "5" * 64, "right_hand": "6" * 64, "left_foot": "7" * 64, "right_foot": "8" * 64},
        "render_manifest_sha256": render_manifest_sha,
        "render_region_sha256": {"left_hand": "a" * 64, "right_hand": "b" * 64, "left_foot": "c" * 64, "right_foot": "0" * 64},
        "reviewed_utc": "2026-09-05T18:00:00Z",
        "checklist": checklist,
        "quality_note": "Real source-vs-render review.",
        "state": "complete",
        "source_grounded": True,
        "operator_supplied": True,
        **checklist,
        "production_activation": False,
    }


def _wardrobe() -> dict:
    review_id = "wardreview-0123456789abcdef0123456789abcdef"
    review_sha = "2" * 64
    render_sha = "3" * 64
    lineage_sha = "4" * 64
    deformation_sha = "5" * 64
    release_id = _wardrobe_release_id(
        review_id=review_id,
        review_authority_sha256=review_sha,
        render_authority_sha256=render_sha,
        package_lineage_sha256=lineage_sha,
        deformation_probe_sha256=deformation_sha,
        body_package_sha256=SHA_G,
        bodyrig_revision=BODYRIG_REVISION,
    )
    checklist = {field: True for field in WARDROBE_CHECKLIST_FIELDS}
    return {
        "format": WARDROBE_FORMAT,
        "version": 1,
        "policy_revision": WARDROBE_POLICY,
        "release_id": release_id,
        "review_id": review_id,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": SHA_A,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": SHA_G,
        "bodyrig_revision": BODYRIG_REVISION,
        "review_authority_sha256": review_sha,
        "source_capture_id": "wardcap-0123456789abcdef0123456789abcdef",
        "source_capture_sha256": "6" * 64,
        "source_manifest_sha256": "7" * 64,
        "source_view_sha256": {"front": "8" * 64, "left_side": "9" * 64, "right_side": "a" * 64, "back": "b" * 64},
        "garment_inventory_sha256": "c" * 64,
        "garment_count": 3,
        "footwear_present": True,
        "render_authority_sha256": render_sha,
        "package_lineage_sha256": lineage_sha,
        "comparison_authority_sha256": "d" * 64,
        "runtime_manifest_sha256": "e" * 64,
        "render_manifest_sha256": "f" * 64,
        "render_view_sha256": {"front": "0" * 64, "left_side": "1" * 64, "right_side": "2" * 64, "back": "3" * 64},
        "machine_probe_sha256": "4" * 64,
        "deformation_probe_sha256": deformation_sha,
        "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
        "finalized_utc": "2026-09-05T20:00:00Z",
        "state": "complete",
        "source_grounded": True,
        "operator_supplied": True,
        **checklist,
        "footwear_review_required": True,
        "footwear_review_passed": True,
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
    status = inspect_digital_twin_status(assembly_receipt=_assembly(), body_release_status=_body_release())
    assert status["avatar_ready"] is True
    assert status["digital_twin_release_eligible"] is False
    assert status["digital_twin_ready"] is False
    assert status["production_activation"] is False
    assert status["next_gate"] == "hands_feet_nails"
    assert status["gates"]["hands_feet_nails"]["state"] == "missing"
    assert status["gates"]["wardrobe"]["state"] == "missing"
    assert status["gates"]["embodiment"]["state"] == "missing"


def test_all_subsystem_authorities_only_make_twin_release_eligible() -> None:
    hands = _hands_nails()
    wardrobe = _wardrobe()
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(), body_release_status=_body_release(), hands_nails_authority=hands,
        wardrobe_authority=wardrobe, embodiment_authority=_embodiment(),
    )
    assert status["avatar_ready"] is True
    assert status["digital_twin_release_eligible"] is True
    assert status["digital_twin_ready"] is False
    assert status["production_activation"] is False
    assert status["final_release_implemented"] is False
    assert status["next_gate"] == "digital_twin_final_release"
    assert status["gates"]["hands_feet_nails"]["release_id"] == hands["release_id"]
    assert status["gates"]["wardrobe"]["release_id"] == wardrobe["release_id"]
    assert status["gates"]["wardrobe"]["footwear_present"] is True


def test_nails_cannot_be_incidental_texture_only() -> None:
    hands = _hands_nails()
    hands["fingernails_review_passed"] = False
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(), body_release_status=_body_release(), hands_nails_authority=hands,
        wardrobe_authority=_wardrobe(), embodiment_authority=_embodiment(),
    )
    assert status["digital_twin_release_eligible"] is False
    assert status["next_gate"] == "hands_feet_nails"
    assert any("did not pass fingernails_review_passed" in blocker for blocker in status["blockers"])


def test_hands_authority_is_bound_to_exact_promoted_body_package() -> None:
    hands = _hands_nails()
    hands["body_package_sha256"] = "0" * 64
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(), body_release_status=_body_release(), hands_nails_authority=hands,
        wardrobe_authority=_wardrobe(), embodiment_authority=_embodiment(),
    )
    assert status["digital_twin_release_eligible"] is False
    assert status["next_gate"] == "hands_feet_nails"
    assert any("body_package_sha256" in blocker for blocker in status["blockers"])


def test_raw_human_review_is_not_finalized_m2_authority() -> None:
    status = inspect_digital_twin_status(assembly_receipt=_assembly(), body_release_status=_body_release(), hands_nails_authority=_raw_review())
    assert status["digital_twin_release_eligible"] is False
    assert status["gates"]["hands_feet_nails"]["state"] == "blocked"
    assert any("finalized authority" in blocker for blocker in status["blockers"])


def test_legacy_boolean_hands_dict_is_not_m2_authority() -> None:
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(), body_release_status=_body_release(),
        hands_nails_authority={"state": "complete", "source_grounded": True, "hand_geometry_review_passed": True, "production_activation": False},
    )
    assert status["digital_twin_release_eligible"] is False
    assert status["gates"]["hands_feet_nails"]["state"] == "blocked"
    assert any("fields are not canonical" in blocker for blocker in status["blockers"])


def test_wardrobe_requires_real_deformation_review() -> None:
    wardrobe = _wardrobe()
    wardrobe["deformation_review_passed"] = False
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(), body_release_status=_body_release(), hands_nails_authority=_hands_nails(),
        wardrobe_authority=wardrobe, embodiment_authority=_embodiment(),
    )
    assert status["digital_twin_release_eligible"] is False
    assert status["next_gate"] == "wardrobe"
    assert any("deformation_review_passed" in blocker for blocker in status["blockers"])


def test_raw_or_legacy_wardrobe_authority_cannot_satisfy_m3() -> None:
    legacy = {
        "state": "complete",
        "source_grounded": True,
        "garment_geometry_review_passed": True,
        "material_review_passed": True,
        "layering_review_passed": True,
        "attachment_review_passed": True,
        "deformation_review_passed": True,
        "production_activation": False,
    }
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(), body_release_status=_body_release(), hands_nails_authority=_hands_nails(),
        wardrobe_authority=legacy, embodiment_authority=_embodiment(),
    )
    assert status["digital_twin_release_eligible"] is False
    assert status["gates"]["wardrobe"]["state"] == "blocked"
    assert any("finalized authority" in blocker for blocker in status["blockers"])


def test_wardrobe_cannot_activate_production_independently() -> None:
    wardrobe = _wardrobe()
    wardrobe["production_activation"] = True
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(), body_release_status=_body_release(), hands_nails_authority=_hands_nails(),
        wardrobe_authority=wardrobe, embodiment_authority=_embodiment(),
    )
    assert status["digital_twin_release_eligible"] is False
    assert any("cannot" in blocker or "non-activating" in blocker for blocker in status["blockers"])


def test_wardrobe_footwear_review_is_required_when_present() -> None:
    wardrobe = _wardrobe()
    wardrobe["footwear_review_passed"] = False
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(), body_release_status=_body_release(), hands_nails_authority=_hands_nails(),
        wardrobe_authority=wardrobe, embodiment_authority=_embodiment(),
    )
    assert status["digital_twin_release_eligible"] is False
    assert status["next_gate"] == "wardrobe"
    assert any("footwear" in blocker for blocker in status["blockers"])


def test_legacy_person_assembly_receipt_is_not_twin_authority() -> None:
    assembly = _assembly()
    assembly["version"] = 1
    try:
        inspect_digital_twin_status(assembly_receipt=assembly, body_release_status=_body_release())
    except DigitalTwinStatusError as exc:
        assert "audition-bound Person assembly receipt" in str(exc)
    else:
        raise AssertionError("legacy assembly receipt unexpectedly became digital-twin authority")
