from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from .person_profiles import load_profile
from .storage import person_library
from .ui_jobs import manager, operator_checkout_status

FORMAT = "bodyrig-ab-baseline-physical-preflight"
VERSION = 1
_OPEN_JOB_STATES = {"uploading", "queued", "running", "needs_speaker", "needs_reference", "cancelling"}


class AbBaselinePhysicalPreflightError(RuntimeError):
    pass


def _canonical_revision(value: object, *, label: str) -> str:
    revision = str(value or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise AbBaselinePhysicalPreflightError(f"{label} is not an exact 40-character Git revision")
    return revision


def _service_environment(environ: Mapping[str, str]) -> tuple[str, str]:
    stash_url = str(environ.get("STASH_URL") or "").strip()
    stash_key = str(environ.get("STASH_API_KEY") or "").strip()
    if not stash_url:
        raise AbBaselinePhysicalPreflightError("STASH_URL is not configured in the BodyRig service environment")
    if not stash_key:
        raise AbBaselinePhysicalPreflightError("STASH_API_KEY is not configured in the BodyRig service environment")
    return stash_url, stash_key


def _run_checked(
    args: list[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    timeout: int,
    step: str,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = runner(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AbBaselinePhysicalPreflightError(f"{step} could not start") from exc
    if int(completed.returncode) != 0:
        raise AbBaselinePhysicalPreflightError(f"{step} failed with exit code {completed.returncode}")
    return completed


def run_ab_baseline_physical_preflight(
    person_id: str,
    *,
    expected_bodyrig_revision: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    expected = _canonical_revision(expected_bodyrig_revision, label="expected BodyRig revision")
    environment = os.environ if environ is None else environ

    authority = operator_checkout_status()
    if not authority.get("ok"):
        raise AbBaselinePhysicalPreflightError(
            str(authority.get("reason") or "BodyRig operator checkout is not authoritative")
        )
    actual = _canonical_revision(authority.get("revision"), label="BodyRig operator checkout revision")
    if actual != expected:
        raise AbBaselinePhysicalPreflightError(
            f"BodyRig operator checkout revision differs from requested preflight authority: expected {expected}, got {actual}"
        )

    profile = load_profile(person_library(), person_id)
    source = profile.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "stash-performer":
        raise AbBaselinePhysicalPreflightError("Person must be bound to a Stash performer before A/B baseline preflight")
    performer_id = str(source.get("performer_id") or "").strip()
    if not performer_id:
        raise AbBaselinePhysicalPreflightError("Person Stash performer binding is missing its performer id")

    open_jobs = [job for job in manager.list(person_id=person_id) if str(job.get("status") or "") in _OPEN_JOB_STATES]
    if open_jobs:
        raise AbBaselinePhysicalPreflightError(
            f"Another BodyRig UI build is already open for this person: {str(open_jobs[0].get('job_id') or 'unknown')}"
        )

    stash_url, _ = _service_environment(environment)
    root = Path(__file__).resolve().parents[1]
    readiness_script = root / "check-rig-ready.ps1"
    if not readiness_script.is_file():
        raise AbBaselinePhysicalPreflightError("BodyRig rig readiness script is missing from the service checkout")

    pwsh = str(authority.get("powershell") or "").strip()
    if not pwsh:
        raise AbBaselinePhysicalPreflightError("BodyRig operator authority did not bind PowerShell 7")

    readiness = _run_checked(
        [
            pwsh,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(readiness_script),
            "-BodyRigPython",
            sys.executable,
            "-StashUrl",
            stash_url,
            "-ApiKeyEnv",
            "STASH_API_KEY",
            "-WslExe",
            "wsl.exe",
        ],
        runner=runner,
        timeout=600,
        step="BodyRig live rig/SiTH/CUDA/Stash readiness",
    )
    if "BodyRig rig readiness: READY" not in str(readiness.stdout or ""):
        raise AbBaselinePhysicalPreflightError("BodyRig live readiness exited successfully without the canonical READY marker")

    probe = _run_checked(
        [
            sys.executable,
            "-m",
            "bodyrig.stash_cli",
            "probe",
            "--performer-id",
            performer_id,
            "--url",
            stash_url,
            "--api-key-env",
            "STASH_API_KEY",
            "--ffmpeg",
            "ffmpeg",
        ],
        runner=runner,
        timeout=120,
        step="Selected Stash performer/source decode probe",
    )
    try:
        probe_value = json.loads(str(probe.stdout or ""))
    except json.JSONDecodeError as exc:
        raise AbBaselinePhysicalPreflightError("Selected Stash performer/source decode probe returned unreadable JSON") from exc
    if not isinstance(probe_value, dict) or probe_value.get("ok") is not True:
        raise AbBaselinePhysicalPreflightError("Selected Stash performer/source decode probe did not report ok=true")
    performer = probe_value.get("performer")
    if not isinstance(performer, Mapping) or str(performer.get("id") or "") != performer_id:
        raise AbBaselinePhysicalPreflightError("Selected Stash performer/source probe returned a different performer id")
    if str(probe_value.get("decode_gate") or "") != "ffmpeg-one-frame-v1":
        raise AbBaselinePhysicalPreflightError("Selected Stash performer/source probe did not use ffmpeg-one-frame-v1")
    usable_source_count = int(probe_value.get("usable_source_count") or 0)
    if usable_source_count < 1:
        raise AbBaselinePhysicalPreflightError("Selected Stash performer has no locally decodable source for A/B baseline")

    authority_after = operator_checkout_status()
    if not authority_after.get("ok"):
        raise AbBaselinePhysicalPreflightError(
            str(authority_after.get("reason") or "BodyRig operator checkout lost authority during physical preflight")
        )
    actual_after = _canonical_revision(
        authority_after.get("revision"),
        label="post-preflight BodyRig operator checkout revision",
    )
    if actual_after != expected:
        raise AbBaselinePhysicalPreflightError(
            f"BodyRig operator checkout revision moved during physical preflight: expected {expected}, got {actual_after}"
        )

    return {
        "format": FORMAT,
        "version": VERSION,
        "ready": True,
        "person_id": person_id,
        "performer_id": performer_id,
        "bodyrig_revision": expected,
        "decode_gate": "ffmpeg-one-frame-v1",
        "usable_source_count": usable_source_count,
        "service_environment_bound": True,
        "readiness_output_persisted": False,
        "physical_acceptance_authority": False,
        "promotion_authority": False,
        "production_activation": False,
    }
