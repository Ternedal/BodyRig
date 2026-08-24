from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .acceptance_status import AcceptanceStatus


LEGACY_RENDERER_EVIDENCE = (
    "windows-probe.json",
    "windows-deformation-probe.json",
    "quest-probe.json",
    "quest-deformation-probe.json",
)


def apply_reference_policy(status: AcceptanceStatus) -> AcceptanceStatus:
    """Apply the canonical BodyRig V1 reference-renderer policy to generic status.

    The generic status reader intentionally remains able to inspect legacy root-file
    renderer evidence. The canonical reference-renderer path, however, only releases
    dedicated transactional ``windows-evidence/`` and ``quest-evidence/`` bundles.
    An unfinished legacy run must therefore stop before more physical work or a human
    attestation is added to a chain that the reference release policy cannot accept.

    Already-complete historical release artifacts remain readable; this policy does
    not retroactively rewrite or invalidate an existing activating release artifact.
    """

    if not status.acceptance_dir or status.state == "complete":
        return status

    acceptance_dir = Path(status.acceptance_dir)
    present = tuple(name for name in LEGACY_RENDERER_EVIDENCE if (acceptance_dir / name).is_file())
    if not present:
        return status

    files = ", ".join(present)
    return replace(
        status,
        state="blocked",
        gate="reference-layout",
        message=(
            "Legacy root renderer evidence is readable but cannot continue through the canonical "
            "BodyRig V1 reference-renderer release policy. Start a fresh Gate A acceptance bundle "
            "from the original physical-clone PASS session and use the transactional reference "
            f"wrappers. Legacy files present: {files}."
        ),
        next_command=None,
    )
