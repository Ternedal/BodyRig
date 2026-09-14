from pathlib import Path

path = Path("tests/test_fidelity_component_gap_executor.py")
text = path.read_text(encoding="utf-8")
anchor = '        "prepare-hands-feet-nails-fingernail-geometry-candidate.ps1",\n'
if text.count(anchor) != 1:
    raise SystemExit("executor fixture script anchor mismatch")
text = text.replace(
    anchor,
    '        "prepare-hands-feet-nails-detail-candidate.ps1",\n' + anchor,
    1,
)
text = text.replace('"body_id": "body-example",', '"body_id": "performer-42",')
path.write_text(text, encoding="utf-8", newline="\n")
