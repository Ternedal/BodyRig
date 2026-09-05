from __future__ import annotations

import bodyrig.high_fidelity_physical_acceptance as physical
import bodyrig.high_fidelity_release_readiness as release


def test_physical_handoff_modules_import_and_keep_release_activation_separate() -> None:
    assert physical.FORMAT == "bodyrig-high-fidelity-physical-handoff"
    assert release.PHYSICAL_GATE_A == "physical_gate_a"
    assert release.WINDOWS_GATE == "physical_windows_acceptance"
    assert release.QUEST_GATE == "physical_quest_acceptance"
    assert release.FINAL_RELEASE_GATE == "final_release"
