from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping

from .person_source_alignment import file_sha256

FORMAT = "bodyrig-person-body-review"
VERSION = 1
FIDELITY_FORMAT = "bodyrig-fidelity-render-set"
FIDELITY_VERSION = 1
COMPARISON_FORMAT = "bodyrig-fidelity-comparison-authority"
COMPARISON_VERSION = 1
SEMANTICS = "visual-fidelity-not-identity-verification"
CANONICAL_VIEWS = ("front-full", "three-quarter-full", "side-full", "face-front")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PERSON_ID_RE = re.compile(r"^person-[0-9a-f]{32}$")


class PersonBodyReviewError(ValueError):
    pass


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise PersonBodyReviewError(f"{label} is not a canonical SHA-256")
    return text


def _person_id(value: Any) -> str:
    text = str(value or "").strip()
    if not PERSON_ID_RE.fullmatch(text):
        raise PersonBodyReviewError("person_id is invalid")
    return text


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PersonBodyReviewError(f"{label} is missing: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonBodyReviewError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PersonBodyReviewError(f"{label} must be an object")
    return value


def _body_revision(profile: Mapping[str, Any], revision_id: str) -> dict[str, Any]:
    for item in profile.get("body_revisions", []):
        if isinstance(item, Mapping) and item.get("revision_id") == revision_id:
            return dict(item)
    raise PersonBodyReviewError("unknown body revision")


def _review_root(root: str | os.PathLike[str], person_id: str, package_sha256: str) -> Path:
    return Path(root).expanduser().resolve() / ".body-reviews" / _person_id(person_id) / _sha(package_sha256, "package_sha256")


def validate_fidelity_output(
    output_dir: str | os.PathLike[str],
    *,
    body_id: str,
    package_sha256: str,
) -> dict[str, Any]:
    root = Path(output_dir).expanduser().resolve()
    if not root.is_dir():
        raise PersonBodyReviewError("fidelity render output directory is missing")
    expected_package = _sha(package_sha256, "package_sha256")
    expected_body = str(body_id or "").strip()
    if not expected_body:
        raise PersonBodyReviewError("body_id is required")

    comparison_path = root / "comparison-authority.json"
    comparison = _read_json(comparison_path, "fidelity comparison authority")
    expected_comparison_fields = {
        "format",
        "version",
        "authority",
        "bodyrig_revision",
        "runtime_manifest_sha256",
        "package_sha256",
        "physical_acceptance_authority",
        "comparison_only",
        "production_activation",
    }
    if set(comparison) != expected_comparison_fields:
        raise PersonBodyReviewError("fidelity comparison authority fields are invalid")
    if comparison.get("format") != COMPARISON_FORMAT or comparison.get("version") != COMPARISON_VERSION:
        raise PersonBodyReviewError("fidelity comparison authority format/version mismatch")
    if comparison.get("authority") != "gate-a-pending-candidate":
        raise PersonBodyReviewError("fidelity render set is not backed by Gate A pending-candidate authority")
    if comparison.get("physical_acceptance_authority") is not True or comparison.get("comparison_only") is not True:
        raise PersonBodyReviewError("fidelity comparison authority flags are invalid")
    if comparison.get("production_activation") is not False:
        raise PersonBodyReviewError("fidelity comparison authority must remain non-activating")
    if _sha(comparison.get("package_sha256"), "comparison.package_sha256") != expected_package:
        raise PersonBodyReviewError("fidelity comparison authority package SHA does not match the body candidate")
    _sha(comparison.get("runtime_manifest_sha256"), "comparison.runtime_manifest_sha256")
    revision = str(comparison.get("bodyrig_revision") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise PersonBodyReviewError("fidelity comparison authority BodyRig revision is invalid")

    snapshots_dir = root / "snapshots"
    manifest_path = snapshots_dir / "fidelity-render-set.json"
    manifest = _read_json(manifest_path, "fidelity render-set manifest")
    if set(manifest) != {"format", "version", "body_id", "package_sha256", "semantics", "snapshots"}:
        raise PersonBodyReviewError("fidelity render-set fields are invalid")
    if manifest.get("format") != FIDELITY_FORMAT or manifest.get("version") != FIDELITY_VERSION:
        raise PersonBodyReviewError("fidelity render-set format/version mismatch")
    if manifest.get("semantics") != SEMANTICS:
        raise PersonBodyReviewError("fidelity render-set semantics mismatch")
    if str(manifest.get("body_id") or "") != expected_body:
        raise PersonBodyReviewError("fidelity render-set body id does not match the body candidate")
    if _sha(manifest.get("package_sha256"), "render-set.package_sha256") != expected_package:
        raise PersonBodyReviewError("fidelity render-set package SHA does not match the body candidate")

    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list) or len(snapshots) != len(CANONICAL_VIEWS):
        raise PersonBodyReviewError("fidelity render-set must contain exactly four canonical views")
    views: list[dict[str, Any]] = []
    for expected_view, snapshot in zip(CANONICAL_VIEWS, snapshots, strict=True):
        if not isinstance(snapshot, Mapping) or set(snapshot) != {"view", "file", "sha256", "width", "height"}:
            raise PersonBodyReviewError("fidelity snapshot fields are invalid")
        view = str(snapshot.get("view") or "")
        filename = str(snapshot.get("file") or "")
        if view != expected_view or filename != f"{expected_view}.png":
            raise PersonBodyReviewError("fidelity canonical view order/name binding mismatch")
        if snapshot.get("width") != 1024 or snapshot.get("height") != 1024:
            raise PersonBodyReviewError("fidelity snapshots must be 1024x1024")
        expected_sha = _sha(snapshot.get("sha256"), f"snapshot.{view}.sha256")
        image_path = snapshots_dir / filename
        if not image_path.is_file():
            raise PersonBodyReviewError(f"fidelity snapshot is missing: {filename}")
        actual_sha = file_sha256(image_path)
        if actual_sha != expected_sha:
            raise PersonBodyReviewError(f"fidelity snapshot bytes no longer match manifest: {filename}")
        views.append(
            {
                "view": view,
                "file": filename,
                "sha256": expected_sha,
                "width": 1024,
                "height": 1024,
            }
        )

    return {
        "body_id": expected_body,
        "package_sha256": expected_package,
        "bodyrig_revision": revision,
        "runtime_manifest_sha256": _sha(comparison["runtime_manifest_sha256"], "comparison.runtime_manifest_sha256"),
        "comparison_authority_path": str(comparison_path),
        "comparison_authority_sha256": file_sha256(comparison_path),
        "render_manifest_path": str(manifest_path),
        "render_manifest_sha256": file_sha256(manifest_path),
        "snapshots_dir": str(snapshots_dir),
        "views": views,
    }


def persist_review(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    fidelity_output_dir: str | os.PathLike[str],
    body_id: str,
    package_sha256: str,
) -> dict[str, Any]:
    validated = validate_fidelity_output(
        fidelity_output_dir,
        body_id=body_id,
        package_sha256=package_sha256,
    )
    target = _review_root(root, person_id, validated["package_sha256"])
    receipt_path = target / "review.json"
    if receipt_path.is_file():
        return read_review_by_package(root, person_id=person_id, package_sha256=validated["package_sha256"])
    if target.exists():
        raise PersonBodyReviewError("body review target exists without a valid receipt")

    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp = parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    snapshots_source = Path(validated["snapshots_dir"])
    try:
        temp.mkdir()
        for view in validated["views"]:
            source = snapshots_source / view["file"]
            destination = temp / view["file"]
            shutil.copyfile(source, destination)
            if file_sha256(destination) != view["sha256"]:
                raise PersonBodyReviewError(f"fidelity snapshot changed while persisting review: {view['file']}")
        shutil.copyfile(validated["render_manifest_path"], temp / "fidelity-render-set.json")
        shutil.copyfile(validated["comparison_authority_path"], temp / "comparison-authority.json")
        if file_sha256(temp / "fidelity-render-set.json") != validated["render_manifest_sha256"]:
            raise PersonBodyReviewError("fidelity render manifest changed while persisting review")
        if file_sha256(temp / "comparison-authority.json") != validated["comparison_authority_sha256"]:
            raise PersonBodyReviewError("fidelity comparison authority changed while persisting review")

        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "person_id": _person_id(person_id),
            "body_id": validated["body_id"],
            "package_sha256": validated["package_sha256"],
            "bodyrig_revision": validated["bodyrig_revision"],
            "runtime_manifest_sha256": validated["runtime_manifest_sha256"],
            "semantics": SEMANTICS,
            "render_manifest_sha256": validated["render_manifest_sha256"],
            "comparison_authority_sha256": validated["comparison_authority_sha256"],
            "views": validated["views"],
        }
        (temp / "review.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temp, target)
    except Exception:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
        raise
    return read_review_by_package(root, person_id=person_id, package_sha256=validated["package_sha256"])


def read_review_by_package(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    package_sha256: str,
) -> dict[str, Any]:
    target = _review_root(root, person_id, package_sha256)
    receipt = _read_json(target / "review.json", "body review receipt")
    expected_fields = {
        "format",
        "version",
        "person_id",
        "body_id",
        "package_sha256",
        "bodyrig_revision",
        "runtime_manifest_sha256",
        "semantics",
        "render_manifest_sha256",
        "comparison_authority_sha256",
        "views",
    }
    if set(receipt) != expected_fields or receipt.get("format") != FORMAT or receipt.get("version") != VERSION:
        raise PersonBodyReviewError("body review receipt format/fields mismatch")
    if receipt.get("person_id") != _person_id(person_id):
        raise PersonBodyReviewError("body review person identity mismatch")
    expected_package = _sha(package_sha256, "package_sha256")
    if _sha(receipt.get("package_sha256"), "review.package_sha256") != expected_package:
        raise PersonBodyReviewError("body review package identity mismatch")
    if receipt.get("semantics") != SEMANTICS:
        raise PersonBodyReviewError("body review semantics mismatch")
    render_manifest_sha = _sha(receipt.get("render_manifest_sha256"), "review.render_manifest_sha256")
    comparison_sha = _sha(receipt.get("comparison_authority_sha256"), "review.comparison_authority_sha256")
    if file_sha256(target / "fidelity-render-set.json") != render_manifest_sha:
        raise PersonBodyReviewError("persisted fidelity render manifest has changed")
    if file_sha256(target / "comparison-authority.json") != comparison_sha:
        raise PersonBodyReviewError("persisted fidelity comparison authority has changed")

    views = receipt.get("views")
    if not isinstance(views, list) or len(views) != len(CANONICAL_VIEWS):
        raise PersonBodyReviewError("body review canonical views are invalid")
    clean_views: list[dict[str, Any]] = []
    for expected_view, view in zip(CANONICAL_VIEWS, views, strict=True):
        if not isinstance(view, Mapping) or set(view) != {"view", "file", "sha256", "width", "height"}:
            raise PersonBodyReviewError("body review view fields are invalid")
        if view.get("view") != expected_view or view.get("file") != f"{expected_view}.png":
            raise PersonBodyReviewError("body review canonical view identity mismatch")
        expected_sha = _sha(view.get("sha256"), f"review.{expected_view}.sha256")
        path = target / str(view["file"])
        if file_sha256(path) != expected_sha:
            raise PersonBodyReviewError(f"persisted body review image has changed: {view['file']}")
        clean_views.append(dict(view))
    return {**receipt, "views": clean_views, "root": str(target)}


def read_review(
    root: str | os.PathLike[str],
    profile: Mapping[str, Any],
    *,
    body_revision: str,
) -> dict[str, Any]:
    item = _body_revision(profile, body_revision)
    review = read_review_by_package(
        root,
        person_id=str(profile.get("person_id") or ""),
        package_sha256=str(item.get("package_sha256") or ""),
    )
    if review.get("body_id") != item.get("body_id"):
        raise PersonBodyReviewError("body review body id no longer matches the registered revision")
    return review


def review_image_path(
    root: str | os.PathLike[str],
    profile: Mapping[str, Any],
    *,
    body_revision: str,
    view: str,
) -> Path:
    if view not in CANONICAL_VIEWS:
        raise PersonBodyReviewError("unknown canonical body review view")
    review = read_review(root, profile, body_revision=body_revision)
    entry = next(item for item in review["views"] if item["view"] == view)
    return Path(review["root"]) / entry["file"]
