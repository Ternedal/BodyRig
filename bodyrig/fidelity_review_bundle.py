from __future__ import annotations

import argparse
import hashlib
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
RENDER_SET_FORMAT = "bodyrig-fidelity-render-set"
RENDER_SET_VERSION = 1
RENDER_SET_SEMANTICS = "visual-fidelity-not-identity-verification"
KNOWN_BAD_PACKAGE_SHA256 = "8a8915658201eb8a391a3a2771b2e36bc4fe0e20d293259e015938d5aa6f1897"


class FidelityReviewBundleError(ValueError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise FidelityReviewBundleError(f"could not hash review artifact: {path}") from exc
    return digest.hexdigest()


def _need_sha256(value: Any, *, label: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64 or any(char not in "0123456789abcdef" for char in raw):
        raise FidelityReviewBundleError(f"{label} is not a canonical SHA-256")
    return raw


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FidelityReviewBundleError(f"{label} not found: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FidelityReviewBundleError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise FidelityReviewBundleError(f"{label} must be an object")
    return value


def _snapshots_dir(
    path: str | os.PathLike[str],
    *,
    label: str,
    expected_package_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    resolved = Path(path).expanduser().resolve()
    if resolved.is_dir() and resolved.name == "snapshots":
        root = resolved
    elif (resolved / "snapshots").is_dir():
        root = resolved / "snapshots"
    else:
        raise FidelityReviewBundleError(f"{label} snapshots directory not found: {resolved}")

    manifest_path = root / "fidelity-render-set.json"
    manifest = _read_json(manifest_path, label=f"{label} fidelity-render-set.json")
    if (
        manifest.get("format") != RENDER_SET_FORMAT
        or manifest.get("version") != RENDER_SET_VERSION
        or manifest.get("semantics") != RENDER_SET_SEMANTICS
    ):
        raise FidelityReviewBundleError(f"{label} fidelity-render-set format/version/semantics mismatch")
    package_sha = _need_sha256(manifest.get("package_sha256"), label=f"{label} render-set package SHA")
    if package_sha != _need_sha256(expected_package_sha256, label=f"{label} expected package SHA"):
        raise FidelityReviewBundleError(f"{label} render-set is not bound to the expected package bytes")

    entries = manifest.get("snapshots")
    if not isinstance(entries, list) or len(entries) != len(SNAPSHOTS):
        raise FidelityReviewBundleError(f"{label} fidelity-render-set must contain exactly four canonical snapshots")
    for index, (name, _) in enumerate(SNAPSHOTS):
        entry = entries[index]
        expected_view = name.removesuffix(".png")
        if not isinstance(entry, dict):
            raise FidelityReviewBundleError(f"{label} canonical snapshot entry is invalid: {expected_view}")
        if entry.get("view") != expected_view or entry.get("file") != name:
            raise FidelityReviewBundleError(f"{label} canonical snapshot order/file binding mismatch: {expected_view}")
        if entry.get("width") != 1024 or entry.get("height") != 1024:
            raise FidelityReviewBundleError(f"{label} canonical snapshot dimensions are invalid: {name}")
        image = root / name
        if not image.is_file():
            raise FidelityReviewBundleError(f"{label} canonical snapshot missing: {name}")
        expected_sha = _need_sha256(entry.get("sha256"), label=f"{label} {name} SHA")
        if _sha256_file(image) != expected_sha:
            raise FidelityReviewBundleError(f"{label} canonical snapshot hash mismatch: {name}")
    return root, manifest


def _read_evidence(path: str | os.PathLike[str]) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    value = _read_json(resolved, label="A/B evidence")
    if value.get("format") != EVIDENCE_FORMAT or value.get("version") != EVIDENCE_VERSION:
        raise FidelityReviewBundleError("unsupported A/B evidence format/version")
    invariants = value.get("invariants")
    if not isinstance(invariants, dict) or invariants.get("clean_appearance_ab") is not True:
        raise FidelityReviewBundleError("review bundle requires passing clean appearance A/B evidence")
    left = value.get("left")
    right = value.get("right")
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise FidelityReviewBundleError("A/B evidence is missing package-side authority")
    _need_sha256(left.get("package_sha256"), label="#40 A/B package SHA")
    _need_sha256(right.get("package_sha256"), label="#41 A/B package SHA")
    if value.get("human_visual_authority_required") is not True or value.get("production_activation") is not False:
        raise FidelityReviewBundleError("A/B evidence has invalid human/production authority semantics")
    return value


def _copy_exact(source: Path, destination: Path, *, label: str) -> None:
    before = _sha256_file(source)
    shutil.copyfile(source, destination)
    if _sha256_file(destination) != before:
        raise FidelityReviewBundleError(f"{label} changed while copying into the review bundle")


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
    evidence_path = Path(ab_evidence).expanduser().resolve()
    evidence = _read_evidence(evidence_path)
    historical, _ = _snapshots_dir(
        historical_render,
        label="historical baseline",
        expected_package_sha256=KNOWN_BAD_PACKAGE_SHA256,
    )
    pr40, _ = _snapshots_dir(
        pr40_render,
        label="#40",
        expected_package_sha256=str(evidence["left"]["package_sha256"]),
    )
    pr41, _ = _snapshots_dir(
        pr41_render,
        label="#41",
        expected_package_sha256=str(evidence["right"]["package_sha256"]),
    )
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
                _copy_exact(source / name, temp / target_name, label=f"{prefix} {name}")
                image_map[(prefix, name)] = target_name
            _copy_exact(
                source / "fidelity-render-set.json",
                temp / f"{prefix}-fidelity-render-set.json",
                label=f"{prefix} render-set manifest",
            )
        _copy_exact(evidence_path, temp / "fidelity-ab-evidence.json", label="A/B evidence")

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
<p class="notice"><strong>Machine boundary:</strong> clean #40 → #41 appearance-only A/B is PASS and every displayed PNG is SHA-bound to its renderer manifest/package. This page still does not decide visual quality. Human review remains authoritative; production activation remains false.</p>
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
