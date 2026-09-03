from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

from .person_body_review import CANONICAL_VIEWS
from .person_source_alignment import file_sha256
from .recovery_throughput_sampling_audit import RecoverySamplingAuditError, RunEvidence, audit, collect_run

FORMAT = "bodyrig-recovery-throughput-review-bundle"
VERSION = 1
SEMANTICS = "human-visual-ab-review-not-promotion-authority"


class RecoveryThroughputReviewBundleError(ValueError):
    pass


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _view_entry(run: RunEvidence, view: str) -> tuple[Path, dict[str, Any]]:
    for item in run.review.get("views", []):
        if isinstance(item, Mapping) and item.get("view") == view:
            source = Path(str(run.review["root"])) / str(item["file"])
            if not source.is_file():
                raise RecoveryThroughputReviewBundleError(f"persisted review image is missing: {view}")
            expected = str(item.get("sha256") or "").strip().lower()
            actual = file_sha256(source)
            if actual != expected:
                raise RecoveryThroughputReviewBundleError(f"persisted review image SHA changed: {view}")
            return source, dict(item)
    raise RecoveryThroughputReviewBundleError(f"persisted review does not contain canonical view: {view}")


def _render_html(*, baseline: RunEvidence, candidate: RunEvidence, machine: Mapping[str, Any]) -> str:
    rows = []
    for view in CANONICAL_VIEWS:
        rows.append(
            "<section class=\"view\">"
            f"<h2>{view}</h2>"
            "<div class=\"pair\">"
            f"<figure><figcaption>Baseline</figcaption><img src=\"baseline/{view}.png\" alt=\"Baseline {view}\"></figure>"
            f"<figure><figcaption>Candidate</figcaption><img src=\"candidate/{view}.png\" alt=\"Candidate {view}\"></figure>"
            "</div></section>"
        )
    baseline_seconds = machine.get("timing", {}).get("baseline_clone_pipeline_seconds")
    candidate_seconds = machine.get("timing", {}).get("candidate_clone_pipeline_seconds")
    baseline_frames = machine.get("frames", {}).get("baseline")
    candidate_frames = machine.get("frames", {}).get("candidate")
    return """<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>BodyRig recovery throughput A/B review</title>
<style>
body{font-family:system-ui,sans-serif;margin:2rem;background:#111;color:#eee}main{max-width:1500px;margin:auto}.notice{padding:1rem;border:1px solid #777;background:#1b1b1b}.view{margin:2rem 0}.pair{display:grid;grid-template-columns:1fr 1fr;gap:1rem}figure{margin:0}img{display:block;width:100%;height:auto;background:#000}figcaption{font-weight:700;margin-bottom:.5rem}code{word-break:break-all}@media(max-width:800px){.pair{grid-template-columns:1fr}}</style>
</head><body><main>
<h1>BodyRig recovery throughput A/B review</h1>
<div class=\"notice\"><strong>Human comparison only.</strong> This bundle cannot grant promotion or production authority. Review identity-bearing shape, face, skin/texture alignment and gross anatomy across all four canonical views.</div>
<p>Person: <code>""" + str(baseline.job.get("person_id")) + """</code><br>
Baseline job: <code>""" + str(baseline.job.get("job_id")) + """</code><br>
Candidate job: <code>""" + str(candidate.job.get("job_id")) + """</code><br>
Recovery frames: """ + str(baseline_frames) + " → " + str(candidate_frames) + """<br>
Clone-pipeline seconds: """ + str(baseline_seconds) + " → " + str(candidate_seconds) + """</p>
""" + "\n".join(rows) + """
</main></body></html>\n"""


def verify_bundle(path: str | Path) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    receipt_path = root / "review-bundle.json"
    if not receipt_path.is_file():
        raise RecoveryThroughputReviewBundleError("review bundle receipt is missing")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryThroughputReviewBundleError("review bundle receipt is invalid JSON") from exc
    if not isinstance(receipt, dict) or receipt.get("format") != FORMAT or receipt.get("version") != VERSION:
        raise RecoveryThroughputReviewBundleError("review bundle receipt format/version mismatch")
    if receipt.get("semantics") != SEMANTICS:
        raise RecoveryThroughputReviewBundleError("review bundle semantics mismatch")
    if receipt.get("human_visual_review_required") is not True:
        raise RecoveryThroughputReviewBundleError("review bundle must require human visual review")
    if receipt.get("promotion_authority") is not False or receipt.get("production_activation") is not False:
        raise RecoveryThroughputReviewBundleError("review bundle cannot carry promotion/production authority")
    files = receipt.get("files")
    if not isinstance(files, list) or not files:
        raise RecoveryThroughputReviewBundleError("review bundle file manifest is missing")
    expected_names: set[str] = set()
    for item in files:
        if not isinstance(item, Mapping):
            raise RecoveryThroughputReviewBundleError("review bundle file entry is invalid")
        name = str(item.get("path") or "")
        expected = str(item.get("sha256") or "").strip().lower()
        if not name or name.startswith("/") or ".." in Path(name).parts:
            raise RecoveryThroughputReviewBundleError("review bundle file path is invalid")
        target = root / name
        if not target.is_file() or file_sha256(target) != expected:
            raise RecoveryThroughputReviewBundleError(f"review bundle file has changed: {name}")
        expected_names.add(name)
    actual_names = {
        str(item.relative_to(root)).replace("\\", "/")
        for item in root.rglob("*")
        if item.is_file() and item.name != "review-bundle.json"
    }
    if actual_names != expected_names:
        raise RecoveryThroughputReviewBundleError("review bundle contains missing or unexpected files")
    return receipt


def build_bundle(
    baseline_job: str | Path,
    candidate_job: str | Path,
    *,
    expected_candidate_bodyrig_revision: str,
    out_dir: str | Path,
    person_root: str | Path | None = None,
) -> dict[str, Any]:
    machine = audit(
        baseline_job,
        candidate_job,
        expected_candidate_bodyrig_revision=expected_candidate_bodyrig_revision,
        person_root=person_root,
    )
    if machine.get("machine_evidence_pass") is not True or machine.get("decision") != "eligible-for-human-ab-review":
        blockers = machine.get("blockers") or []
        raise RecoveryThroughputReviewBundleError(
            "machine A/B gate did not pass" + (f": {'; '.join(str(item) for item in blockers)}" if blockers else "")
        )
    baseline = collect_run(baseline_job, person_root=person_root)
    candidate = collect_run(candidate_job, person_root=person_root)

    target = Path(out_dir).expanduser().resolve()
    if target.exists():
        raise RecoveryThroughputReviewBundleError(f"refusing to overwrite existing review bundle: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    try:
        (temp / "baseline").mkdir(parents=True)
        (temp / "candidate").mkdir(parents=True)
        file_rows: list[dict[str, str]] = []
        view_rows: list[dict[str, Any]] = []
        for view in CANONICAL_VIEWS:
            baseline_source, baseline_entry = _view_entry(baseline, view)
            candidate_source, candidate_entry = _view_entry(candidate, view)
            baseline_target = temp / "baseline" / f"{view}.png"
            candidate_target = temp / "candidate" / f"{view}.png"
            shutil.copyfile(baseline_source, baseline_target)
            shutil.copyfile(candidate_source, candidate_target)
            if file_sha256(baseline_target) != baseline_entry["sha256"]:
                raise RecoveryThroughputReviewBundleError(f"baseline image changed while copying: {view}")
            if file_sha256(candidate_target) != candidate_entry["sha256"]:
                raise RecoveryThroughputReviewBundleError(f"candidate image changed while copying: {view}")
            file_rows.extend(
                [
                    {"path": f"baseline/{view}.png", "sha256": baseline_entry["sha256"]},
                    {"path": f"candidate/{view}.png", "sha256": candidate_entry["sha256"]},
                ]
            )
            view_rows.append(
                {
                    "view": view,
                    "baseline_sha256": baseline_entry["sha256"],
                    "candidate_sha256": candidate_entry["sha256"],
                    "width": 1024,
                    "height": 1024,
                }
            )

        machine_path = temp / "machine-audit.json"
        _write_json(machine_path, machine)
        html_path = temp / "index.html"
        html_path.write_text(
            _render_html(baseline=baseline, candidate=candidate, machine=machine),
            encoding="utf-8",
            newline="\n",
        )
        file_rows.extend(
            [
                {"path": "machine-audit.json", "sha256": file_sha256(machine_path)},
                {"path": "index.html", "sha256": file_sha256(html_path)},
            ]
        )
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "semantics": SEMANTICS,
            "person_id": baseline.job.get("person_id"),
            "baseline_job_id": baseline.job.get("job_id"),
            "candidate_job_id": candidate.job.get("job_id"),
            "baseline_bodyrig_revision": baseline.job.get("bodyrig_revision"),
            "candidate_bodyrig_revision": candidate.job.get("bodyrig_revision"),
            "baseline_package_sha256": baseline.package_sha256,
            "candidate_package_sha256": candidate.package_sha256,
            "views": view_rows,
            "files": sorted(file_rows, key=lambda item: item["path"]),
            "human_visual_review_required": True,
            "promotion_authority": False,
            "production_activation": False,
        }
        _write_json(temp / "review-bundle.json", receipt)
        os.replace(temp, target)
    except Exception:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
        raise
    return verify_bundle(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a create-only, hash-bound human A/B review bundle after machine throughput audit PASS.")
    parser.add_argument("baseline_job")
    parser.add_argument("candidate_job")
    parser.add_argument("--expected-candidate-bodyrig-revision", required=True)
    parser.add_argument("--person-root", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        result = build_bundle(
            args.baseline_job,
            args.candidate_job,
            expected_candidate_bodyrig_revision=args.expected_candidate_bodyrig_revision,
            out_dir=args.out,
            person_root=args.person_root or None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, RecoverySamplingAuditError, RecoveryThroughputReviewBundleError, ValueError) as exc:
        print(f"BodyRig recovery throughput review bundle: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
