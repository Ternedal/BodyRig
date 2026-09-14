from __future__ import annotations

from pathlib import Path

PRODUCT = Path("bodyrig/wardrobe_source_capture.py")
TEST = Path("tests/test_wardrobe_source_capture.py")

product = PRODUCT.read_text(encoding="utf-8")
old = '    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:\n'
new = '    if value.get("format") != FORMAT or isinstance(value.get("version"), bool) or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:\n'
if product.count(old) != 1:
    raise SystemExit(f"expected exactly one source-capture v1 gate, found {product.count(old)}")
PRODUCT.write_text(product.replace(old, new), encoding="utf-8", newline="\n")

test = TEST.read_text(encoding="utf-8")
import_old = "from __future__ import annotations\n\nimport struct\n"
import_new = "from __future__ import annotations\n\nimport json\nimport struct\n"
if import_old not in test:
    raise SystemExit("test import anchor missing")
test = test.replace(import_old, import_new, 1)
marker = "def test_read_source_capture_rejects_noncanonical_v1_versions"
if marker in test:
    raise SystemExit("focused v1 regressions already present")
append = r'''


def _prepare_capture_for_version_test(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, Path]:
    source = _source(tmp_path)
    monkeypatch.setattr(wardrobe, "_source_authority", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(wardrobe, "_run_version", lambda *_args, **_kwargs: "ffmpeg version fixture")
    monkeypatch.setattr(
        wardrobe,
        "_extract",
        lambda *, output, media, **_kwargs: _fake_png(output, media.name.encode("utf-8")),
    )
    receipt = wardrobe.prepare_source_capture(
        tmp_path,
        PERSON_ID,
        body_revision=BODY_REVISION,
        bodyrig_revision=BODYRIG_REVISION,
        views=_views(),
        garments=_garments(),
    )
    manifest = wardrobe.capture_dir(
        tmp_path,
        PERSON_ID,
        BODY_REVISION,
        receipt["capture_id"],
    ) / "source-capture.json"
    return receipt, manifest


@pytest.mark.parametrize("bad_version", [True, False, "1", None, 2])
def test_read_source_capture_rejects_noncanonical_v1_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_version: object,
) -> None:
    receipt, manifest = _prepare_capture_for_version_test(tmp_path, monkeypatch)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["version"] = bad_version
    manifest.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    with pytest.raises(wardrobe.WardrobeSourceCaptureError, match="format/version/policy"):
        wardrobe.read_source_capture(
            tmp_path,
            PERSON_ID,
            body_revision=BODY_REVISION,
            capture_id=receipt["capture_id"],
        )


def test_read_source_capture_accepts_numeric_float_v1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, manifest = _prepare_capture_for_version_test(tmp_path, monkeypatch)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["version"] = 1.0
    manifest.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    reread = wardrobe.read_source_capture(
        tmp_path,
        PERSON_ID,
        body_revision=BODY_REVISION,
        capture_id=receipt["capture_id"],
    )
    assert reread["version"] == 1.0
    assert reread["source_grounded"] is True
    assert reread["comparison_only"] is True
    assert reread["human_review_required"] is True
    assert reread["production_activation"] is False
'''
TEST.write_text(test.rstrip() + append + "\n", encoding="utf-8", newline="\n")
