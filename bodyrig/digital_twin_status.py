from __future__ import annotations

import re
from typing import Any, Mapping

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
        "voice_revision": voice_revision,
        "personality_revision": personality_revision,
        "audition_id": audition_id,
    }


def _bool_gate(authority: Mapping[str, Any] | None, *, label: str, fields: tuple[str, ...]) -> dict[str, Any]:
    if authority is None:
        return {
            "ready": False,
            "state": "missing",
            "blockers": [f"{label} authority is not implemented/recorded"],
        }
    value = _mapping(authority, label)
    blockers: list[str] = []
    if value.get("state") != "complete":
        blockers.append(f"{label} state is not complete")
    for field in fields:
        if value.get(field) is not True:
            blockers.append(f"{label} did not pass {field}")
    if value.get("production_activation") is not False:
        blockers.append(f"{label} component authority must remain non-activating before final digital-twin release")
    return {
        "ready": not blockers,
        "state": "complete" if not blockers else "blocked",
        "blockers": blockers,
    }


def inspect_digital_twin_status(
    *,
    assembly_receipt: Mapping[str, Any],
    body_release_status: Mapping[str, Any],
    hands_nails_authority: Mapping[str, Any] | None = None,
    wardrobe_authority: Mapping[str, Any] | None = None,
    embodiment_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose current Person/body authority into the stricter full-digital-twin product gate.

    This is intentionally fail-closed. The existing body release may be production-ready,
    but that alone is never sufficient to call the Person a full digital twin.
    """

    assembly = _assembly_gate(_mapping(assembly_receipt, "Person assembly receipt"))
    body = _mapping(body_release_status, "body release")

    body_ready = body.get("production_ready") is True and body.get("production_activation") is True
    body_blockers: list[str] = []
    if body.get("production_ready") is not True:
        body_blockers.append("body release is not production-ready")
    if body.get("production_activation") is not True:
        body_blockers.append("body release is not physically activated")

    hands_nails = _bool_gate(
        hands_nails_authority,
        label="hands/feet/nails",
        fields=(
            "source_grounded",
            "hand_geometry_review_passed",
            "foot_geometry_review_passed",
            "skin_detail_review_passed",
            "fingernails_review_passed",
            "toenails_review_passed",
        ),
    )
    wardrobe = _bool_gate(
        wardrobe_authority,
        label="wardrobe/clothing",
        fields=(
            "source_grounded",
            "garment_geometry_review_passed",
            "material_review_passed",
            "layering_review_passed",
            "attachment_review_passed",
            "deformation_review_passed",
        ),
    )
    embodiment = _bool_gate(
        embodiment_authority,
        label="embodiment",
        fields=(
            "motion_authority",
            "expression_authority",
            "voice_timing_authority",
        ),
    )

    gates = {
        "person_assembly": {"ready": True, "state": "complete", "blockers": []},
        "body": {"ready": body_ready, "state": "complete" if body_ready else "blocked", "blockers": body_blockers},
        "voice": {"ready": True, "state": "complete", "blockers": []},
        "personality": {"ready": True, "state": "complete", "blockers": []},
        "audition": {"ready": True, "state": "complete", "blockers": []},
        "hands_feet_nails": hands_nails,
        "wardrobe": wardrobe,
        "embodiment": embodiment,
    }
    blockers = [blocker for gate in gates.values() for blocker in gate["blockers"]]
    release_eligible = all(gate["ready"] for gate in gates.values())

    if not hands_nails["ready"]:
        next_gate = "hands_feet_nails"
    elif not wardrobe["ready"]:
        next_gate = "wardrobe"
    elif not embodiment["ready"]:
        next_gate = "embodiment"
    elif not body_ready:
        next_gate = "body_physical_release"
    else:
        next_gate = "digital_twin_final_release"

    return {
        "format": FORMAT,
        "version": VERSION,
        "person_id": str(assembly_receipt.get("person_id") or ""),
        "person_revision": str(assembly_receipt.get("person_revision") or ""),
        "assembly_fingerprint": assembly["assembly_fingerprint"],
        "avatar_ready": body_ready,
        "digital_twin_release_eligible": release_eligible,
        "digital_twin_ready": False,
        "production_activation": False,
        "final_release_implemented": False,
        "gates": gates,
        "blockers": blockers,
        "next_gate": next_gate,
        "message": (
            "All subsystem authorities are complete; a separate canonical digital-twin final release is still required."
            if release_eligible
            else "Avatar/body authority is not sufficient for a full digital twin; missing twin authorities remain blocked."
        ),
    }
