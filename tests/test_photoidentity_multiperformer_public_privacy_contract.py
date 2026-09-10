from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_multiperformer_manifests_do_not_persist_source_paths() -> None:
    discovery = (ROOT / "bodyrig" / "photoidentity_multiperformer_source_discovery.py").read_text(encoding="utf-8")
    review = (ROOT / "bodyrig" / "photoidentity_multiperformer_review_prepare.py").read_text(encoding="utf-8")
    attestation = (ROOT / "bodyrig" / "photoidentity_multiperformer_track_attestation.py").read_text(encoding="utf-8")

    assert '"source_paths_persisted": False' in discovery
    assert '"source_paths_persisted": False' in review
    assert '"source_paths_persisted": False' in attestation
    assert '"source_path": candidate.path' in discovery
    assert '"source_path": str(source)' in review
    assert '"source_path"' not in attestation.split('receipt = {', 1)[1].split('}', 1)[0]
