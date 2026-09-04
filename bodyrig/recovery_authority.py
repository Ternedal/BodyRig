from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

RIG_SETUP_ENV = "BODYRIG_RIG_SETUP_REPORT"


class RecoveryAuthorityError(ValueError):
    pass


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.expanduser().resolve())) == os.path.normcase(
        str(right.expanduser().resolve())
    )


def resolve_phalp_repo(
    four_d_repo: str | Path,
    explicit_phalp_repo: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the PHALP checkout that belongs to a 4D-Humans recovery authority.

    Production ready-rig runs inherit BODYRIG_RIG_SETUP_REPORT, so an omitted
    --phalp-repo is recovered from the exact byte-bound rig setup rather than
    guessed from whatever editable PHALP happens to import. Low-level
    diagnostics without a rig setup keep the historical managed sibling layout
    fallback: <recovery-root>/4D-Humans + <recovery-root>/PHALP.
    """

    four_d = Path(four_d_repo).expanduser().resolve()
    if explicit_phalp_repo is not None and str(explicit_phalp_repo).strip():
        return Path(explicit_phalp_repo).expanduser().resolve()

    environment = os.environ if environ is None else environ
    report_value = str(environment.get(RIG_SETUP_ENV, "")).strip()
    if not report_value:
        return (four_d.parent / "PHALP").resolve()

    report_path = Path(report_value).expanduser().resolve()
    if not report_path.is_file():
        raise RecoveryAuthorityError(
            f"{RIG_SETUP_ENV} points to a missing rig setup report: {report_path}"
        )
    try:
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryAuthorityError(
            f"{RIG_SETUP_ENV} rig setup report is unreadable"
        ) from exc
    if not isinstance(report, dict) or report.get("format") != "bodyrig-rig-setup" or report.get("version") != 1:
        raise RecoveryAuthorityError(
            f"{RIG_SETUP_ENV} does not reference a BodyRig rig setup v1 report"
        )
    recovery = report.get("recovery")
    if not isinstance(recovery, dict):
        raise RecoveryAuthorityError("rig setup report has no recovery authority")
    bound_four_d = recovery.get("four_d_humans_repo")
    bound_phalp = recovery.get("phalp_repo")
    if not isinstance(bound_four_d, str) or not bound_four_d.strip():
        raise RecoveryAuthorityError("rig setup recovery authority has no 4D-Humans checkout")
    if not isinstance(bound_phalp, str) or not bound_phalp.strip():
        raise RecoveryAuthorityError("rig setup recovery authority has no PHALP checkout")
    if not _same_path(Path(bound_four_d), four_d):
        raise RecoveryAuthorityError(
            "4D-Humans checkout does not match the active rig setup recovery authority"
        )
    return Path(bound_phalp).expanduser().resolve()
