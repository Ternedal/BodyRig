from bodyrig.digital_twin_status import (
    _embodiment_gate,
    _hands_nails_gate,
    _platform_acceptance_gate,
    _wardrobe_gate,
)


def test_missing_digital_twin_evidence_is_not_reported_as_missing_implementation() -> None:
    empty: dict = {}
    gates = (
        _hands_nails_gate(None, assembly_receipt=empty, body_release_status=empty),
        _wardrobe_gate(None, assembly_receipt=empty, body_release_status=empty),
        _embodiment_gate(
            None,
            assembly_receipt=empty,
            body_release_status=empty,
            hands_nails_authority=None,
            wardrobe_authority=None,
        ),
        _platform_acceptance_gate(None),
    )

    for gate in gates:
        assert gate["state"] == "missing"
        assert gate["ready"] is False
        assert len(gate["blockers"]) == 1
        blocker = gate["blockers"][0].lower()
        assert "recorded" in blocker
        assert "not implemented" not in blocker
        assert "implemented/recorded" not in blocker
