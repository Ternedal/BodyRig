import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.avatar import ProceduralAvatarFitter
from bodyrig.digital_twin_composition_authority import (
    FORMAT as COMPOSITION_FORMAT,
    POLICY_REVISION as COMPOSITION_POLICY,
    DigitalTwinCompositionAuthorityError,
    _authority_id as _composition_id,
    _content_sha256,
    build_embodiment_probe,
    composition_authority_dir,
    read_composition_authority,
    write_composition_authority,
)
from bodyrig.digital_twin_status import DigitalTwinStatusError, inspect_digital_twin_status
from bodyrig.hands_feet_nails_authority import CHECKLIST_FIELDS, _review_id
from bodyrig.hands_feet_nails_release_authority import (
    FORMAT as HFN_FORMAT,
    POLICY_REVISION as HFN_POLICY,
    _release_id,
)
from bodyrig.package import build_package
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
        "audition": {
            "audition_id": "audition-0123456789abcdef0123456789abcdef",
            "receipt_sha256": SHA_F,
        },
    }


def _body_release(package_sha: str = SHA_G) -> dict:
    return {
        "format": "bodyrig-person-release-status",
        "version": 1,
        "person_id": PERSON_ID,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "package_sha256": package_sha,
        "production_ready": True,
        "production_activation": True,
    }


def _review_identity(package_sha: str = SHA_G) -> tuple[str, str, str]:
    source_capture_sha = "2" * 64
    render_manifest_sha = "3" * 64
    review_id = _review_id(
        person_id=PERSON_ID,
        person_revision=PERSON_REVISION,
        assembly_fingerprint=SHA_A,
        body_package_sha256=package_sha,
        bodyrig_revision=BODYRIG_REVISION,
        source_capture_sha256=source_capture_sha,
        render_manifest_sha256=render_manifest_sha,
    )
    return review_id, source_capture_sha, render_manifest_sha


def _hands_nails(package_sha: str = SHA_G) -> dict:
    review_id, source_capture_sha, render_manifest_sha = _review_identity(package_sha)
    review_authority_sha = "d" * 64
    render_authority_sha = "e" * 64
    comparison_authority_sha = "f" * 64
    release_id = _release_id(
        review_id=review_id,
        review_authority_sha256=review_authority_sha,
        render_authority_sha256=render_authority_sha,
        comparison_authority_sha256=comparison_authority_sha,
        body_package_sha256=package_sha,
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
        "body_package_sha256": package_sha,
        "bodyrig_revision": BODYRIG_REVISION,
        "review_authority_sha256": review_authority_sha,
        "source_capture_id": "hfncap-0123456789abcdef0123456789abcdef",
        "source_capture_sha256": source_capture_sha,
        "source_manifest_sha256": "4" * 64,
        "source_region_sha256": {
            "left_hand": "5" * 64,
            "right_hand": "6" * 64,
            "left_foot": "7" * 64,
            "right_foot": "8" * 64,
        },
        "render_authority_sha256": render_authority_sha,
        "comparison_authority_sha256": comparison_authority_sha,
        "runtime_manifest_sha256": "9" * 64,
        "render_manifest_sha256": render_manifest_sha,
        "render_region_sha256": {
            "left_hand": "a" * 64,
            "right_hand": "b" * 64,
            "left_foot": "c" * 64,
            "right_foot": "0" * 64,
        },
        "finalized_utc": "2026-09-05T18:00:00Z",
        "state": "complete",
        "source_grounded": True,
        "operator_supplied": True,
        **checklist,
        "production_activation": False,
    }


def _wardrobe(package_sha: str = SHA_G) -> dict:
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
        body_package_sha256=package_sha,
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
        "body_package_sha256": package_sha,
        "bodyrig_revision": BODYRIG_REVISION,
        "review_authority_sha256": review_sha,
        "source_capture_id": "wardcap-0123456789abcdef0123456789abcdef",
        "source_capture_sha256": "6" * 64,
        "source_manifest_sha256": "7" * 64,
        "source_view_sha256": {
            "front": "8" * 64,
            "left_side": "9" * 64,
            "right_side": "a" * 64,
            "back": "b" * 64,
        },
        "garment_inventory_sha256": "c" * 64,
        "garment_count": 3,
        "footwear_present": True,
        "render_authority_sha256": render_sha,
        "package_lineage_sha256": lineage_sha,
        "comparison_authority_sha256": "d" * 64,
        "runtime_manifest_sha256": "e" * 64,
        "render_manifest_sha256": "f" * 64,
        "render_view_sha256": {
            "front": "0" * 64,
            "left_side": "1" * 64,
            "right_side": "2" * 64,
            "back": "3" * 64,
        },
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


def _component(authority: dict, exact_sha: str) -> dict:
    return {
        "release_id": authority["release_id"],
        "review_id": authority["review_id"],
        "source_capture_id": authority["source_capture_id"],
        "authority_sha256": exact_sha,
        "authority_content_sha256": _content_sha256(authority),
    }


def _composition(
    *,
    assembly: dict | None = None,
    release: dict | None = None,
    hands: dict | None = None,
    wardrobe: dict | None = None,
) -> dict:
    assembly = assembly or _assembly()
    release = release or _body_release()
    hands = hands or _hands_nails()
    wardrobe = wardrobe or _wardrobe()
    result = {
        "format": COMPOSITION_FORMAT,
        "version": 1,
        "policy_revision": COMPOSITION_POLICY,
        "authority_id": "",
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": SHA_A,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": release["package_sha256"],
        "bodyprint_sha256": "6" * 64,
        "bodyrig_revision": BODYRIG_REVISION,
        "assembly_receipt_sha256": "7" * 64,
        "assembly_receipt_content_sha256": _content_sha256(assembly),
        "body_release_status_sha256": "8" * 64,
        "body_release_status_content_sha256": _content_sha256(release),
        "audition_receipt_sha256": SHA_F,
        "hands_feet_nails": _component(hands, "9" * 64),
        "wardrobe": _component(wardrobe, "0" * 64),
        "embodiment_probe_sha256": "a" * 64,
        "finalized_utc": "2026-09-06T08:00:00Z",
        "state": "complete",
        "source_observed_embodiment": True,
        "production_activation": False,
    }
    result["authority_id"] = _composition_id(result)
    return result


def _m5_status() -> dict:
    return {
        "format": "bodyrig-digital-twin-platform-status",
        "version": 1,
        "m5_ready": True,
        "digital_twin_ready": False,
        "production_activation": False,
        "platforms": {
            "windows-unity-univrm": {
                "ready": True,
                "state": "complete",
                "realization_sha256": "2" * 64,
            },
            "android-quest-class": {
                "ready": True,
                "state": "complete",
                "realization_sha256": "3" * 64,
            },
        },
        "blockers": [],
        "next_gate": "digital_twin_final_release",
    }


def test_body_release_alone_is_not_a_full_digital_twin() -> None:
    status = inspect_digital_twin_status(assembly_receipt=_assembly(), body_release_status=_body_release())
    assert status["avatar_ready"] is True
    assert status["digital_twin_release_eligible"] is False
    assert status["next_gate"] == "hands_feet_nails"
    assert status["gates"]["embodiment"]["state"] == "missing"


def test_finalized_m4_composition_stops_at_m5_platform_acceptance() -> None:
    hands = _hands_nails()
    wardrobe = _wardrobe()
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        hands_nails_authority=hands,
        wardrobe_authority=wardrobe,
        embodiment_authority=_composition(hands=hands, wardrobe=wardrobe),
    )
    assert status["digital_twin_release_eligible"] is False
    assert status["digital_twin_ready"] is False
    assert status["production_activation"] is False
    assert status["final_release_implemented"] is False
    assert status["next_gate"] == "digital_twin_platform_acceptance"
    assert status["gates"]["embodiment"]["authority_id"].startswith("dtcomp-")
    assert status["gates"]["platform_acceptance"]["state"] == "missing"


def test_complete_m5_makes_twin_eligible_for_m6_but_does_not_activate() -> None:
    hands = _hands_nails()
    wardrobe = _wardrobe()
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        hands_nails_authority=hands,
        wardrobe_authority=wardrobe,
        embodiment_authority=_composition(hands=hands, wardrobe=wardrobe),
        platform_acceptance_status=_m5_status(),
    )
    assert status["digital_twin_release_eligible"] is True
    assert status["digital_twin_ready"] is False
    assert status["production_activation"] is False
    assert status["final_release_implemented"] is False
    assert status["next_gate"] == "digital_twin_final_release"
    assert status["gates"]["platform_acceptance"]["state"] == "complete"


def test_m5_cannot_claim_final_readiness_or_activation() -> None:
    hands = _hands_nails()
    wardrobe = _wardrobe()
    bad = _m5_status()
    bad["digital_twin_ready"] = True
    bad["production_activation"] = True
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        hands_nails_authority=hands,
        wardrobe_authority=wardrobe,
        embodiment_authority=_composition(hands=hands, wardrobe=wardrobe),
        platform_acceptance_status=bad,
    )
    assert status["digital_twin_release_eligible"] is False
    assert status["next_gate"] == "digital_twin_platform_acceptance"


def test_legacy_loose_embodiment_booleans_are_rejected() -> None:
    legacy = {
        "state": "complete",
        "motion_authority": True,
        "expression_authority": True,
        "voice_timing_authority": True,
        "production_activation": False,
    }
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        hands_nails_authority=_hands_nails(),
        wardrobe_authority=_wardrobe(),
        embodiment_authority=legacy,
    )
    assert status["digital_twin_release_eligible"] is False
    assert status["next_gate"] == "embodiment"
    assert any("composition authority" in blocker for blocker in status["blockers"])


def test_composition_is_bound_to_exact_m2_content() -> None:
    hands = _hands_nails()
    wardrobe = _wardrobe()
    composition = _composition(hands=hands, wardrobe=wardrobe)
    hands["fingernails_review_passed"] = False
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        hands_nails_authority=hands,
        wardrobe_authority=wardrobe,
        embodiment_authority=composition,
    )
    assert status["digital_twin_release_eligible"] is False
    assert status["next_gate"] == "hands_feet_nails"


def test_composition_is_bound_to_exact_m3_content() -> None:
    hands = _hands_nails()
    wardrobe = _wardrobe()
    composition = _composition(hands=hands, wardrobe=wardrobe)
    wardrobe["deformation_review_passed"] = False
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        hands_nails_authority=hands,
        wardrobe_authority=wardrobe,
        embodiment_authority=composition,
    )
    assert status["digital_twin_release_eligible"] is False
    assert status["next_gate"] == "wardrobe"


def test_m4_cannot_activate_production() -> None:
    hands = _hands_nails()
    wardrobe = _wardrobe()
    composition = _composition(hands=hands, wardrobe=wardrobe)
    composition["production_activation"] = True
    status = inspect_digital_twin_status(
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        hands_nails_authority=hands,
        wardrobe_authority=wardrobe,
        embodiment_authority=composition,
    )
    assert status["digital_twin_release_eligible"] is False
    assert status["next_gate"] == "embodiment"


def test_legacy_person_assembly_receipt_is_not_twin_authority() -> None:
    assembly = _assembly()
    assembly["version"] = 1
    with pytest.raises(DigitalTwinStatusError, match="audition-bound Person assembly receipt"):
        inspect_digital_twin_status(assembly_receipt=assembly, body_release_status=_body_release())


def test_embodiment_probe_does_not_claim_neutral_defaults_as_observed() -> None:
    probe = build_embodiment_probe(
        body_id=BODY_ID,
        bodyprint={"format": "modelrig-bodyprint", "version": 1, "motion": {"energy": 0.42}},
    )
    observed = probe["motor_state"]["embodiment"]["observed"]
    assert observed == {"energy": 0.42}
    assert "head_motion" in probe["motor_state"]["motion"]
    assert "head_motion" not in observed
    assert probe["motor_state"]["speech"]["viseme"] == "AA"
    assert "amplitude" in probe["motor_state"]["speech"]


def test_embodiment_probe_requires_source_observed_behavior() -> None:
    with pytest.raises(DigitalTwinCompositionAuthorityError, match="no source-observed"):
        build_embodiment_probe(
            body_id=BODY_ID,
            bodyprint={
                "format": "modelrig-bodyprint",
                "version": 1,
                "shape": {"shoulder_to_height": 0.24},
            },
        )


def _write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _package(tmp_path: Path) -> Path:
    bodyprint = {
        "format": "modelrig-bodyprint",
        "version": 1,
        "shape": {
            "shoulder_to_height": 0.24,
            "hip_to_height": 0.19,
            "arm_to_height": 0.44,
            "leg_to_height": 0.53,
        },
        "motion": {"energy": 0.42, "gesture_amplitude": 0.61},
        "expression": {"gaze_strength": 0.57, "speech_motion": 0.64},
        "runtime": {"gesture_intensity": 0.58},
    }
    provenance = {
        "format": "modelrig-body-provenance",
        "version": 1,
        "created_at": "2026-09-06T08:00:00Z",
        "source": {"kind": "user-supplied-local-media", "count": 2},
        "synthetic_avatar": True,
        "pipeline": [{"stage": "body-recovery", "adapter": "fixture", "revision": "fixture-v1"}],
    }
    avatar = ProceduralAvatarFitter().fit(bodyprint, name="M4 Fixture").avatar_vrm
    return build_package(
        tmp_path / "m4-fixture.mrbody",
        body_id=BODY_ID,
        name="M4 Fixture",
        avatar_vrm=avatar,
        bodyprint=bodyprint,
        provenance=provenance,
        thumbnail_png=b"\x89PNG\r\n\x1a\nfixture",
        builder_revision=BODYRIG_REVISION,
    )


def test_m4_bundle_is_create_only_and_readback_detects_tamper(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
    assembly = _assembly()
    release = _body_release(package_sha)
    hands = _hands_nails(package_sha)
    wardrobe = _wardrobe(package_sha)

    assembly_path = _write_json(tmp_path / "assembly.json", assembly)
    release_path = _write_json(tmp_path / "release.json", release)
    hands_path = _write_json(tmp_path / "hands.json", hands)
    wardrobe_path = _write_json(tmp_path / "wardrobe.json", wardrobe)
    library = tmp_path / "library"

    authority = write_composition_authority(
        library,
        assembly_receipt_path=assembly_path,
        body_release_status_path=release_path,
        hands_nails_authority_path=hands_path,
        wardrobe_authority_path=wardrobe_path,
        body_package_path=package,
        bodyrig_revision=BODYRIG_REVISION,
    )
    assert authority["production_activation"] is False
    assert authority["body_package_sha256"] == package_sha
    assert authority["audition_receipt_sha256"] == SHA_F

    readback = read_composition_authority(
        library,
        person_id=PERSON_ID,
        person_revision=PERSON_REVISION,
        authority_id=authority["authority_id"],
        body_package_path=package,
    )
    assert readback == authority

    with pytest.raises(DigitalTwinCompositionAuthorityError, match="already exists"):
        write_composition_authority(
            library,
            assembly_receipt_path=assembly_path,
            body_release_status_path=release_path,
            hands_nails_authority_path=hands_path,
            wardrobe_authority_path=wardrobe_path,
            body_package_path=package,
            bodyrig_revision=BODYRIG_REVISION,
        )

    bundle = composition_authority_dir(library, PERSON_ID, PERSON_REVISION, authority["authority_id"])
    probe_path = bundle / "embodiment-probe.json"
    probe_path.write_bytes(probe_path.read_bytes() + b"\n")
    with pytest.raises(DigitalTwinCompositionAuthorityError, match="probe bytes were modified"):
        read_composition_authority(
            library,
            person_id=PERSON_ID,
            person_revision=PERSON_REVISION,
            authority_id=authority["authority_id"],
        )
