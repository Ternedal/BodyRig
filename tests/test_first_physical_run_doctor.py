from pathlib import Path


def test_first_physical_run_doctor_is_read_only_and_checkout_bound() -> None:
    script = Path("prepare-first-physical-run.ps1").read_text(encoding="utf-8")

    for token in (
        "git -C $repoRoot rev-parse HEAD",
        "git -C $repoRoot status --porcelain",
        "bodyrig.__file__",
        "check-reference-renderer-ready.ps1",
        "check-rig-ready.ps1",
        "-RigSetupReport",
        "-BodyRigPython",
        "-StashUrl",
        "-ApiKeyEnv",
        "-WslExe",
        "BodyRig pre-session doctor: READY",
        "No Unity project was opened and no physical clone session or acceptance evidence was created.",
    ):
        assert token in script

    # The doctor must never create/mutate physical evidence or start the heavy clone.
    assert "bodyrig.physical_session" not in script
    assert "accept-physical-clone.ps1" not in script
    assert "& $powerShellExe @cloneArgs" not in script


def test_first_physical_run_doctor_refuses_dirty_or_drifting_checkout() -> None:
    script = Path("prepare-first-physical-run.ps1").read_text(encoding="utf-8")

    assert "BodyRig checkout is dirty" in script
    assert "BodyRig Git HEAD changed during pre-session readiness" in script
    assert "BodyRig checkout became dirty during pre-session readiness" in script
    assert "-AllowDirty" not in script


def test_first_physical_run_doctor_requires_powershell_7_and_pwsh() -> None:
    script = Path("prepare-first-physical-run.ps1").read_text(encoding="utf-8")

    assert "$PSVersionTable.PSVersion.Major -lt 7" in script
    assert "PowerShell 7+ (pwsh) is required" in script
    assert 'Resolve-CommandPath "pwsh"' in script
    assert 'Resolve-CommandPath "powershell"' not in script


def test_first_physical_run_doctor_prints_canonical_clone_command_only_with_complete_identity_pair() -> None:
    script = Path("prepare-first-physical-run.ps1").read_text(encoding="utf-8")

    assert 'Pass -PerformerId and -BodyId together, or omit both.' in script
    assert '.\\clone-body-from-stash-ready.ps1 -PerformerId $quotedPerformer -BodyId $quotedBody' in script
    assert '.\\stash-sources.ps1 search \'<performer name>\' -Limit 10' in script


def test_first_physical_run_runbook_uses_doctor_before_session_creation() -> None:
    doc = Path("docs/FIRST_PHYSICAL_RUN.md").read_text(encoding="utf-8")

    assert "prepare-first-physical-run.ps1" in doc
    assert "PowerShell 7" in doc
    assert "pre-session" in doc.lower()
    assert "does not create" in doc.lower() or "opretter ikke" in doc.lower()
