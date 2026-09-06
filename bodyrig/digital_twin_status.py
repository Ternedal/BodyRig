from __future__ import annotations

import re
from typing import Any, Mapping

from .digital_twin_composition_authority import (
    DigitalTwinCompositionAuthorityError,
    validate_composition_authority_structure,
)
from .digital_twin_release import DigitalTwinReleaseError, validate_release_authority_structure as validate_final_release
from .hands_feet_nails_release_authority import (
    HandsFeetNailsReleaseAuthorityError,
    validate_release_authority_structure as validate_hands_nails_release_authority,
)
from .wardrobe_release_authority import (
    WardrobeReleaseAuthorityError,
    validate_release_authority_structure as validate_wardrobe_release_authority,
)

FORMAT = "bodyrig-digital-twin-status"
VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DigitalTwinStatusError(ValueError):
    pass


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DigitalTwinStatusError(f"{label} authority is missing or invalid")
    return value


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256.fullmatch(text):
        raise DigitalTwinStatusError(f"{label} is not a canonical SHA-256")
    return text


def _assembly_gate(receipt: Mapping[str, Any]) -> dict[str, Any]:
    if receipt.get("format") != "bodyrig-person-assembly-receipt" or receipt.get("version") != 2:
        raise DigitalTwinStatusError("digital twin requires a current audition-bound Person assembly receipt")

    body = _mapping(receipt.get("body"), "body assembly")
    voice = _mapping(receipt.get("voice"), "voice assembly")
    personality = _mapping(receipt.get("personality"), "personality assembly")
    audition = _mapping(receipt.get("audition"), "audition")

    body_revision = str(body.get("revision_id") or "").strip()
    body_id = str(body.get("body_id") or "").strip()
    voice_revision = str(voice.get("revision_id") or "").strip()
    voice_id = str(voice.get("voice_id") or "").strip()
    voice_package = str(voice.get("voice_package") or "").strip()
    personality_revision = str(personality.get("revision_id") or "").strip()
    default_language = str(personality.get("default_language") or "").strip()
    audition_id = str(audition.get("audition_id") or "").strip()

    if not all((body_revision, body_id, voice_revision, voice_id, voice_package, personality_revision, default_language, audition_id)):
        raise DigitalTwinStatusError("Person assembly is missing required body/voice/personality/audition identity")

    _sha(body.get("package_sha256"), "body package SHA-256")
    _sha(voice.get("package_sha256"), "voice package SHA-256")
    _sha(personality.get("instructions_sha256"), "personality instructions SHA-256")
    _sha(personality.get("style_notes_sha256"), "personality style-notes SHA-256")
    _sha(audition.get("receipt_sha256"), "audition receipt SHA-256")
    assembly_fingerprint = _sha(receipt.get("assembly_fingerprint"), "assembly fingerprint")

    return {
        "ready": True,
        "assembly_fingerprint": assembly_fingerprint,
        "body_revision": body_revision,
        "body_id": body_id,
        "voice_revision": voice_revision,
        "personality_revision": personality_revision,
        "audition_id": audition_id,
    }


def _hands_nails_gate(
    authority: Mapping[str, Any] | None,
    *,
    assembly_receipt: Mapping[str, Any],
    body_release_status: Mapping[str, Any],
) -> dict[str, Any]:
    if authority is None:
        return {
            "ready": False,
            "state": "missing",
            "blockers": ["hands/feet/nails finalized authority is not implemented/recorded"],
        }
    try:
        value = validate_hands_nails_release_authority(
            authority,
            assembly_receipt=assembly_receipt,
            body_release_status=body_release_status,
        )
    except HandsFeetNailsReleaseAuthorityError as exc:
        return {
            "ready": False,
            "state": "blocked",
            "blockers": [f"hands/feet/nails finalized authority is invalid: {exc}"],
        }
    return {
        "ready": True,
        "state": "complete",
        "blockers": [],
        "release_id": str(value["release_id"]),
        "review_id": str(value["review_id"]),
        "source_capture_id": str(value["source_capture_id"]),
        "body_package_sha256": str(value["body_package_sha256"]),
        "bodyrig_revision": str(value["bodyrig_revision"]),
    }


def _wardrobe_gate(
    authority: Mapping[str, Any] | None,
    *,
    assembly_receipt: Mapping[str, Any],
    body_release_status: Mapping[str, Any],
) -> dict[str, Any]:
    if authority is None:
        return {
            "ready": False,
            "state": "missing",
            "blockers": ["wardrobe/clothing finalized authority is not implemented/recorded"],
        }
    try:
        value = validate_wardrobe_release_authority(
            authority,
            assembly_receipt=assembly_receipt,
            body_release_status=body_release_status,
        )
    except WardrobeReleaseAuthorityError as exc:
        return {
            "ready": False,
            "state": "blocked",
            "blockers": [f"wardrobe/clothing finalized authority is invalid: {exc}"],
        }
    return {
        "ready": True,
        "state": "complete",
        "blockers": [],
        "release_id": str(value["release_id"]),
        "review_id": str(value["review_id"]),
        "source_capture_id": str(value["source_capture_id"]),
        "garment_count": int(value["garment_count"]),
        "footwear_present": bool(value["footwear_present"]),
        "body_package_sha256": str(value["body_package_sha256"]),
        "bodyrig_revision": str(value["bodyrig_revision"]),
    }


def _embodiment_gate(
    authority: Mapping[str, Any] | None,
    *,
    assembly_receipt: Mapping[str, Any],
    body_release_status: Mapping[str, Any],
    hands_nails_authority: Mapping[str, Any] | None,
    wardrobe_authority: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if authority is None:
        return {
            "ready": False,
            "state": "missing",
            "blockers": ["finalized M4 digital-twin composition authority is not implemented/recorded"],
        }
    if hands_nails_authority is None or wardrobe_authority is None:
        return {
            "ready": False,
            "state": "blocked",
            "blockers": ["M4 composition cannot validate without the exact finalized M2 and M3 authorities"],
        }
    try:
        value = validate_composition_authority_structure(
            authority,
            assembly_receipt=assembly_receipt,
            body_release_status=body_release_status,
            hands_nails_authority=hands_nails_authority,
            wardrobe_authority=wardrobe_authority,
        )
    except DigitalTwinCompositionAuthorityError as exc:
        return {
            "ready": False,
            "state": "blocked",
            "blockers": [f"M4 digital-twin composition authority is invalid: {exc}"],
        }
    return {
        "ready": True,
        "state": "complete",
        "blockers": [],
        "authority_id": str(value["authority_id"]),
        "body_package_sha256": str(value["body_package_sha256"]),
        "bodyprint_sha256": str(value["bodyprint_sha256"]),
        "embodiment_probe_sha256": str(value["embodiment_probe_sha256"]),
        "bodyrig_revision": str(value["bodyrig_revision"]),
    }


def _platform_acceptance_gate(status: Mapping[str, Any] | None) -> dict[str, Any]:
    if status is None:
        return {
            "ready": False,
            "state": "missing",
            "blockers": ["M5 Windows/Quest digital-twin composition acceptance is not implemented/recorded"],
        }
    if status.get("format") != "bodyrig-digital-twin-platform-status" or status.get("version") != 1:
        return {
            "ready": False,
            "state": "blocked",
            "blockers": ["M5 platform acceptance status format/version is invalid"],
        }
    platforms = status.get("platforms")
    if not isinstance(platforms, Mapping):
        return {
            "ready": False,
            "state": "blocked",
            "blockers": ["M5 platform acceptance lacks platform evidence"],
        }
    required = ("windows-unity-univrm", "android-quest-class")
    blockers: list[str] = []
    for platform in required:
        value = platforms.get(platform)
        if not isinstance(value, Mapping) or value.get("ready") is not True or value.get("state") != "complete":
            blockers.append(f"M5 {platform} digital-twin realization is not complete")
    if status.get("m5_ready") is not True:
        blockers.append("M5 platform acceptance has not reached ready state")
    if status.get("production_activation") is not False:
        blockers.append("M5 platform acceptance must remain non-activating")
    if status.get("digital_twin_ready") is not False:
        blockers.append("M5 may not claim final digital-twin readiness before M6")
    if blockers:
        return {"ready": False, "state": "blocked", "blockers": blockers}
    return {
        "ready": True,
        "state": "complete",
        "blockers": [],
        "windows_realization_sha256": str(platforms["windows-unity-univrm"].get("realization_sha256") or ""),
        "quest_realization_sha256": str(platforms["android-quest-class"].get("realization_sha256") or ""),
    }


def _final_release_gate(
    authority: Mapping[str, Any] | None,
    *,
    composition_authority: Mapping[str, Any] | None,
    platform_acceptance_status: Mapping[str, Any] | None,
    body_release_status: Mapping[str, Any],
) -> dict[str, Any]:
    if authority is None:
        return {
            "ready": False,
            "state": "missing",
            "blockers": ["canonical M6 full digital-twin release is not finalized/recorded"],
        }
    if composition_authority is None or platform_acceptance_status is None:
        return {
            "ready": False,
            "state": "blocked",
            "blockers": ["M6 release cannot validate without exact M4 composition and M5 platform status"],
        }
    try:
        value = validate_final_release(
            authority,
            composition_authority=composition_authority,
            platform_acceptance_status=platform_acceptance_status,
            body_release_status=body_release_status,
        )
    except DigitalTwinReleaseError as exc:
        return {
            "ready": False,
            "state": "blocked",
            "blockers": [f"canonical M6 full digital-twin release is invalid: {exc}"],
        }
    return {
        "ready": True,
        "state": "complete",
        "blockers": [],
        "release_id": str(value["release_id"]),
        "body_package_sha256": str(value["body_package_sha256"]),
        "windows_realization_sha256": str(value["windows_realization_sha256"]),
        "quest_realization_sha256": str(value["quest_realization_sha256"]),
        "bodyrig_revision": str(value["bodyrig_revision"]),
    }


def inspect_digital_twin_status(
    *,
    assembly_receipt: Mapping[str, Any],
    body_release_status: Mapping[str, Any],
    hands_nails_authority: Mapping[str, Any] | None = None,
    wardrobe_authority: Mapping[str, Any] | None = None,
    embodiment_authority: Mapping[str, Any] | None = None,
    platform_acceptance_status: Mapping[str, Any] | None = None,
    final_release_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose the complete BodyRig full-digital-twin release state.

    M1-M5 make the Person Revision eligible for final release. Only a valid M6
    canonical release authority may set digital_twin_ready and production_activation.
    """

    assembly = _assembly_gate(_mapping(assembly_receipt, "Person assembly receipt"))
    body = _mapping(body_release_status, "body release")

    body_ready = body.get("production_ready") is True and body.get("production_activation") is True
    body_blockers: list[str] = []
    if body.get("production_ready") is not True:
        body_blockers.append("body release is not production-ready")
    if body.get("production_activation") is not True:
        body_blockers.append("body release is not physically activated")

    hands_nails = _hands_nails_gate(
        hands_nails_authority,
        assembly_receipt=assembly_receipt,
        body_release_status=body_release_status,
    )
    wardrobe = _wardrobe_gate(
        wardrobe_authority,
        assembly_receipt=assembly_receipt,
        body_release_status=body_release_status,
    )
    embodiment = _embodiment_gate(
        embodiment_authority,
        assembly_receipt=assembly_receipt,
        body_release_status=body_release_status,
        hands_nails_authority=hands_nails_authority,
        wardrobe_authority=wardrobe_authority,
    )
    platform_acceptance = _platform_acceptance_gate(platform_acceptance_status)

    pre_release_gates = {
        "person_assembly": {"ready": True, "state": "complete", "blockers": []},
        "body": {"ready": body_ready, "state": "complete" if body_ready else "blocked", "blockers": body_blockers},
        "voice": {"ready": True, "state": "complete", "blockers": []},
        "personality": {"ready": True, "state": "complete", "blockers": []},
        "audition": {"ready": True, "state": "complete", "blockers": []},
        "hands_feet_nails": hands_nails,
        "wardrobe": wardrobe,
        "embodiment": embodiment,
        "platform_acceptance": platform_acceptance,
    }
    release_eligible = all(gate["ready"] for gate in pre_release_gates.values())
    final_release = _final_release_gate(
        final_release_authority,
        composition_authority=embodiment_authority,
        platform_acceptance_status=platform_acceptance_status,
        body_release_status=body_release_status,
    )
    gates = {**pre_release_gates, "final_release": final_release}
    blockers = [blocker for gate in gates.values() for blocker in gate["blockers"]]
    digital_twin_ready = release_eligible and final_release["ready"]

    if not hands_nails["ready"]:
        next_gate = "hands_feet_nails"
    elif not wardrobe["ready"]:
        next_gate = "wardrobe"
    elif not embodiment["ready"]:
        next_gate = "embodiment"
    elif not body_ready:
        next_gate = "body_physical_release"
    elif not platform_acceptance["ready"]:
        next_gate = "digital_twin_platform_acceptance"
    elif not final_release["ready"]:
        next_gate = "digital_twin_final_release"
    else:
        next_gate = "complete"

    if digital_twin_ready:
        message = "Canonical M6 full digital-twin release is active for this exact Person Revision."
    elif release_eligible:
        message = "M1-M5 authorities are complete; canonical M6 digital-twin final release is required."
    else:
        message = "Avatar/body authority is not sufficient for a full digital twin; missing twin authorities remain blocked."

    return {
        "format": FORMAT,
        "version": VERSION,
        "person_id": str(assembly_receipt.get("person_id") or ""),
        "person_revision": str(assembly_receipt.get("person_revision") or ""),
        "assembly_fingerprint": assembly["assembly_fingerprint"],
        "avatar_ready": body_ready,
        "digital_twin_release_eligible": release_eligible,
        "digital_twin_ready": digital_twin_ready,
        "production_activation": digital_twin_ready,
        "final_release_implemented": final_release["ready"],
        "gates": gates,
        "blockers": blockers,
        "next_gate": next_gate,
        "message": message,
    }
