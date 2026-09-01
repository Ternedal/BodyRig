from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

SNAPSHOTS = (
    ("front-full.png", "Front"),
    ("three-quarter-full.png", "3/4"),
    ("side-full.png", "Side"),
    ("face-front.png", "Face"),
)
EVIDENCE_FORMAT = "bodyrig-fidelity-ab-evidence"
EVIDENCE_VERSION = 1


class FidelityReviewBundleError(ValueError):
    pass


def _snapshots_dir(path: str | os.PathLike[str], *, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved.is_dir() and resolved.name == "snapshots":
        root = resolved
    elif (resolved / "snapshots").is_dir():
        root = resolved / "snapshots"
    else:
        raise FidelityReviewBundleError(f"{label} snapshots directory not found: {resolved}")
    for name, _ in SNAPSHOTS:
        if not (root / name).is_file():
            raise FidelityReviewBundleError(f"{label} canonical snapshot missing: {name}")
    manifest = root / "fidelity-render-set.json"
    if not manifest.is_file():
        raise FidelityReviewBundleError(f"{label} fidelity-render-set.json is missing")
    try:
        value = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FidelityReviewBundleError(f"{label} fidelity-render-set.json is invalid") from exc
    if not isinstance(value, dict):
        raise FidelityReviewBundleError(f"{label} fidelity-render-set.json must be an object")
    return root


def _read_evidence(path: str | os.PathLike[str]) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FidelityReviewBundleError(f"A/B evidence not found: {resolved}")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FidelityReviewBundleError("A/B evidence is invalid JSON") from exc
    if not isinstance(value, dict) or value.get("format") != EVIDENCE_FORMAT or value.get("version") != EVIDENCE_VERSION:
        raise FidelityReviewBundleError("unsupported A/B evidence format/version")
    invariants = value.get("invariants")
    if not isinstance(invariants, dict) or invariants.get("clean_appearance_ab") is not True:
        raise FidelityReviewBundleError("review bundle requires passing clean appearance A/B evidence")
    if value.get("human_visual_authority_required") is not True or value.get("production_activation") is not False:
        raise FidelityReviewBundleError("A/B evidence has invalid human/production authority semantics")
    return value


def _short_sha(value: Any) -> str:
    raw = str(value or "")
    return raw[:12] + "…" if len(raw) > 12 else raw


def _invariant_table(evidence: Mapping[str, Any]) -> str:
    invariants = evidence["invariants"]
    labels = (
        ("body_id_identical", "Body ID"),
        ("bodyprint_identical", "BodyPrint"),
        ("geometry_identical", "Geometry"),
        ("skin_binding_identical", "Skin binding"),
        ("rig_identical", "Humanoid rig"),
        ("appearance_changed", "Appearance changed"),
    )
    rows = []
    for key, label in labels:
        ok = invariants.get(key) is True
        rows.append(f"<tr><th>{html.escape(label)}</th><td>{'PASS' if ok else 'FAIL'}</td></tr>")
    left = evidence.get("left", {})
    right = evidence.get("right", {})
    rows.extend(
        [
            f"<tr><th>#40 geometry SHA</th><td><code>{html.escape(_short_sha(left.get('geometry_surface_sha256')))}</code></td></tr>",
            f"<tr><th>#41 geometry SHA</th><td><code>{html.escape(_short_sha(right.get('geometry_surface_sha256')))}</code></td></tr>",
            f"<tr><th>#40 package SHA</th><td><code>{html.escape(_short_sha(left.get('package_sha256')))}</code></td></tr>",
            f"<tr><th>#41 package SHA</th><td><code>{html.escape(_short_sha(right.get('package_sha256')))}</code></td></tr>",
        ]
    )
    return "<table class='invariants'>" + "".join(rows) + "</table>"


def build_review_bundle(
    *,
    historical_render: str | os.PathLike[str],
    pr40_render: str | os.PathLike[str],
    pr41_render: str | os.PathLike[str],
    ab_evidence: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
) -> Path:
    historical = _snapshots_dir(historical_render, label="historical baseline")
    pr40 = _snapshots_dir(pr40_render, label="#40")
    pr41 = _snapshots_dir(pr41_render, label="#41")
    evidence = _read_evidence(ab_evidence)
    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise FidelityReviewBundleError(f"review bundle output already exists: {output}")

    temp = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    if temp.exists():
        raise FidelityReviewBundleError(f"temporary review bundle already exists: {temp}")
    temp.mkdir(parents=True)
    try:
        columns = (
            ("historical", "Historical bad baseline", historical),
            ("pr40", "#40 · donor topology", pr40),
            ("pr41", "#41 · seam-aware UV", pr41),
        )
        image_map: dict[tuple[str, str], str] = {}
        for prefix, _, source in columns:
            for name, _ in SNAPSHOTS:
                target_name = f"{prefix}-{name}"
                shutil.copyfile(source / name, temp / target_name)
                image_map[(prefix, name)] = target_name
            shutil.copyfile(source / "fidelity-render-set.json", temp / f"{prefix}-fidelity-render-set.json")
        shutil.copyfile(Path(ab_evidence).expanduser().resolve(), temp / "fidelity-ab-evidence.json")

        header_cells = "".join(f"<th>{html.escape(title)}</th>" for _, title, _ in columns)
        view_rows = []
        for name, label in SNAPSHOTS:
            cells = "".join(
                f"<td><img src='{html.escape(image_map[(prefix, name)])}' alt='{html.escape(title + ' ' + label)}'></td>"
                for prefix, title, _ in columns
            )
            view_rows.append(f"<tr class='view-label'><th colspan='3'>{html.escape(label)}</th></tr><tr>{cells}</tr>")

        page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BodyRig physical fidelity review</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
body {{ margin: 0; background: #111; color: #eee; }}
main {{ max-width: 1800px; margin: 0 auto; padding: 24px; }}
h1 {{ margin-bottom: 6px; }}
.notice {{ padding: 12px 16px; border: 1px solid #666; border-radius: 8px; background: #1b1b1b; }}
.invariants {{ border-collapse: collapse; margin: 18px 0 28px; }}
.invariants th,.invariants td {{ border-bottom: 1px solid #444; padding: 7px 12px; text-align: left; }}
.review {{ width: 100%; border-collapse: separate; border-spacing: 10px; table-layout: fixed; }}
.review th {{ font-size: 1rem; padding: 8px; }}
.review td {{ vertical-align: top; background: #181818; }}
.review img {{ display: block; width: 100%; height: auto; }}
.view-label th {{ padding-top: 28px; font-size: 1.15rem; text-align: left; }}
code {{ overflow-wrap: anywhere; }}
</style>
</head>
<body>
<main>
<h1>BodyRig physical fidelity review</h1>
<p class="notice"><strong>Machine boundary:</strong> clean #40 → #41 appearance-only A/B is PASS. This page does not decide visual quality. Human review remains authoritative; production activation remains false.</p>
{_invariant_table(evidence)}
<table class="review">
<thead><tr>{header_cells}</tr></thead>
<tbody>{''.join(view_rows)}</tbody>
</table>
</main>
</body>
</html>
"""
        (temp / "index.html").write_text(page, encoding="utf-8")
        temp.replace(output)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return output / "index.html"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a create-only three-column BodyRig physical fidelity review bundle.")
    parser.add_argument("--historical-render", required=True)
    parser.add_argument("--pr40-render", required=True)
    parser.add_argument("--pr41-render", required=True)
    parser.add_argument("--ab-evidence", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        index = build_review_bundle(
            historical_render=args.historical_render,
            pr40_render=args.pr40_render,
            pr41_render=args.pr41_render,
            ab_evidence=args.ab_evidence,
            output_dir=args.out,
        )
    except (FidelityReviewBundleError, OSError, ValueError) as exc:
        print(f"BodyRig fidelity review bundle: FAIL: {exc}", file=sys.stderr)
        return 1
    print(index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
