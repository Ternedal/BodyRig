from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "nt", reason="Windows-only Credential Manager P/Invoke smoke test")
def test_native_storage_credential_helper_loads_and_reports_session_policy() -> None:
    pwsh = shutil.which("pwsh")
    assert pwsh is not None
    helper = ROOT / "storage-auth-native.ps1"
    command = (
        "$ErrorActionPreference='Stop'; "
        f". '{str(helper).replace("'", "''")}'; "
        "$value=[int](Get-BodyRigDomainCredentialMaxPersist); "
        "if ($value -lt 0 -or $value -gt 3) { throw \"invalid persistence value: $value\" }; "
        "if (-not ('BodyRig.NativeCredentialStore' -as [type])) { throw 'native helper type missing' }; "
        "Write-Output \"PERSIST=$value\""
    )
    completed = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert completed.stdout.strip().startswith("PERSIST=")
